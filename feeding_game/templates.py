"""内置主题模板与素材落盘工具。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional


_BUILTIN_TEMPLATES = (
    {
        "id": "mouse_rice",
        "name": "老鼠吃大米",
        "description": "一捧大米落下来，喂饱抱着碗的小老鼠。",
        "food_files": ("rice.png",),
        "consumer_file": "mouse.png",
    },
    {
        "id": "leaves_bin",
        "name": "落叶进桶",
        "description": "绿叶、黄枫叶和红橡叶一起落进回收桶。",
        "food_files": ("leaf_green.png", "leaf_yellow.png", "leaf_red.png"),
        "consumer_file": "trash_bin.png",
    },
    {
        "id": "cat_fish",
        "name": "猫咪吃小鱼",
        "description": "把银蓝小鱼投喂给抱着饭碗的橘猫。",
        "food_files": ("fish.png",),
        "consumer_file": "cat.png",
    },
    {
        "id": "stars_jar",
        "name": "星星收藏瓶",
        "description": "收集从天而降的小星星，装满许愿玻璃瓶。",
        "food_files": ("star.png",),
        "consumer_file": "jar.png",
    },
)


def _resource_root() -> Path:
    """源码运行时读取项目目录，单文件 EXE 中读取 PyInstaller 解压目录。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def builtin_templates() -> List[Dict]:
    """返回带预览素材绝对路径的内置模板列表。"""
    result: List[Dict] = []
    assets_root = _resource_root() / "assets" / "templates"
    for template in _BUILTIN_TEMPLATES:
        source_dir = assets_root / template["id"]
        result.append(
            {
                "id": template["id"],
                "name": template["name"],
                "description": template["description"],
                "food_images": [
                    str(source_dir / name) for name in template["food_files"]
                ],
                "consumer_image": str(source_dir / template["consumer_file"]),
                "builtin": True,
            }
        )
    return result


def materialize_builtin_template(template_id: str, data_dir: Path) -> Optional[Dict]:
    """把内置资源复制到程序目录，避免单文件 EXE 重启后临时路径失效。"""
    template = next(
        (item for item in builtin_templates() if item["id"] == template_id), None
    )
    if template is None:
        return None

    destination_dir = Path(data_dir) / "template_assets" / template_id
    destination_dir.mkdir(parents=True, exist_ok=True)

    copied_foods: List[str] = []
    for source_text in template["food_images"]:
        source = Path(source_text)
        destination = destination_dir / source.name
        # 已存在的模板素材直接复用，避免每次应用都重复写盘。
        if not destination.is_file() and source.is_file():
            shutil.copy2(source, destination)
        if destination.is_file():
            copied_foods.append(str(destination.resolve()))

    source_consumer = Path(template["consumer_image"])
    destination_consumer = destination_dir / source_consumer.name
    if not destination_consumer.is_file() and source_consumer.is_file():
        shutil.copy2(source_consumer, destination_consumer)

    return {
        **template,
        "food_images": copied_foods,
        "consumer_image": (
            str(destination_consumer.resolve())
            if destination_consumer.is_file()
            else ""
        ),
    }
