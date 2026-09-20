"""B 站直播间礼物目录同步与本地图标缓存。"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from PyQt5.QtCore import QThread, pyqtSignal


API_URL = (
    "https://api.live.bilibili.com/xlive/web-room/v1/giftPanel/roomGiftList"
    "?platform=pc&room_id={room_id}"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


def _cache_root() -> Path:
    """礼物图片固定保存在程序/项目当前目录下，方便查看和随软件移动。"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "gift_images"


def _metadata_path() -> Path:
    return _cache_root() / "catalog.json"


def load_cached_gifts() -> List[Dict]:
    """读取已缓存目录；损坏或不存在时安静返回空列表。"""
    try:
        payload = json.loads(_metadata_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    result: List[Dict] = []
    for item in payload.get("gifts", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        icon_text = str(item.get("icon_path", "")).strip()
        icon_path = ""
        if icon_text:
            original = Path(icon_text)
            # 新版目录保存相对文件名；兼容旧版绝对路径，并优先使用当前
            # 程序目录中的安装包自带 gift_images，换电脑后仍能正常显示。
            local = _cache_root() / original.name
            if local.is_file():
                icon_path = str(local.resolve())
            elif original.is_file():
                icon_path = str(original.resolve())
        result.append(
            {
                "id": int(item.get("id", 0) or 0),
                "name": name,
                "price": int(item.get("price", 0) or 0),
                "icon_path": icon_path,
            }
        )
    return result


def cached_gift_icon(gift_name: str, gift_id: int = 0) -> str:
    """优先按礼物 ID 查图，名称只作为旧配置兼容，避免文字与图标串位。"""
    target = str(gift_name).strip()
    target_id = int(gift_id or 0)
    if not target and not target_id:
        return ""
    gifts = load_cached_gifts()
    if target_id:
        for item in gifts:
            if int(item.get("id", 0) or 0) == target_id:
                return str(item.get("icon_path", ""))
    for item in gifts:
        if item.get("name") == target:
            return str(item.get("icon_path", ""))
    return ""


def _normalize_image_url(value: object) -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        return "https:" + url
    return url if url.startswith(("https://", "http://")) else ""


def _image_url(item: Dict) -> str:
    # 浮窗优先使用 B 站基础 PNG：透明边缘更稳定，也不会带 WebP 的平台差异。
    for key in ("img_basic", "web_light", "webp", "img_dynamic", "gif"):
        url = _normalize_image_url(item.get(key))
        if url:
            return url
    return ""


def _safe_extension(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if re.fullmatch(r"\.(png|jpe?g|webp|gif|bmp)", suffix) else ".png"


class GiftCatalogSyncThread(QThread):
    """后台拉取当前直播间可用礼物，并并发缓存小图标。"""

    progress = pyqtSignal(int, int, str)
    catalog_ready = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, room_id: str, parent=None) -> None:
        super().__init__(parent)
        self.room_id = str(room_id).strip()

    def run(self) -> None:
        try:
            gifts = self._fetch_catalog()
            if self.isInterruptionRequested():
                return
            self._download_icons(gifts)
            if self.isInterruptionRequested():
                return
            gifts.sort(key=lambda item: (item["price"], item["name"]))
            self._save_metadata(gifts)
            self.catalog_ready.emit(gifts)
        except Exception as error:  # 网络失败不能影响设置窗口继续使用
            self.failed.emit(str(error))

    def _request(self, url: str, timeout: float = 15.0):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": f"https://live.bilibili.com/{self.room_id}",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        return urllib.request.urlopen(request, timeout=timeout)

    def _fetch_catalog(self) -> List[Dict]:
        self.progress.emit(0, 0, "正在获取直播间礼物列表…")
        with self._request(API_URL.format(room_id=self.room_id)) as response:
            payload = json.load(response)
        if int(payload.get("code", -1)) != 0:
            raise RuntimeError(str(payload.get("message") or "B站礼物接口返回异常"))
        data = payload.get("data") or {}
        gift_config = data.get("gift_config") or {}
        raw_list = list(
            ((gift_config.get("base_config") or {}).get("list")) or []
        )
        # 房间配置中还包含舰长等专属礼物，不能只读取通用礼物。
        room_config = gift_config.get("room_config") or []
        if isinstance(room_config, list):
            raw_list.extend(room_config)
        # 同名礼物只保留一项，优先选择有图标且 ID 有效的版本。
        unique: Dict[str, Dict] = {}
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            candidate = {
                "id": int(raw.get("id", 0) or 0),
                "name": name,
                "price": int(raw.get("price", 0) or 0),
                "image_url": _image_url(raw),
                "icon_path": "",
            }
            current = unique.get(name)
            if current is None or (not current["image_url"] and candidate["image_url"]):
                unique[name] = candidate
        gifts = list(unique.values())
        if not gifts:
            raise RuntimeError("当前直播间没有返回可用礼物")
        return gifts

    def _download_icons(self, gifts: List[Dict]) -> None:
        root = _cache_root()
        root.mkdir(parents=True, exist_ok=True)
        total = len(gifts)

        def download(item: Dict) -> str:
            if self.isInterruptionRequested() or not item["image_url"]:
                return ""
            destination = root / f"gift_{item['id']}{_safe_extension(item['image_url'])}"
            if destination.is_file() and destination.stat().st_size > 0:
                return str(destination)
            request = urllib.request.Request(
                item["image_url"],
                headers={"User-Agent": USER_AGENT, "Referer": "https://live.bilibili.com/"},
            )
            try:
                with urllib.request.urlopen(request, timeout=12.0) as response:
                    # 礼物小图正常只有几十 KB，限制异常响应，避免缓存无界增长。
                    content = response.read(5 * 1024 * 1024 + 1)
                if not content or len(content) > 5 * 1024 * 1024:
                    return ""
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_bytes(content)
                temporary.replace(destination)
                return str(destination)
            except (OSError, ValueError):
                return ""

        completed = 0
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="gift-icon") as pool:
            futures = {pool.submit(download, item): item for item in gifts}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    item["icon_path"] = future.result()
                except Exception:
                    item["icon_path"] = ""
                completed += 1
                if completed == total or completed % 4 == 0:
                    self.progress.emit(completed, total, f"正在下载礼物图片 {completed}/{total}")
                if self.isInterruptionRequested():
                    for pending in futures:
                        pending.cancel()
                    break

    @staticmethod
    def _save_metadata(gifts: List[Dict]) -> None:
        path = _metadata_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        compact = [
            {
                "id": item["id"],
                "name": item["name"],
                "price": item["price"],
                "icon_path": (
                    Path(str(item.get("icon_path", ""))).name
                    if item.get("icon_path")
                    else ""
                ),
            }
            for item in gifts
        ]
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "gifts": compact,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
