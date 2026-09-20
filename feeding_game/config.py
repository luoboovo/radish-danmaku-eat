"""配置读取、校验与持久化。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_STAR_BLESSINGS = [
    "一切尽意,万事从欢",
    "顺遂无虞,皆得所愿",
    "浅予深深,长乐未央",
    "旦逢良辰,顺颂时宜",
]

LEGACY_STAR_BLESSINGS = [
    "愿你的愿望闪闪发光 ✨",
    "今天也会有好事发生！",
    "所有期待都在悄悄靠近你。",
    "愿你被温柔和好运围绕。",
    "下一颗星星会带来惊喜！",
]


DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 2,
    "room_id": "",
    "sessdata": "",
    "food_images": [],
    "consumer_image": "",
    "active_theme_id": "",
    "star_blessings": DEFAULT_STAR_BLESSINGS,
    "custom_templates": [],
    "initial_food_count": 10,
    "manual_step": 100,
    "food_size": 72,
    "consumer_size": 190,
    "sound_enabled": True,
    "sound_files": {
        "add": "",
        "remove": "",
        "eat": "",
        "gift": "",
    },
    "food_sound_files": {},
    "food_image_order": "random",
    "food_layout_mode": "piles",
    "danmaku_match_mode": "exact",
    "danmaku_case_sensitive": False,
    "danmaku_rules": [
        {"keyword": "投喂", "delta": 1},
        {"keyword": "吃", "delta": -1},
    ],
    "gift_food_rules": [
        {"gift_name": "辣条", "operation": "add", "value": 1.0},
    ],
    "gift_range_rules": [
        {"gift_name": "小花花", "seconds": 10},
    ],
    "gift_rule_templates": [],
    "gift_effect_overlay_enabled": True,
    "gift_effect_position_set": False,
    "gift_effect_x_ratio": 0.5,
    "gift_effect_y_ratio": 0.03,
    "range_hit_mode": "intersects",
    "range_radius": 50,
    "range_pickup_limit": 100,
    "user_cooldown_seconds": 1.0,
    "stats_visible": True,
    "stats_scale": 1.0,
    "stats_x_ratio": 0.03,
    "stats_y_ratio": 0.03,
}


def _int_value(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _float_value(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def normalize_config(raw: Any) -> Dict[str, Any]:
    """把旧配置或手工修改后的配置整理为程序可安全使用的格式。"""
    source = raw if isinstance(raw, dict) else {}
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(source)

    config["room_id"] = str(config.get("room_id", "")).strip()
    config["sessdata"] = str(config.get("sessdata", "")).strip()
    config["food_images"] = [
        str(item) for item in config.get("food_images", []) if str(item).strip()
    ]
    config["consumer_image"] = str(config.get("consumer_image", "")).strip()
    config["active_theme_id"] = str(config.get("active_theme_id", "")).strip()[:40]
    raw_blessings = config.get("star_blessings", [])
    if not isinstance(raw_blessings, list):
        raw_blessings = []
    normalized_blessings = [
        str(item).strip()[:80]
        for item in raw_blessings[:100]
        if str(item).strip()
    ]
    # 将早期版本自带的五句祝福迁移成新版四句；用户自行填写的内容原样保留。
    if not normalized_blessings or normalized_blessings == LEGACY_STAR_BLESSINGS:
        normalized_blessings = copy.deepcopy(DEFAULT_STAR_BLESSINGS)
    config["star_blessings"] = normalized_blessings
    raw_custom_templates = config.get("custom_templates", [])
    config["custom_templates"] = []
    if isinstance(raw_custom_templates, list):
        seen_template_names = set()
        for item in raw_custom_templates[:100]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()[:40]
            if not name or name in seen_template_names:
                continue
            raw_template_foods = item.get("food_images", [])
            if not isinstance(raw_template_foods, list):
                raw_template_foods = []
            food_images = [
                str(path).strip()
                for path in raw_template_foods
                if str(path).strip()
            ]
            consumer_image = str(item.get("consumer_image", "")).strip()
            config["custom_templates"].append(
                {
                    "name": name,
                    "food_images": food_images,
                    "consumer_image": consumer_image,
                    "theme_id": str(item.get("theme_id", "")).strip()[:40],
                }
            )
            seen_template_names.add(name)
    config["initial_food_count"] = _int_value(
        config.get("initial_food_count"), 10, 0, 100000
    )
    config["manual_step"] = _int_value(config.get("manual_step"), 100, 1, 10000)
    config["food_size"] = _int_value(config.get("food_size"), 72, 24, 256)
    config["consumer_size"] = _int_value(
        config.get("consumer_size"), 190, 60, 600
    )
    config["sound_enabled"] = bool(config.get("sound_enabled", True))
    raw_sound_files = config.get("sound_files", {})
    if not isinstance(raw_sound_files, dict):
        raw_sound_files = {}
    config["sound_files"] = {
        name: str(raw_sound_files.get(name, "")).strip()
        for name in ("add", "remove", "eat", "gift")
    }
    raw_food_sound_files = config.get("food_sound_files", {})
    if not isinstance(raw_food_sound_files, dict):
        raw_food_sound_files = {}
    config["food_sound_files"] = {
        str(food_path): str(sound_path).strip()
        for food_path, sound_path in raw_food_sound_files.items()
        if str(food_path).strip() and str(sound_path).strip()
    }
    # 短暂版本中的 OBS 绿幕配置已经取消，游戏窗口恢复纯透明。
    config.pop("capture_background_color", None)
    # 旧版本的可见数量上限已取消：食物总数是多少，就创建多少个贴图。
    config.pop("max_visible_foods", None)
    if config.get("food_image_order") not in {"random", "sequential"}:
        config["food_image_order"] = "random"
    # 旧版的 spread 会把食物直接散布到整个画面，不符合重力堆积语义。
    # 读取旧配置时统一迁移成从底部逐层向上生长的自然堆积模式。
    config["food_layout_mode"] = "piles"
    if config.get("danmaku_match_mode") not in {"exact", "contains"}:
        config["danmaku_match_mode"] = "exact"
    config["danmaku_case_sensitive"] = bool(
        config.get("danmaku_case_sensitive", False)
    )
    if config.get("range_hit_mode") not in {"intersects", "contains"}:
        config["range_hit_mode"] = "intersects"
    # 兼容旧版矩形宽高：第一次读取时取较长边的一半作为圆形半径。
    radius_value = source.get("range_radius")
    if radius_value is None:
        if "range_box_width" in source or "range_box_height" in source:
            legacy_width = _int_value(source.get("range_box_width"), 300, 50, 2000)
            legacy_height = _int_value(source.get("range_box_height"), 220, 50, 2000)
            radius_value = max(legacy_width, legacy_height) // 2
        else:
            radius_value = DEFAULT_CONFIG["range_radius"]
    config["range_radius"] = _int_value(radius_value, 50, 25, 1000)
    config["range_pickup_limit"] = _int_value(
        config.get("range_pickup_limit"), 100, 1, 10000
    )
    config.pop("range_box_width", None)
    config.pop("range_box_height", None)
    config["user_cooldown_seconds"] = _float_value(
        config.get("user_cooldown_seconds"), 1.0, 0.0, 3600.0
    )
    config["stats_visible"] = bool(config.get("stats_visible", True))
    config["stats_scale"] = _float_value(
        config.get("stats_scale"), 1.0, 0.5, 3.0
    )
    config["stats_x_ratio"] = _float_value(
        config.get("stats_x_ratio"), 0.03, 0.0, 1.0
    )
    config["stats_y_ratio"] = _float_value(
        config.get("stats_y_ratio"), 0.03, 0.0, 1.0
    )

    config["danmaku_rules"] = _normalize_rules(
        config.get("danmaku_rules"), "keyword", "delta", -10000, 10000
    )
    # v1 只有带正负号的 delta；首次读取时无损迁移成“增加/减少”操作。
    raw_gift_food_rules = source.get("gift_food_rules")
    if raw_gift_food_rules is None:
        legacy_rules = source.get("gift_delta_rules")
        if legacy_rules is None:
            raw_gift_food_rules = DEFAULT_CONFIG["gift_food_rules"]
        else:
            raw_gift_food_rules = []
            for rule in legacy_rules if isinstance(legacy_rules, list) else []:
                if not isinstance(rule, dict):
                    continue
                delta = _int_value(rule.get("delta"), 1, -10000, 10000)
                if delta:
                    raw_gift_food_rules.append(
                        {
                            "gift_name": rule.get("gift_name", ""),
                            "operation": "add" if delta > 0 else "subtract",
                            "value": float(abs(delta)),
                        }
                    )
    config["gift_food_rules"] = _normalize_gift_food_rules(raw_gift_food_rules)
    config.pop("gift_delta_rules", None)
    config["gift_range_rules"] = _normalize_rules(
        config.get("gift_range_rules"), "gift_name", "seconds", 1, 3600
    )
    config["gift_rule_templates"] = _normalize_gift_rule_templates(
        config.get("gift_rule_templates")
    )
    config["gift_effect_overlay_enabled"] = bool(
        config.get("gift_effect_overlay_enabled", True)
    )
    config["gift_effect_position_set"] = bool(
        config.get("gift_effect_position_set", False)
    )
    config["gift_effect_x_ratio"] = _float_value(
        config.get("gift_effect_x_ratio"), 0.5, 0.0, 1.0
    )
    config["gift_effect_y_ratio"] = _float_value(
        config.get("gift_effect_y_ratio"), 0.03, 0.0, 1.0
    )
    return config


def _normalize_gift_food_rules(rules: Any) -> list:
    """整理礼物食物运算，支持加减乘除、清空和刮大风。"""
    result = []
    if not isinstance(rules, list):
        return result
    aliases = {
        "add": "add",
        "subtract": "subtract",
        "multiply": "multiply",
        "divide": "divide",
        "clear": "clear",
        "wind": "wind",
        "+": "add",
        "-": "subtract",
        "*": "multiply",
        "/": "divide",
    }
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        gift_name = str(rule.get("gift_name", "")).strip()
        operation = aliases.get(str(rule.get("operation", "add")).strip().lower())
        if not gift_name or operation is None:
            continue
        value = _float_value(rule.get("value"), 1.0, 0.01, 10000.0)
        if operation in {"clear", "wind"}:
            value = 1.0
        elif operation in {"multiply", "divide"}:
            value = max(1.01, value)
        else:
            value = max(1.0, value)
        result.append(
            {
                "gift_name": gift_name,
                "operation": operation,
                "value": value,
                **(
                    {"gift_id": _int_value(rule.get("gift_id"), 0, 0, 999999999)}
                    if _int_value(rule.get("gift_id"), 0, 0, 999999999)
                    else {}
                ),
            }
        )
    return result


def _normalize_gift_rule_templates(templates: Any) -> list:
    """整理用户保存的整套礼物规则模板。"""
    result = []
    if not isinstance(templates, list):
        return result
    seen_names = set()
    for template in templates[:100]:
        if not isinstance(template, dict):
            continue
        name = str(template.get("name", "")).strip()[:40]
        if not name or name in seen_names:
            continue
        result.append(
            {
                "name": name,
                "gift_food_rules": _normalize_gift_food_rules(
                    template.get("gift_food_rules")
                ),
                "gift_range_rules": _normalize_rules(
                    template.get("gift_range_rules"),
                    "gift_name",
                    "seconds",
                    1,
                    3600,
                ),
            }
        )
        seen_names.add(name)
    return result


def _normalize_rules(
    rules: Any,
    name_key: str,
    value_key: str,
    minimum: int,
    maximum: int,
) -> list:
    result = []
    if not isinstance(rules, list):
        return result
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get(name_key, "")).strip()
        if not name:
            continue
        value = _int_value(rule.get(value_key), 1, minimum, maximum)
        if value_key == "delta" and value == 0:
            continue
        normalized = {name_key: name, value_key: value}
        if name_key == "gift_name":
            gift_id = _int_value(rule.get("gift_id"), 0, 0, 999999999)
            if gift_id:
                normalized["gift_id"] = gift_id
        result.append(normalized)
    return result


def load_config(path: Path) -> Dict[str, Any]:
    """读取 JSON；文件不存在时返回默认配置。"""
    if not path.exists():
        return normalize_config({})
    try:
        with path.open("r", encoding="utf-8") as file:
            return normalize_config(json.load(file))
    except (OSError, json.JSONDecodeError):
        # 损坏的配置不会阻止界面启动，保存时会覆盖为合法 JSON。
        return normalize_config({})


def save_config(path: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    """规范化并以 UTF-8 JSON 保存，返回实际保存的配置。"""
    normalized = normalize_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return normalized
