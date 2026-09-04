"""静态图和 GIF 的统一加载工具，兼容 Windows 中文路径。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PyQt5.QtGui import QMovie, QPixmap
from PyQt5.QtWidgets import QLabel


def load_pixmap(path: str) -> QPixmap:
    """优先让 Qt 直接加载，失败时由 Python 读取数据以绕过路径编码问题。"""
    if not path or not Path(path).is_file():
        return QPixmap()
    pixmap = QPixmap(path)
    if not pixmap.isNull():
        return pixmap
    try:
        data = Path(path).read_bytes()
    except OSError:
        return QPixmap()
    pixmap.loadFromData(data)
    return pixmap


def create_movie(path: str, parent, bounds: QSize) -> Optional[QMovie]:
    """创建 GIF 动画；QBuffer 会挂在 movie 上保持整个播放期有效。"""
    if not path or not Path(path).is_file():
        return None
    movie = QMovie(path, parent=parent)
    if not movie.isValid():
        # 某些 Qt5/Windows 组合无法直接打开中文路径，改从内存读取。
        movie.deleteLater()
        try:
            data = Path(path).read_bytes()
        except OSError:
            return None
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        if not buffer.open(QIODevice.ReadOnly):
            return None
        movie = QMovie(buffer, b"", parent)
        buffer.setParent(movie)
        movie._source_buffer = buffer  # type: ignore[attr-defined]
    if not movie.isValid():
        movie.deleteLater()
        return None

    movie.setCacheMode(QMovie.CacheAll)
    movie.jumpToFrame(0)
    original = movie.currentPixmap().size()
    if original.isValid() and not original.isEmpty():
        movie.setScaledSize(original.scaled(bounds, Qt.KeepAspectRatio))
    else:
        movie.setScaledSize(bounds)
    return movie


def set_label_media(
    label: QLabel,
    path: str,
    bounds: QSize,
    fallback: Optional[QPixmap] = None,
) -> bool:
    """在 QLabel 上显示静态图片或循环 GIF，返回指定文件是否加载成功。"""
    old_movie = getattr(label, "_active_movie", None)
    if old_movie is not None:
        old_movie.stop()
        old_movie.deleteLater()
        label._active_movie = None  # type: ignore[attr-defined]
    label.clear()
    label.setAlignment(Qt.AlignCenter)

    if Path(path).suffix.lower() == ".gif":
        movie = create_movie(path, label, bounds)
        if movie is not None:
            label._active_movie = movie  # type: ignore[attr-defined]
            label.setMovie(movie)
            movie.start()
            return True

    pixmap = load_pixmap(path)
    loaded = not pixmap.isNull()
    if pixmap.isNull() and fallback is not None:
        pixmap = fallback
    if not pixmap.isNull():
        label.setPixmap(
            pixmap.scaled(bounds, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
    return loaded
