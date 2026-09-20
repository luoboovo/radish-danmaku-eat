"""启动游戏前的桌面区域圈选层。"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget


class RegionSelector(QWidget):
    """覆盖虚拟桌面，让主播拖出透明游戏层的实际活动范围。"""

    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()
    # 最小宽度仍可完整放下包含“关闭游戏”的工具条，同时保持选区灵活。
    MINIMUM_WIDTH = 880
    MINIMUM_HEIGHT = 500

    def __init__(self) -> None:
        super().__init__()
        self._anchor: Optional[QPoint] = None
        self._selection: Optional[QRect] = None
        self.setWindowTitle("小萝卜吃吃吃 · 圈选游戏区域")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.virtualGeometry())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self.cancelled.emit()
            self.close()
            return
        if event.button() == Qt.LeftButton:
            self._anchor = QPoint(event.pos())
            self._selection = QRect(self._anchor, self._anchor)
            self.update()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._anchor is not None and event.buttons() & Qt.LeftButton:
            self._selection = QRect(self._anchor, event.pos()).normalized()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self._anchor is None:
            event.ignore()
            return
        local_rect = self._bounded_selection(event.pos())
        global_rect = local_rect.translated(self.geometry().topLeft())
        self._anchor = None
        self._selection = local_rect
        self.region_selected.emit(global_rect)
        self.close()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def _bounded_selection(self, current: QPoint) -> QRect:
        raw = QRect(self._anchor, current).normalized()
        width = min(self.width(), max(self.MINIMUM_WIDTH, raw.width()))
        height = min(self.height(), max(self.MINIMUM_HEIGHT, raw.height()))
        x = raw.left() if current.x() >= self._anchor.x() else raw.right() - width + 1
        y = raw.top() if current.y() >= self._anchor.y() else raw.bottom() - height + 1
        x = max(0, min(self.width() - width, x))
        y = max(0, min(self.height() - height, y))
        return QRect(x, y, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(16, 18, 22, 155))

        if self._selection is None or self._selection.isNull():
            painter.setPen(QColor("white"))
            font = painter.font()
            font.setFamily("Microsoft YaHei UI")
            font.setPixelSize(25)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(24, 24, -24, -24),
                Qt.AlignCenter,
                "按住鼠标左键拖动，圈出游戏活动区域\n右键或 Esc 取消",
            )
            painter.end()
            return

        selection = self._selection.intersected(self.rect())
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(selection, Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setPen(QPen(QColor("#43D39E"), 4))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(selection.adjusted(2, 2, -2, -2), 10, 10)

        painter.setPen(QColor("white"))
        font = painter.font()
        font.setFamily("Microsoft YaHei UI")
        font.setPixelSize(17)
        font.setBold(True)
        painter.setFont(font)
        label = f"{selection.width()} × {selection.height()}  ·  松开鼠标确认"
        label_rect = QRect(selection.left(), max(8, selection.top() - 42), 330, 34)
        painter.fillRect(label_rect, QColor(20, 22, 26, 210))
        painter.drawText(label_rect.adjusted(10, 0, -8, 0), Qt.AlignVCenter, label)
        painter.end()
