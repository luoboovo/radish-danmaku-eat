"""离线机器码授权：Ed25519 公钥验签，不在客户端保存签发私钥。"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


LICENSE_PREFIX = "RDEC1"
PUBLIC_KEY_B64 = "skVMWc9iug0kpmyyB3hzKknPxQqBLxcAKJLNsj29bqQ"
PLAN_LABELS = {
    "1d": "一天",
    "7d": "七天",
    "30d": "一个月",
    "90d": "一个季度",
    "permanent": "永久",
}


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    message: str
    machine_code: str
    plan: str = ""
    expires_at: int = 0
    key: str = ""

    @property
    def plan_label(self) -> str:
        return PLAN_LABELS.get(self.plan, self.plan or "未知")

    @property
    def expiry_text(self) -> str:
        if self.expires_at <= 0:
            return "永久"
        return datetime.fromtimestamp(
            self.expires_at, tz=timezone.utc
        ).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def canonical_payload(payload: Dict[str, Any]) -> bytes:
    """签发端与客户端共用的稳定 JSON 字节格式。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def normalize_machine_code(text: str) -> str:
    clean = "".join(character for character in str(text).upper() if character.isalnum())
    return "-".join(clean[index : index + 4] for index in range(0, len(clean), 4))


def machine_code() -> str:
    """生成稳定的 Windows 本机机器码，不上传任何硬件信息。"""
    identity = ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            identity = str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except (ImportError, OSError):
        identity = f"{uuid.getnode():012x}|{platform.node()}"
    digest = hashlib.sha256(
        f"RadishDanmakuEat|{identity}|{platform.machine()}".encode("utf-8")
    ).hexdigest().upper()[:24]
    return normalize_machine_code(digest)


def encode_license(payload: Dict[str, Any], signature: bytes) -> str:
    return f"{LICENSE_PREFIX}.{_b64encode(canonical_payload(payload))}.{_b64encode(signature)}"


def validate_license_key(
    key: str,
    expected_machine: Optional[str] = None,
    now: Optional[int] = None,
) -> LicenseStatus:
    expected = normalize_machine_code(expected_machine or machine_code())
    compact = "".join(str(key).split())
    try:
        prefix, payload_text, signature_text = compact.split(".", 2)
        if prefix != LICENSE_PREFIX:
            raise ValueError("prefix")
        payload_bytes = _b64decode(payload_text)
        signature = _b64decode(signature_text)
        public_key = Ed25519PublicKey.from_public_bytes(_b64decode(PUBLIC_KEY_B64))
        public_key.verify(signature, payload_bytes)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, InvalidSignature):
        return LicenseStatus(False, "密钥格式错误或签名无效", expected)

    licensed_machine = normalize_machine_code(payload.get("machine", ""))
    if not licensed_machine or licensed_machine != expected:
        return LicenseStatus(False, "密钥不属于这台电脑", expected)
    if int(payload.get("version", 0) or 0) != 1:
        return LicenseStatus(False, "密钥版本不受支持", expected)

    current = int(now if now is not None else time.time())
    issued_at = int(payload.get("issued_at", 0) or 0)
    expires_at = int(payload.get("expires_at", 0) or 0)
    plan = str(payload.get("plan", ""))
    if issued_at > current + 86400:
        return LicenseStatus(False, "系统时间异常：密钥签发时间位于未来", expected)
    if expires_at > 0 and current >= expires_at:
        return LicenseStatus(
            False,
            f"授权已于 {datetime.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S')} 到期",
            expected,
            plan,
            expires_at,
            compact,
        )
    return LicenseStatus(True, "授权有效", expected, plan, expires_at, compact)


def load_saved_license(path: Path) -> LicenseStatus:
    code = machine_code()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        key = str(data.get("key", ""))
        last_seen = int(data.get("last_seen_utc", 0) or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return LicenseStatus(False, "尚未激活，请输入授权密钥", code)
    now = int(time.time())
    if last_seen and now + 21600 < last_seen:
        return LicenseStatus(False, "检测到系统时间明显回退，请校准时间后重试", code)
    status = validate_license_key(key, code, now)
    if status.valid:
        save_license_key(path, key, max(now, last_seen))
    return status


def save_license_key(path: Path, key: str, last_seen: Optional[int] = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "key": "".join(str(key).split()),
                "last_seen_utc": int(last_seen or time.time()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
