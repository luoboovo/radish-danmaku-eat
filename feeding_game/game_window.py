"""透明置顶游戏界面与拖拽/范围拾取逻辑。"""

from __future__ import annotations

import ctypes
import html
import heapq
import math
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QMouseEvent,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QWidget,
)

from .gift_catalog import cached_gift_icon
from .media import create_movie, load_pixmap as load_media_pixmap, set_label_media
from .sound import GameSoundPlayer


WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTTRANSPARENT = -1
MAX_FOOD_COUNT = 100000


class FoodItem(QLabel):
    """单个食物贴图；具体拖动规则交给 GameWindow 统一处理。"""

    def __init__(
        self,
        game: "GameWindow",
        path: str,
        fallback: QPixmap,
        size: int,
        rotation_angle: int,
    ) -> None:
        super().__init__(game)
        self.game = game
        self.source_path = str(path) if path else "__default__"
        self.rotation_angle = int(rotation_angle)
        self._shared_movie: Optional[QMovie] = None
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        # 静态图按“尺寸+角度”缓存；GIF 同尺寸只解码一次，每帧的旋转结果
        # 也按角度共享，避免大量食物重复做图像变换。
        movie = game._shared_food_movie(path, size)
        if movie is not None:
            self._shared_movie = movie
            game._register_movie_food(movie, self)
        else:
            self.setPixmap(
                game._rotated_food_pixmap(
                    path,
                    size,
                    fallback,
                    self.rotation_angle,
                )
            )
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 物理位置使用浮点数，QWidget 实际显示位置在每帧取整。
        self.physics_x = 0.0
        self.physics_y = 0.0
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.collision_radius = size * 0.42
        self.is_sleeping = False
        self.free_falling = False
        # 自由拖放或竖列补位时使用食物自己的垂直落点，不能写进全局槽位缓存，
        # 否则同槽位后续食物会继承错误坐标并留下空洞。
        self.gravity_target: Optional[QPoint] = None
        self.pile_slot = -1

    def release_media(self) -> None:
        """食物移除时解除共享 GIF 更新，避免隐藏对象继续接收每一帧。"""
        if self._shared_movie is not None:
            self.game._unregister_movie_food(self._shared_movie, self)
            self._shared_movie = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self.game.begin_food_drag(self, event.globalPos())
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.game.move_food_drag(event.globalPos())
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setCursor(Qt.OpenHandCursor)
        if event.button() == Qt.LeftButton:
            self.game.finish_food_drag(event.globalPos())
            event.accept()
            return
        event.ignore()


class ConsumerItem(QLabel):
    """可拖动的食用者贴图。"""

    def __init__(
        self,
        game: "GameWindow",
        path: str,
        fallback: QPixmap,
        size: int,
    ) -> None:
        super().__init__(game)
        self.game = game
        self.setFixedSize(size, size)
        set_label_media(self, path, QSize(size, size), fallback)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("按住鼠标左键可移动食用者")
        self.setAttribute(Qt.WA_TranslucentBackground)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.game.begin_consumer_drag(event.globalPos())
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.game.move_consumer_drag(event.globalPos())
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.game.finish_consumer_drag()
            event.accept()
            return
        event.ignore()


class LogEntryCard(QFrame):
    """互动日志中的单条可爱卡片。"""

    THEMES = {
        "feed": ("🥕", "#ef7f39", "#fff5ed"),
        "decrease": ("➖", "#7c72df", "#f4f2ff"),
        "gift": ("🎁", "#ef6f9d", "#fff2f7"),
        "eat": ("🍽", "#7c72df", "#f4f2ff"),
        "range": ("✨", "#1eaa83", "#edfbf6"),
        "system": ("●", "#5794df", "#f0f6fd"),
        "manual": ("☝", "#7d8795", "#f4f5f7"),
    }

    def __init__(self, event_type: str, title: str, detail: str, time_text: str) -> None:
        super().__init__()
        icon, accent, background = self.THEMES.get(
            event_type, self.THEMES["system"]
        )
        self.setObjectName("logCard")
        self.setStyleSheet(
            "QFrame#logCard { background: #ffffff; border: 1px solid #e9eaec;"
            "border-radius: 12px; }"
        )

        icon_label = QLabel(icon)
        icon_label.setFixedSize(34, 34)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(
            f"background: {background}; color: {accent}; border-radius: 17px; font-size: 18px;"
        )
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            "color: #202124; font-family: 'Microsoft YaHei UI'; font-size: 16px; font-weight: 700;"
        )
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(
            "color: #70757a; font-family: 'Microsoft YaHei UI'; font-size: 14px;"
        )
        detail_label.setVisible(bool(detail))
        time_label = QLabel(time_text)
        time_label.setAlignment(Qt.AlignTop | Qt.AlignRight)
        time_label.setStyleSheet("color: #a2a6ac; font-size: 12px;")

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(title_label)
        text_layout.addWidget(detail_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(8)
        layout.addWidget(icon_label, 0, Qt.AlignTop)
        layout.addLayout(text_layout, 1)
        layout.addWidget(time_label, 0, Qt.AlignTop)
        self.setToolTip(f"{title}\n{detail}".strip())


class LogDragHandle(QFrame):
    """日志面板的拖动标题栏。"""

    def __init__(self, panel: QFrame) -> None:
        super().__init__(panel)
        self.panel = panel
        self._drag_offset: Optional[QPoint] = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # 使用全局坐标计算偏移，主屏在多显示器布局中不是 (0, 0) 时也不会跳位。
            self._drag_offset = event.globalPos() - self.panel.mapToGlobal(QPoint(0, 0))
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is None or not (event.buttons() & Qt.LeftButton):
            return
        desired = event.globalPos() - self._drag_offset
        parent = self.panel.parentWidget()
        local = parent.mapFromGlobal(desired)
        x = max(0, min(parent.width() - self.panel.width(), local.x()))
        y = max(0, min(parent.height() - self.panel.height(), local.y()))
        self.panel.move(x, y)
        self.panel._was_dragged = True  # type: ignore[attr-defined]
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        self.setCursor(Qt.OpenHandCursor)
        event.accept()


class MovableToolbar(QFrame):
    """可在游戏层内拖动的顶部工具条；按钮区域仍保持正常点击。"""

    def __init__(self, game: "GameWindow") -> None:
        super().__init__(game)
        self.game = game
        self._drag_offset: Optional[QPoint] = None
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("按住工具条空白处或左侧拖动点可移动")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.mapToGlobal(QPoint(0, 0))
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is None or not (event.buttons() & Qt.LeftButton):
            event.ignore()
            return
        parent = self.parentWidget()
        desired = parent.mapFromGlobal(event.globalPos() - self._drag_offset)
        x = max(0, min(parent.width() - self.width(), desired.x()))
        y = max(0, min(parent.height() - self.height(), desired.y()))
        self.move(x, y)
        self.game._toolbar_was_dragged = True
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        self.setCursor(Qt.OpenHandCursor)
        event.accept()


class StatsOverlay(QWidget):
    """透明纯文字统计框：拖动文字移动，滚轮调整大小。"""

    def __init__(self, game: "GameWindow") -> None:
        super().__init__(game)
        self.game = game
        self.scale_factor = float(game.config.get("stats_scale", 1.0))
        self._drag_offset: Optional[QPoint] = None
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("拖动文字可移动；鼠标滚轮可放大或缩小")

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setTextFormat(Qt.RichText)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        shadow = QGraphicsDropShadowEffect(self.label)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 175))
        self.label.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.label)
        self.update_counts(0, 0)

    def update_counts(self, eaten: int, remaining: int) -> None:
        font_px = max(
            20,
            int(round(34 * self.game._display_scale * self.scale_factor)),
        )
        label_px = max(16, int(round(font_px * 0.72)))
        self.label.setFont(QFont("Microsoft YaHei UI"))
        self.label.setStyleSheet("background: transparent; border: 0;")
        self.label.setText(
            f"<span style='font-size:{label_px}px; font-weight:700; color:#ffffff'>已吃</span> "
            f"<span style='font-size:{font_px}px; font-weight:900; color:#ff6476'>{int(eaten)}</span>"
            f"<span style='font-size:{label_px}px; color:transparent'>　</span>"
            f"<span style='font-size:{label_px}px; font-weight:700; color:#ffffff'>剩余</span> "
            f"<span style='font-size:{font_px}px; font-weight:900; color:#ff861f'>{int(remaining)}</span>"
        )
        self.adjustSize()
        self._clamp_inside_parent()

    def restore_position_from_config(self) -> None:
        available_x = max(0, self.game.width() - self.width())
        available_y = max(0, self.game.height() - self.height())
        self.move(
            round(available_x * float(self.game.config.get("stats_x_ratio", 0.03))),
            round(available_y * float(self.game.config.get("stats_y_ratio", 0.03))),
        )

    def set_scale_factor(self, value: float, notify: bool = True) -> None:
        self.scale_factor = max(0.5, min(3.0, float(value)))
        self.update_counts(self.game.eaten_count, self.game.food_count)
        if notify:
            self.game._stats_preferences_updated()

    def _clamp_inside_parent(self) -> None:
        self.move(
            max(0, min(self.game.width() - self.width(), self.x())),
            max(0, min(self.game.height() - self.height(), self.y())),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.mapToGlobal(QPoint(0, 0))
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            desired = self.game.mapFromGlobal(event.globalPos() - self._drag_offset)
            self.move(
                max(0, min(self.game.width() - self.width(), desired.x())),
                max(0, min(self.game.height() - self.height(), desired.y())),
            )
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.game._stats_preferences_updated()
            event.accept()
            return
        event.ignore()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.angleDelta().y():
            step = 0.1 if event.angleDelta().y() > 0 else -0.1
            self.set_scale_factor(self.scale_factor + step)
            event.accept()
            return
        event.ignore()


class EatingFeedbackCard(QLabel):
    """投喂后只弹出一个爱心，不显示文字或外框。"""

    def __init__(self, parent=None, scale: float = 1.0) -> None:
        super().__init__("💖", parent)
        self._scale = max(0.72, min(1.80, float(scale)))
        card_size = max(58, round(82 * self._scale))
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(card_size, card_size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            "background: transparent; border: 0;"
            f"font-family: 'Segoe UI Emoji'; font-size: {max(39, round(54 * self._scale))}px;"
        )
        self.pop_animation = QPropertyAnimation(self, b"geometry", self)
        self.pop_animation.setDuration(260)
        self.pop_animation.setEasingCurve(QEasingCurve.OutBack)
        self.hide()

    def pop(self, eaten: int, target_geometry: QRect) -> None:
        final_x = target_geometry.center().x() - self.width() // 2
        final_x = max(8, min(self.parentWidget().width() - self.width() - 8, final_x))
        final_y = max(8, target_geometry.top() - self.height() + 4)
        final_rect = QRect(final_x, final_y, self.width(), self.height())
        start_size = max(28, round(38 * self._scale))
        start_rect = QRect(
            final_x + round(22 * self._scale),
            final_y + round(28 * self._scale),
            start_size,
            start_size,
        )
        self.pop_animation.stop()
        self.setGeometry(start_rect)
        self.show()
        self.raise_()
        self.pop_animation.setStartValue(start_rect)
        self.pop_animation.setEndValue(final_rect)
        self.pop_animation.start()


class BlessingBubble(QWidget):
    """许愿瓶祝福气泡：手绘黑边、粉色内芯和向下的小尾巴。"""

    def __init__(self, game: "GameWindow") -> None:
        super().__init__(game)
        self.game = game
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"background:transparent; color:#272126; border:0;"
            f"font-family:'Microsoft YaHei UI';"
            f"font-size:{game._scaled_px(19, 15)}px; font-weight:800;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            game._scaled_px(30, 20),
            game._scaled_px(20, 14),
            game._scaled_px(30, 20),
            game._scaled_px(38, 28),
        )
        layout.addWidget(self.label)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, message: str) -> None:
        self.label.setMaximumWidth(self.game._scaled_px(420, 260))
        self.label.setText(str(message))
        self.label.adjustSize()
        self.adjustSize()
        self.setMinimumWidth(self.game._scaled_px(230, 170))
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self.hide_timer.start(4200)

    def reposition(self) -> None:
        consumer = self.game.consumer.geometry()
        x = consumer.center().x() - self.width() // 2
        y = consumer.top() - self.height() + self.game._scaled_px(18, 10)
        self.move(
            max(0, min(self.game.width() - self.width(), x)),
            max(0, min(self.game.height() - self.height(), y)),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = self.rect().adjusted(5, 5, -5, -self.game._scaled_px(26, 18))
        radius = self.game._scaled_px(30, 20)
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(body), radius, radius)
        tail_center = body.center().x()
        outer.moveTo(tail_center - 15, body.bottom() - 2)
        outer.cubicTo(
            tail_center - 4,
            body.bottom() + 9,
            tail_center + 5,
            body.bottom() + 20,
            tail_center + 18,
            body.bottom() + 23,
        )
        outer.cubicTo(
            tail_center + 11,
            body.bottom() + 11,
            tail_center + 12,
            body.bottom() + 4,
            tail_center + 12,
            body.bottom() - 2,
        )
        painter.setPen(QPen(QColor(22, 20, 22), self.game._scaled_px(5, 3)))
        painter.setBrush(QColor(252, 251, 251, 248))
        painter.drawPath(outer)
        inner = body.adjusted(
            self.game._scaled_px(13, 9),
            self.game._scaled_px(10, 7),
            -self.game._scaled_px(13, 9),
            -self.game._scaled_px(10, 7),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(246, 181, 216, 245))
        painter.drawRoundedRect(inner, radius, radius)
        painter.end()


class GiftEffectRow(QFrame):
    """礼物作用浮窗中的一行，图标与礼物 ID/名称始终成对更新。"""

    def __init__(self, game: "GameWindow", entry: Dict) -> None:
        super().__init__()
        self.gift_id = int(entry.get("gift_id", 0) or 0)
        self.gift_name = str(entry.get("gift_name", "")).strip()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        icon_size = game._scaled_px(48, 36)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.icon_label.setStyleSheet(
            "background:transparent; border:0;"
            "font-family:'Segoe UI Emoji'; font-size:25px;"
        )
        icon_path = cached_gift_icon(self.gift_name, self.gift_id)
        if not set_label_media(self.icon_label, icon_path, QSize(icon_size, icon_size)):
            self.icon_label.setText("🎁")

        self.gift_name_label = QLabel(self.gift_name)
        self.gift_name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.gift_name_label.setStyleSheet(
            f"color:#ffffff; font-family:'Microsoft YaHei UI';"
            f"font-size:{game._scaled_px(18, 15)}px; font-weight:800;"
        )
        self.effect_label = QLabel()
        self.effect_label.setTextFormat(Qt.RichText)
        self.effect_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.effect_label.setStyleSheet(
            f"background:transparent; font-family:'Microsoft YaHei UI';"
            f"font-size:{game._scaled_px(18, 15)}px; font-weight:800;"
        )
        self.effect_label.setText(self._effect_html(str(entry.get("effect_text", ""))))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(game._scaled_px(10, 7))
        layout.addWidget(self.icon_label)
        layout.addWidget(self.gift_name_label)
        layout.addSpacing(game._scaled_px(6, 4))
        layout.addWidget(self.effect_label)
        layout.addStretch(1)

    def show_live_effect(self, gift_num: int, effect_text: str) -> None:
        quantity = f" ×{int(gift_num)}" if int(gift_num) > 1 else ""
        self.gift_name_label.setText(f"{self.gift_name}{quantity}")
        self.effect_label.setText(self._effect_html(str(effect_text)))

    @staticmethod
    def _effect_html(effect_text: str) -> str:
        """不同规则使用固定颜色，同一行有多个作用时分别着色。"""
        rendered = []
        for part in str(effect_text).split(" · "):
            clean = part.strip()
            if clean.startswith(("投喂", "增加")):
                color = "#ff626b"
            elif clean.startswith("减少"):
                color = "#58d68d"
            elif clean.startswith("范围拾取"):
                color = "#ffd54f"
            elif clean.startswith("清空"):
                color = "#c084fc"
            elif clean.startswith("刮大风"):
                color = "#67d5ff"
            else:
                color = "#ffb24b"
            rendered.append(
                f"<span style='color:{color}; font-weight:800'>{html.escape(clean)}</span>"
            )
        separator = " <span style='color:#b8b8b8'>·</span> "
        return separator.join(rendered)


class GiftEffectOverlay(QFrame):
    """按配置逐条常驻展示礼物作用，并支持鼠标拖放位置。"""

    def __init__(self, game: "GameWindow") -> None:
        super().__init__(game)
        self.game = game
        self.rows: List[GiftEffectRow] = []
        self._drag_offset: Optional[QPoint] = None
        self._was_dragged = bool(game.config.get("gift_effect_position_set", False))
        self._position_restored = False
        self.setObjectName("giftEffectOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("按住鼠标左键拖动，松开后放置")
        self.setStyleSheet(
            "QFrame#giftEffectOverlay {"
            " background: rgba(28, 29, 33, 226); border: 1px solid rgba(255,255,255,55);"
            " border-radius: 18px; }"
        )
        # 不给整个浮窗套实时阴影。透明窗口中移动带阴影的复杂子控件开销很大，
        # 也可能在部分显卡上短暂丢失纹理，表现为拖动卡顿或浮窗消失。
        self.rows_layout = QVBoxLayout(self)
        self.rows_layout.setContentsMargins(
            game._scaled_px(13, 10),
            game._scaled_px(10, 8),
            game._scaled_px(18, 13),
            game._scaled_px(10, 8),
        )
        self.rows_layout.setSpacing(game._scaled_px(6, 4))
        self.hide()

    def set_rules(self, entries: List[Dict]) -> None:
        self.setUpdatesEnabled(False)
        for row in self.rows:
            self.rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows.clear()
        for entry in entries:
            row = GiftEffectRow(self.game, entry)
            self.rows.append(row)
            self.rows_layout.addWidget(row)
        if not self.rows:
            self.setUpdatesEnabled(True)
            self.hide()
            return
        self.setMaximumWidth(max(140, self.game.width() - 24))
        self.adjustSize()
        self.reposition()
        self.setUpdatesEnabled(True)
        self.show()
        self.raise_()

    def show_live_effect(self, gift_name: str, gift_num: int, effect_text: str) -> None:
        target = str(gift_name).strip()
        for row in self.rows:
            if row.gift_name == target:
                row.show_live_effect(gift_num, effect_text)
                self.adjustSize()
                self.reposition()
                self.show()
                self.raise_()
                return

    def reposition(self) -> None:
        if self._was_dragged and not self._position_restored:
            available_x = max(0, self.game.width() - self.width())
            available_y = max(0, self.game.height() - self.height())
            x = round(
                available_x
                * float(self.game.config.get("gift_effect_x_ratio", 0.5))
            )
            y = round(
                available_y
                * float(self.game.config.get("gift_effect_y_ratio", 0.03))
            )
            self._position_restored = True
        elif self._was_dragged:
            x = max(0, min(self.game.width() - self.width(), self.x()))
            y = max(0, min(self.game.height() - self.height(), self.y()))
        else:
            x = max(8, (self.game.width() - self.width()) // 2)
            y = max(8, self.game._scaled_px(24, 12))
        self.move(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.mapToGlobal(QPoint(0, 0))
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            desired = self.game.mapFromGlobal(event.globalPos() - self._drag_offset)
            self.move(
                max(0, min(self.game.width() - self.width(), desired.x())),
                max(0, min(self.game.height() - self.height(), desired.y())),
            )
            self._was_dragged = True
            self._position_restored = True
            self.raise_()
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self.setCursor(Qt.SizeAllCursor)
            self.game._gift_effect_preferences_updated()
            event.accept()
            return
        event.ignore()


class WindEffectOverlay(QWidget):
    """透明刮风动画：风线与全部食物一起被卷起，结束后重新落回食物堆。"""

    def __init__(self, game: "GameWindow") -> None:
        super().__init__(game)
        self.game = game
        self._particles: List[Dict[str, float]] = []
        self._direction = 1
        self._started_at = 0.0
        self._last_tick = 0.0
        self._duration = 1.8
        self._food_states: Dict[FoodItem, Dict[str, float]] = {}
        self._pending_food_count: Optional[int] = None
        self._pending_source = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._tick)

    def start_wind(
        self,
        quantity: int = 1,
        final_food_count: Optional[int] = None,
        source: str = "",
    ) -> None:
        self.setGeometry(self.game.rect())
        self._direction = random.choice((-1, 1))
        self._duration = min(5.0, 2.6 + max(1, int(quantity)) * 0.28)
        now = time.monotonic()
        self._started_at = now
        self._last_tick = now
        width = max(1, self.width())
        height = max(1, self.height())
        scale = max(0.72, float(self.game._display_scale))
        self._particles = []
        for _ in range(max(18, min(42, width // 52))):
            length = random.uniform(70.0, 230.0) * scale
            self._particles.append(
                {
                    "x": random.uniform(-length, width + length),
                    "y": random.uniform(8.0, max(9.0, height - 8.0)),
                    "length": length,
                    "speed": random.uniform(390.0, 820.0) * scale,
                    "curve": random.uniform(-18.0, 18.0) * scale,
                    "width": random.uniform(1.4, 4.2) * scale,
                    "alpha": random.uniform(0.45, 1.0),
                }
            )
        self.game._cancel_drag()
        if hasattr(self.game, "physics_timer"):
            self.game.physics_timer.stop()
        self._food_states.clear()
        self._capture_foods()
        if final_food_count is not None:
            self._pending_food_count = max(
                0, min(MAX_FOOD_COUNT, int(final_food_count))
            )
            self._pending_source = str(source)
        food_count = len(self.game.food_items)
        self._timer.setInterval(16 if food_count <= 300 else 25 if food_count <= 1000 else 33)
        self.show()
        self.raise_()
        self._timer.start()
        self.update()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    @property
    def pending_food_count(self) -> Optional[int]:
        return self._pending_food_count

    def adjust_pending_food_count(self, delta: int) -> None:
        """刮风期间收到其他投喂时，同步修正动画结束后的最终数量。"""
        if self._pending_food_count is None:
            return
        self._pending_food_count = max(
            0,
            min(MAX_FOOD_COUNT, self._pending_food_count + int(delta)),
        )

    def _capture_foods(self) -> None:
        """把本次风暴中途新增的食物也立即加入，不留下静止食物。"""
        current_items = set(self.game.food_items)
        for item in list(self._food_states):
            if item not in current_items:
                self._food_states.pop(item, None)
        scale = max(0.72, float(self.game._display_scale))
        for item in self.game.food_items:
            if item in self._food_states:
                continue
            item.physics_x = float(item.x())
            item.physics_y = float(item.y())
            item.velocity_x = 0.0
            item.velocity_y = 0.0
            item.gravity_target = None
            item.free_falling = False
            item.is_sleeping = False
            self._food_states[item] = {
                "x": float(item.x()),
                "y": float(item.y()),
                "vx": self._direction * random.uniform(330.0, 760.0) * scale,
                "vy": -random.uniform(430.0, 860.0) * scale,
                "phase": random.uniform(0.0, math.tau),
                "frequency": random.uniform(2.2, 5.5),
            }
            item.raise_()

    def stop_and_settle(self) -> None:
        """提前停止风暴时，也让现存食物自然落回各自堆积槽位。"""
        self._timer.stop()
        self.hide()
        self._settle_foods()

    def _settle_foods(self) -> None:
        pending_count = self._pending_food_count
        pending_source = self._pending_source
        self._pending_food_count = None
        self._pending_source = ""
        if pending_count is not None and pending_count != self.game.food_count:
            self.game.change_food_count(
                pending_count - self.game.food_count,
                pending_source,
            )
        for item in self.game.food_items:
            item.physics_x = float(item.x())
            item.physics_y = float(item.y())
            item.velocity_x = 0.0
            item.velocity_y = random.uniform(35.0, 100.0)
            item.gravity_target = None
            item.free_falling = False
            item.is_sleeping = False
        self._food_states.clear()
        if self.game.food_items:
            self.game._wake_physics()
        self.game.consumer.raise_()
        self.game._raise_gift_effect()
        if self.game.stats_overlay.isVisible():
            self.game.stats_overlay.raise_()

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = now - self._started_at
        if elapsed >= self._duration:
            self._timer.stop()
            self.hide()
            self._settle_foods()
            return
        dt = min(0.08, max(0.0, now - self._last_tick))
        self._last_tick = now
        width = max(1, self.width())
        height = max(1, self.height())
        progress = max(0.0, min(1.0, elapsed / self._duration))
        if hasattr(self.game, "physics_timer"):
            self.game.physics_timer.stop()
        self._capture_foods()
        for particle in self._particles:
            particle["x"] += self._direction * particle["speed"] * dt
            length = particle["length"]
            if self._direction > 0 and particle["x"] - length > width:
                particle["x"] = -length
            elif self._direction < 0 and particle["x"] + length < 0:
                particle["x"] = width + length

        # 前 68% 像阵风一样把全部食物卷起并在画面中循环；最后 32%
        # 平滑收束到各自落点上方，随后交还给重力系统自然下落。
        for item, state in list(self._food_states.items()):
            if item not in self.game.food_items:
                continue
            size = item.width()
            state["vy"] += 250.0 * dt
            state["x"] += state["vx"] * dt
            state["y"] += (
                state["vy"]
                + math.sin(elapsed * state["frequency"] + state["phase"]) * 145.0
            ) * dt
            if state["x"] > width - size * 0.25:
                state["x"] = -size * 0.65
            elif state["x"] < -size * 0.75:
                state["x"] = width - size * 0.35
            if state["y"] < -size * 0.45:
                state["y"] = -size * 0.45
                state["vy"] = random.uniform(55.0, 170.0)
            elif state["y"] > height - size:
                state["y"] = float(height - size)
                state["vy"] = -random.uniform(260.0, 620.0)

            if progress > 0.68:
                settle_progress = (progress - 0.68) / 0.32
                easing = 1.0 - (1.0 - settle_progress) ** 2
                target = self.game._pile_target(item.pile_slot, size)
                landing_y = max(-size * 0.35, target.y() - max(24, round(size * 0.72)))
                blend = min(1.0, max(0.08, easing * 0.30))
                state["x"] += (target.x() - state["x"]) * blend
                state["y"] += (landing_y - state["y"]) * blend

            item.physics_x = state["x"]
            item.physics_y = state["y"]
            item.move(round(state["x"]), round(state["y"]))
        self.update()
        self.raise_()
        self.game._raise_gift_effect()
        if self.game.stats_overlay.isVisible():
            self.game.stats_overlay.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._particles or self._duration <= 0:
            return
        progress = max(0.0, min(1.0, (time.monotonic() - self._started_at) / self._duration))
        fade = math.sin(math.pi * progress)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for index, particle in enumerate(self._particles):
            x = particle["x"]
            y = particle["y"]
            length = particle["length"] * self._direction
            curve = particle["curve"]
            path = QPainterPath(QPointF(x, y))
            path.cubicTo(
                QPointF(x - length * 0.35, y + curve),
                QPointF(x - length * 0.72, y - curve),
                QPointF(x - length, y),
            )
            alpha = int(205 * fade * particle["alpha"])
            color = QColor(205, 244, 255, max(0, min(255, alpha)))
            painter.setPen(QPen(color, particle["width"], Qt.SolidLine, Qt.RoundCap))
            painter.drawPath(path)
            # 每几条风线补一个短小旋涡，让动画比平移直线更像阵风。
            if index % 6 == 0:
                swirl = QPainterPath(QPointF(x - length * 0.42, y))
                swirl.cubicTo(
                    QPointF(x - length * 0.50, y - 16),
                    QPointF(x - length * 0.62, y + 16),
                    QPointF(x - length * 0.70, y),
                )
                painter.drawPath(swirl)
        painter.end()


class GameWindow(QWidget):
    """限制在主播圈选区域内的透明游戏层。"""

    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    food_count_changed = pyqtSignal(int, int)
    range_state_changed = pyqtSignal(bool, int)
    stats_preferences_changed = pyqtSignal(dict)

    def __init__(self, config: dict, game_geometry: Optional[QRect] = None) -> None:
        super().__init__()
        self.config = config
        self._requested_geometry = QRect(game_geometry) if game_geometry else QRect()
        self.food_count = int(config["initial_food_count"])
        # “已吃”统计本局所有实际减少的食物；新开一局时从 0 开始。
        self.eaten_count = 0
        self.food_items: List[FoodItem] = []
        self._image_index = 0
        self._food_pixmap_cache: Dict[tuple[str, int], QPixmap] = {}
        self._rotated_food_pixmap_cache: Dict[tuple[str, int, int], QPixmap] = {}
        self._food_movie_cache: Dict[tuple[str, int], QMovie] = {}
        self._food_movie_items: Dict[QMovie, List[FoodItem]] = {}
        self._pile_target_cache: Dict[tuple[int, int, int, int], QPoint] = {}
        self._free_pile_slots: List[int] = []
        self._next_pile_slot = 0
        self._toolbar_was_dragged = False
        self._display_scale = 1.0
        self._toolbar_margin = 16

        self._manual_range = False
        self._timed_range_until = 0.0
        self._last_range_report: Optional[tuple[bool, int]] = None
        self._drag_kind: Optional[str] = None
        self._drag_anchor = QPoint()
        self._drag_items: List[FoodItem] = []
        self._drag_start_positions: Dict[FoodItem, QPoint] = {}
        self._marquee_all_positions: Dict[FoodItem, QPoint] = {}
        self._selection_rect: Optional[QRect] = None
        self._selection_cursor: Optional[QPoint] = None
        self._fixed_box_origin: Optional[QRect] = None
        self._consumer_drag_start = QPoint()
        self._consumer_was_moved = False
        self._physics_last_time = time.monotonic()
        self._physics_awake_since = time.monotonic()
        self._physics_stable_frames = 0

        self._configure_window()
        self.sound_player = GameSoundPlayer(
            bool(self.config.get("sound_enabled", True)),
            self,
            self.config.get("sound_files", {}),
        )
        # 内置素材只绘制一次，后续所有食物共享缓存结果。
        self._food_fallback_pixmap = self._load_pixmap("", "food")
        self._consumer_fallback_pixmap = self._load_pixmap("", "consumer")
        self._build_toolbar()
        self._build_log_panel()
        # 控制与日志已经迁到独立控制台，透明游戏层不再显示旧工具条和日志面板。
        self.toolbar.hide()
        self.log_panel.hide()
        self._build_consumer()
        self._build_overlays()
        self._build_timers()
        self._sync_food_widgets()
        self._update_count_display()

    def _configure_window(self) -> None:
        # 无边框透明覆盖层，但几何范围严格限制在主播圈选区域内。
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setWindowOpacity(1.0)
        screen = QApplication.primaryScreen()
        if self._requested_geometry.isValid():
            self.setGeometry(self._requested_geometry)
        elif screen is not None:
            self.setGeometry(screen.geometry())
        self._update_display_scale()
        self.setWindowTitle("小萝卜吃吃吃 [透明游戏区域]")

    def _update_display_scale(self) -> None:
        """按圈选区域比例缩放游戏元素；Qt 自身再负责显示器 DPI 换算。"""
        width_scale = max(1, self.width()) / 1920.0
        height_scale = max(1, self.height()) / 1080.0
        self._display_scale = max(0.72, min(1.80, min(width_scale, height_scale)))
        self._toolbar_margin = self._scaled_px(16, 10)

    def _scaled_px(self, value: float, minimum: int = 1) -> int:
        return max(minimum, int(round(float(value) * self._display_scale)))

    def _base_food_size(self) -> int:
        return self._scaled_px(int(self.config.get("food_size", 72)), 20)

    def _build_toolbar(self) -> None:
        self.toolbar = MovableToolbar(self)
        self.toolbar.setObjectName("toolbar")
        layout = QHBoxLayout(self.toolbar)
        layout.setContentsMargins(
            self._scaled_px(12, 8),
            self._scaled_px(8, 6),
            self._scaled_px(12, 8),
            self._scaled_px(8, 6),
        )
        layout.setSpacing(self._scaled_px(8, 5))

        drag_hint = QLabel("⠿")
        drag_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        drag_hint.setStyleSheet(
            f"color: #b0b2b5; font-size: {self._scaled_px(19, 14)}px;"
        )
        self.count_label = QLabel()
        self.count_label.setObjectName("count")
        self.count_label.setTextFormat(Qt.RichText)
        self.count_label.setMinimumWidth(self._scaled_px(166, 122))
        self.minus_button = QPushButton(f"−{self.config['manual_step']}")
        self.plus_button = QPushButton(f"＋{self.config['manual_step']}")
        self.range_button = QPushButton("范围拾取：关")
        self.range_button.setCheckable(True)
        self.range_button.setMinimumWidth(self._scaled_px(112, 86))
        self.timer_label = QLabel("")
        self.timer_label.setObjectName("timer")
        self.timer_label.setMinimumWidth(self._scaled_px(72, 48))
        self.connection_label = QLabel("直播：准备连接")
        self.connection_label.setObjectName("connection")
        self.connection_label.setMinimumWidth(self._scaled_px(142, 104))
        self.log_button = QPushButton("互动记录 0")
        self.log_button.setMinimumWidth(self._scaled_px(108, 82))
        self.close_button = QPushButton("关闭游戏")
        self.close_button.setObjectName("closeGameButton")
        self.close_button.setToolTip("关闭透明游戏区域，设置窗口会继续保留")
        self.close_button.setMinimumWidth(self._scaled_px(88, 68))

        for widget in (
            drag_hint,
            self.count_label,
            self.minus_button,
            self.plus_button,
            self.range_button,
            self.timer_label,
            self.connection_label,
            self.log_button,
            self.close_button,
        ):
            layout.addWidget(widget)

        # 文字状态区域可直接作为拖动热区；按钮仍由自己接收鼠标事件。
        for label in (self.count_label, self.timer_label, self.connection_label):
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.minus_button.clicked.connect(
            lambda: self.change_food_count(-int(self.config["manual_step"]), "手动减少")
        )
        self.plus_button.clicked.connect(
            lambda: self.change_food_count(int(self.config["manual_step"]), "手动增加")
        )
        self.range_button.toggled.connect(self._set_manual_range)
        self.log_button.clicked.connect(self._toggle_log_panel)
        self.close_button.clicked.connect(self.close)

        toolbar_font = self._scaled_px(15, 12)
        count_font = self._scaled_px(18, 14)
        radius = self._scaled_px(15, 11)
        button_radius = self._scaled_px(9, 7)
        padding_v = self._scaled_px(8, 6)
        padding_h = self._scaled_px(12, 8)
        self.toolbar.setStyleSheet(
            f"""
            QFrame#toolbar {{ background: rgba(255, 255, 255, 248); border: 1px solid #e2e3e5; border-radius: {radius}px; }}
            QLabel {{ color: #34363a; font-family: 'Microsoft YaHei UI'; font-size: {toolbar_font}px; }}
            QLabel#count {{ color: #e66f2d; font-weight: 800; font-size: {count_font}px; }}
            QLabel#timer {{ color: #18865f; font-weight: 700; }}
            QLabel#connection {{ color: #5f6368; }}
            QPushButton {{
                color: #3c4043; background: #f3f4f5; border: 1px solid #e7e8ea;
                border-radius: {button_radius}px; padding: {padding_v}px {padding_h}px; font-family: 'Microsoft YaHei UI';
                font-size: {toolbar_font}px; font-weight: 600;
            }}
            QPushButton:hover {{ background: #e9eaec; }}
            QPushButton:checked {{ background: #dff7ee; color: #117558; border-color: #a9e5d0; }}
            QPushButton#closeGameButton {{
                color: #c3455c; background: #fff2f5; border-color: #ffd5de;
            }}
            QPushButton#closeGameButton:hover {{
                color: #a72f47; background: #ffe3e9; border-color: #ffbdca;
            }}
            """
        )
        self.toolbar.adjustSize()
        self.toolbar.move(self._toolbar_margin, self._toolbar_margin)
        self.toolbar.raise_()

        # R 键在游戏层获得焦点时可快速切换手动范围模式。
        self.range_shortcut = QShortcut(QKeySequence("R"), self)
        self.range_shortcut.activated.connect(self.range_button.toggle)

    def _refresh_toolbar_size(self) -> None:
        self.toolbar.adjustSize()
        self.toolbar.move(
            max(0, min(self.width() - self.toolbar.width(), self.toolbar.x())),
            max(0, min(self.height() - self.toolbar.height(), self.toolbar.y())),
        )

    def _build_log_panel(self) -> None:
        self._log_count = 0
        self._log_minimized = False
        self._log_expanded_height = min(
            380,
            max(220, self.height() - self.toolbar.geometry().bottom() - 26),
        )
        self.log_panel = QFrame(self)
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setFixedSize(min(480, max(380, self.width() - 32)), self._log_expanded_height)
        self.log_panel.move(16, self.toolbar.geometry().bottom() + 10)

        drag_hint = QLabel("⠿")
        drag_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        drag_hint.setToolTip("按住标题栏可移动日志")
        drag_hint.setStyleSheet("color: #b0b2b5; font-size: 19px;")
        title = QLabel("直播互动")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title.setStyleSheet(
            "color: #202124; font-family: 'Microsoft YaHei UI'; font-size: 18px; font-weight: 800;"
        )
        self.log_count_label = QLabel("等待第一条互动～")
        self.log_count_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.log_count_label.setStyleSheet(
            "color: #8a8d91; font-family: 'Microsoft YaHei UI'; font-size: 13px;"
        )
        self.log_clear_button = QPushButton("清空")
        self.log_clear_button.setFixedHeight(32)
        self.log_clear_button.clicked.connect(self._clear_logs)
        self.log_minimize_button = QPushButton("最小化")
        self.log_minimize_button.setFixedHeight(32)
        self.log_minimize_button.clicked.connect(self._minimize_log_panel)

        self.log_header = LogDragHandle(self.log_panel)
        header = QHBoxLayout(self.log_header)
        header.setContentsMargins(2, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(drag_hint)
        header.addWidget(title)
        header.addWidget(self.log_count_label, 1)
        header.addWidget(self.log_clear_button)
        header.addWidget(self.log_minimize_button)

        self.log_list = QListWidget()
        self.log_list.setFrameShape(QFrame.NoFrame)
        self.log_list.setFocusPolicy(Qt.NoFocus)
        self.log_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.log_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_list.setSpacing(6)
        self.log_list.setStyleSheet(
            "QListWidget { background: transparent; border: 0; outline: 0; }"
            "QScrollBar:vertical { background: #f4f4f4; width: 8px; margin: 2px 0; border-radius: 4px; }"
            "QScrollBar::handle:vertical { background: #c8c9cc; min-height: 32px; border-radius: 4px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        layout = QVBoxLayout(self.log_panel)
        layout.setContentsMargins(14, 12, 11, 13)
        layout.setSpacing(10)
        layout.addWidget(self.log_header)
        layout.addWidget(self.log_list, 1)
        self.log_panel.setStyleSheet(
            "QFrame#logPanel { background: rgba(255, 255, 255, 249);"
            "border: 1px solid #e4e5e7; border-radius: 18px; }"
            "QPushButton { color: #55585d; background: #f5f5f5;"
            "border: 1px solid #e7e7e7; border-radius: 9px; padding: 5px 10px;"
            "font-family: 'Microsoft YaHei UI'; font-size: 14px; }"
            "QPushButton:hover { background: #eeeeee; color: #202124; }"
        )
        self.log_panel.show()
        self.log_panel.raise_()

    def _minimize_log_panel(self) -> None:
        self._log_minimized = not self._log_minimized
        self.log_list.setVisible(not self._log_minimized)
        self.log_clear_button.setVisible(not self._log_minimized)
        self.log_panel.setFixedHeight(58 if self._log_minimized else self._log_expanded_height)
        self.log_minimize_button.setText("展开" if self._log_minimized else "最小化")
        self.log_panel.move(
            max(0, min(self.width() - self.log_panel.width(), self.log_panel.x())),
            max(0, min(self.height() - self.log_panel.height(), self.log_panel.y())),
        )
        self.log_panel.raise_()

    def _toggle_log_panel(self) -> None:
        visible = not self.log_panel.isVisible()
        self.log_panel.setVisible(visible)
        self.log_button.setText(
            f"{'收起互动' if visible else '互动记录'} {self._log_count}"
        )
        if visible:
            self.log_panel.raise_()
        self._refresh_toolbar_size()

    def _clear_logs(self) -> None:
        self.log_list.clear()
        self._log_count = 0
        self.log_count_label.setText("等待新的互动～")
        self.log_button.setText("收起互动 0" if self.log_panel.isVisible() else "互动记录 0")
        self._refresh_toolbar_size()

    def add_log_event(self, event_type: str, title: str, detail: str = "") -> None:
        if not hasattr(self, "log_list"):
            return
        # 日志只允许直播弹幕加、直播弹幕减和礼物三种事件。
        if event_type not in {"feed", "decrease", "gift"}:
            return
        card = LogEntryCard(event_type, str(title), str(detail), time.strftime("%H:%M:%S"))
        item = QListWidgetItem()
        item.setSizeHint(QSize(438, 78 if detail else 62))
        self.log_list.addItem(item)
        self.log_list.setItemWidget(item, card)
        while self.log_list.count() > 200:
            self.log_list.takeItem(0)
        self._log_count = self.log_list.count()
        self.log_count_label.setText(f"最近 {self._log_count} 条 · 可滚动查看")
        self.log_button.setText(
            f"{'收起互动' if self.log_panel.isVisible() else '互动记录'} {self._log_count}"
        )
        self.log_list.scrollToBottom()
        self.log_panel.raise_()
        self._refresh_toolbar_size()

    def _build_consumer(self) -> None:
        size = self._scaled_px(int(self.config["consumer_size"]), 54)
        self.consumer = ConsumerItem(
            self,
            self.config.get("consumer_image", ""),
            self._consumer_fallback_pixmap,
            size,
        )
        self.consumer.move(self._default_consumer_position())
        # 父窗口已经显示后动态更换贴图时，新建子控件不会自动显示。
        self.consumer.show()
        self.consumer.raise_()

    def _build_overlays(self) -> None:
        self.empty_label = QLabel("没有食物了\n等待观众投喂…", self)
        self.empty_label.setAlignment(Qt.AlignCenter)
        empty_radius = self._scaled_px(18, 13)
        empty_font = self._scaled_px(22, 17)
        empty_pad_v = self._scaled_px(20, 14)
        empty_pad_h = self._scaled_px(34, 24)
        self.empty_label.setStyleSheet(
            "background: rgba(255,255,255,245); color: #303236; border: 1px solid #e5e6e8;"
            f"border-radius: {empty_radius}px; font-family: 'Microsoft YaHei UI';"
            f"font-size: {empty_font}px; font-weight: 700; padding: {empty_pad_v}px {empty_pad_h}px;"
        )
        self.empty_label.adjustSize()
        self.empty_label.move(
            (self.width() - self.empty_label.width()) // 2,
            (self.height() - self.empty_label.height()) // 2,
        )
        self.empty_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.effect_card = EatingFeedbackCard(self, self._display_scale)

        self.blessing_bubble = BlessingBubble(self)

        self.stats_overlay = StatsOverlay(self)
        self.stats_overlay.update_counts(self.eaten_count, self.food_count)
        self.stats_overlay.restore_position_from_config()
        self.stats_overlay.setVisible(bool(self.config.get("stats_visible", True)))
        self.stats_overlay.raise_()

        self.gift_effect_overlay = GiftEffectOverlay(self)
        self._refresh_gift_rule_overlay()

        self.wind_effect_overlay = WindEffectOverlay(self)
        self.wind_effect_overlay.setGeometry(self.rect())

    def _build_timers(self) -> None:
        self.range_timer = QTimer(self)
        self.range_timer.setInterval(100)
        self.range_timer.timeout.connect(self._update_range_state)
        self.range_timer.start()
        self.effect_timer = QTimer(self)
        self.effect_timer.setSingleShot(True)
        self.effect_timer.timeout.connect(self.effect_card.hide)
        self.physics_timer = QTimer(self)
        self.physics_timer.setInterval(25)
        self.physics_timer.timeout.connect(self._physics_tick)

    @property
    def range_active(self) -> bool:
        return self._manual_range or self._timed_range_until > time.monotonic()

    def _set_manual_range(self, enabled: bool) -> None:
        self._manual_range = enabled
        if not enabled and not self.range_active:
            self._cancel_drag()
        self._update_range_state()

    def toggle_manual_range(self) -> None:
        """供独立控制台切换手动范围模式。"""
        self._set_manual_range(not self._manual_range)

    def set_stats_visible(self, visible: bool) -> None:
        self.config["stats_visible"] = bool(visible)
        self.stats_overlay.setVisible(bool(visible))
        if visible:
            self.stats_overlay.raise_()
        self._stats_preferences_updated()

    def reset_stats_position(self) -> None:
        self.config["stats_x_ratio"] = 0.03
        self.config["stats_y_ratio"] = 0.03
        self.stats_overlay.restore_position_from_config()
        self._stats_preferences_updated()

    def reset_stats_scale(self) -> None:
        self.stats_overlay.set_scale_factor(1.0)

    def apply_runtime_config(self, new_config: dict) -> None:
        """在游戏运行中应用贴图、布局、范围与显示设置，并保留本局计数。"""
        old_config = dict(self.config)
        old_consumer_center = self.consumer.geometry().center()
        food_visual_keys = {
            "food_images",
            "food_image_order",
            "food_size",
            "food_layout_mode",
        }
        rebuild_food = any(
            old_config.get(key) != new_config.get(key) for key in food_visual_keys
        )
        rebuild_consumer = any(
            old_config.get(key) != new_config.get(key)
            for key in ("consumer_image", "consumer_size")
        )
        sound_changed = any(
            old_config.get(key) != new_config.get(key)
            for key in ("sound_enabled", "sound_files")
        )

        self._cancel_drag()
        # 原字典可能仍被控制器或监听器引用，因此就地更新最稳妥。
        self.config.clear()
        self.config.update(new_config)

        if rebuild_food:
            self._rebuild_food_visuals()

        if rebuild_consumer:
            old_consumer = self.consumer
            old_consumer.hide()
            old_consumer.deleteLater()
            self._build_consumer()
            self.consumer.move(
                max(0, min(self.width() - self.consumer.width(),
                           old_consumer_center.x() - self.consumer.width() // 2)),
                max(0, min(self.height() - self.consumer.height(),
                           old_consumer_center.y() - self.consumer.height() // 2)),
            )
            self._consumer_was_moved = True

        if sound_changed:
            self.sound_player.stop()
            self.sound_player.deleteLater()
            self.sound_player = GameSoundPlayer(
                bool(self.config.get("sound_enabled", True)),
                self,
                self.config.get("sound_files", {}),
            )

        self.stats_overlay.set_scale_factor(
            float(self.config.get("stats_scale", 1.0)), notify=False
        )
        self.stats_overlay.restore_position_from_config()
        self.stats_overlay.setVisible(bool(self.config.get("stats_visible", True)))
        self._refresh_gift_rule_overlay()
        self._update_count_display()
        self.consumer.raise_()
        if self.stats_overlay.isVisible():
            self.stats_overlay.raise_()

    def _rebuild_food_visuals(self) -> None:
        """仅当贴图、尺寸或排列方式变化时重建食物，数量保持不变。"""
        if hasattr(self, "wind_effect_overlay") and self.wind_effect_overlay.active:
            self.wind_effect_overlay.stop_and_settle()
        self.physics_timer.stop()
        for item in self.food_items:
            item.release_media()
            item.hide()
            item.deleteLater()
        self.food_items.clear()
        for movie in self._food_movie_cache.values():
            movie.stop()
            movie.deleteLater()
        self._food_movie_cache.clear()
        self._food_movie_items.clear()
        self._food_pixmap_cache.clear()
        self._rotated_food_pixmap_cache.clear()
        self._pile_target_cache.clear()
        self._free_pile_slots.clear()
        self._next_pile_slot = 0
        self._image_index = 0
        self._sync_food_widgets()

    def _stats_preferences_updated(self) -> None:
        available_x = max(1, self.width() - self.stats_overlay.width())
        available_y = max(1, self.height() - self.stats_overlay.height())
        preferences = {
            "stats_visible": self.stats_overlay.isVisible(),
            "stats_scale": round(self.stats_overlay.scale_factor, 2),
            "stats_x_ratio": max(0.0, min(1.0, self.stats_overlay.x() / available_x)),
            "stats_y_ratio": max(0.0, min(1.0, self.stats_overlay.y() / available_y)),
        }
        self.config.update(preferences)
        self.stats_preferences_changed.emit(preferences)

    def _gift_effect_preferences_updated(self) -> None:
        """与统计展示框相同：拖动松手后按比例保存位置。"""
        available_x = max(1, self.width() - self.gift_effect_overlay.width())
        available_y = max(1, self.height() - self.gift_effect_overlay.height())
        preferences = {
            "gift_effect_position_set": True,
            "gift_effect_x_ratio": max(
                0.0, min(1.0, self.gift_effect_overlay.x() / available_x)
            ),
            "gift_effect_y_ratio": max(
                0.0, min(1.0, self.gift_effect_overlay.y() / available_y)
            ),
        }
        self.config.update(preferences)
        self.stats_preferences_changed.emit(preferences)

    def trigger_timed_range(self, seconds: int, source: str = "礼物") -> None:
        seconds = max(1, int(seconds))
        now = time.monotonic()
        self._timed_range_until = max(now, self._timed_range_until) + seconds
        self._update_range_state()

    def _update_range_state(self) -> None:
        now = time.monotonic()
        remaining = max(0.0, self._timed_range_until - now)
        if remaining <= 0:
            self._timed_range_until = 0.0
        active = self.range_active
        self.range_button.setText("范围拾取：开" if active else "范围拾取：关")
        if self._manual_range and remaining > 0:
            self.timer_label.setText(f"手动开启 · 礼物剩余 {math.ceil(remaining)}s")
        elif self._manual_range:
            self.timer_label.setText("手动开启 ∞")
        elif remaining > 0:
            self.timer_label.setText(f"剩余 {math.ceil(remaining)}s")
        else:
            self.timer_label.setText("")
        self.range_button.setProperty("timedActive", active)
        if active:
            self.range_button.setStyleSheet("background: #1fb981; color: white;")
        else:
            self.range_button.setStyleSheet("")
        if not active and self._drag_kind in {"range_fixed", "marquee"}:
            self._cancel_drag()
        self._refresh_toolbar_size()
        report = (active, math.ceil(remaining))
        if report != self._last_range_report:
            self._last_range_report = report
            self.range_state_changed.emit(*report)

    def set_connection_status(self, text: str, state: str = "info") -> None:
        colors = {
            "connected": "#16865f",
            "reconnecting": "#ae7418",
            "error": "#d64b62",
            "offline": "#777b80",
            "info": "#5f6368",
        }
        self.connection_label.setText(f"直播：{text}")
        self.connection_label.setStyleSheet(f"color: {colors.get(state, colors['info'])};")
        self._refresh_toolbar_size()

    def show_activity(self, text: str) -> None:
        """互动日志已迁到控制台；游戏层这里只保留礼物提示音。"""
        text = str(text)
        parts = text.split("\t")
        if len(parts) >= 4 and parts[0] == "gift":
            self.sound_player.play("gift")

    def show_gift_effect(self, gift_name: str, gift_num: int, effect_text: str) -> None:
        """收到礼物后把常驻浮窗更新为这次实际触发的作用。"""
        if not bool(self.config.get("gift_effect_overlay_enabled", True)):
            return
        self.gift_effect_overlay.show_live_effect(gift_name, gift_num, effect_text)

    @staticmethod
    def _configured_effect_text(operation: str, value: float) -> str:
        if operation in {"add", "subtract"}:
            action = "投喂" if operation == "add" else "减少"
            return f"{action} {int(round(value))} 个"
        if operation == "clear":
            return "清空食物"
        if operation == "wind":
            return "刮大风 · 随机增减 10%～50%"
        symbol = "×" if operation == "multiply" else "÷"
        return f"食物 {symbol}{value:g}"

    def _refresh_gift_rule_overlay(self) -> None:
        """游戏启动或应用配置后，按设置顺序显示全部礼物规则。"""
        if not hasattr(self, "gift_effect_overlay"):
            return
        if not bool(self.config.get("gift_effect_overlay_enabled", True)):
            self.gift_effect_overlay.hide()
            return
        entries_by_name: Dict[str, Dict] = {}
        for rule in self.config.get("gift_food_rules", []):
            gift_name = str(rule.get("gift_name", "")).strip()
            if not gift_name:
                continue
            entry = entries_by_name.setdefault(
                gift_name,
                {
                    "gift_name": gift_name,
                    "gift_id": int(rule.get("gift_id", 0) or 0),
                    "effects": [],
                },
            )
            if not entry["gift_id"]:
                entry["gift_id"] = int(rule.get("gift_id", 0) or 0)
            entry["effects"].append(
                self._configured_effect_text(
                    str(rule.get("operation", "add")),
                    float(rule.get("value", 1.0)),
                )
            )
        for rule in self.config.get("gift_range_rules", []):
            gift_name = str(rule.get("gift_name", "")).strip()
            if not gift_name:
                continue
            entry = entries_by_name.setdefault(
                gift_name,
                {
                    "gift_name": gift_name,
                    "gift_id": int(rule.get("gift_id", 0) or 0),
                    "effects": [],
                },
            )
            if not entry["gift_id"]:
                entry["gift_id"] = int(rule.get("gift_id", 0) or 0)
            entry["effects"].append(
                f"范围拾取 {int(rule.get('seconds', 1))} 秒"
            )
        entries = [
            {
                "gift_name": entry["gift_name"],
                "gift_id": entry["gift_id"],
                "effect_text": " · ".join(entry["effects"]) or "触发互动",
            }
            for entry in entries_by_name.values()
        ]
        self.gift_effect_overlay.set_rules(entries)

    def _raise_gift_effect(self) -> None:
        """物理刷新和拖拽会改变子控件层级，礼物提示必须始终保持最上层。"""
        if (
            hasattr(self, "gift_effect_overlay")
            and self.gift_effect_overlay.isVisible()
        ):
            self.gift_effect_overlay.raise_()

    def apply_external_delta(self, delta: int, source: str) -> None:
        self.change_food_count(int(delta), source)

    def apply_gift_operation(
        self,
        operation: str,
        value: float,
        gift_num: int,
        source: str,
    ) -> None:
        """按礼物数量执行食物运算；刮风会逐次随机增减 10%～50%。"""
        operation = str(operation)
        value = max(0.01, float(value))
        quantity = max(1, int(gift_num))
        if operation == "wind" and self.wind_effect_overlay.pending_food_count is not None:
            old_count = int(self.wind_effect_overlay.pending_food_count)
        else:
            old_count = self.food_count
        if operation == "add":
            target = old_count + int(round(value * quantity))
        elif operation == "subtract":
            target = old_count - int(round(value * quantity))
        elif operation == "multiply":
            # 连送数量代表规则连续触发；先用对数判断是否会超过安全上限，
            # 避免 value ** quantity 本身产生巨大整数或浮点溢出。
            if old_count <= 0:
                target = 0
            elif value <= 1.0:
                target = old_count
            elif quantity * math.log(value) >= math.log(MAX_FOOD_COUNT / old_count):
                target = MAX_FOOD_COUNT
            else:
                target = int(round(old_count * (value ** quantity)))
        elif operation == "divide":
            if value <= 1.0:
                target = old_count
            elif quantity * math.log(value) > math.log(max(1, old_count)) + 1:
                target = 0
            else:
                target = int(old_count / (value ** quantity))
        elif operation == "clear":
            target = 0
        elif operation == "wind":
            target = old_count
            for _ in range(quantity):
                percent = random.uniform(0.10, 0.50)
                change = max(1, int(round(max(1, target) * percent)))
                if random.choice((True, False)):
                    target = min(MAX_FOOD_COUNT, target + change)
                else:
                    target = max(0, target - change)
        else:
            return
        target = max(0, min(MAX_FOOD_COUNT, target))
        if operation == "wind":
            # 先卷起当前全部食物，动画结束后再结算随机增减，避免一触发就
            # 瞬间删掉一半食物，看不到“全部被刮起来”的效果。
            self.wind_effect_overlay.start_wind(quantity, target, source)
            self._raise_gift_effect()
            if self.stats_overlay.isVisible():
                self.stats_overlay.raise_()
            return
        self.change_food_count(target - old_count, source)

    def change_food_count(self, delta: int, source: str = "") -> None:
        if delta == 0:
            return
        old_count = self.food_count
        self.food_count = max(0, min(MAX_FOOD_COUNT, self.food_count + int(delta)))
        actual = self.food_count - old_count
        if actual == 0:
            return
        if (
            hasattr(self, "wind_effect_overlay")
            and self.wind_effect_overlay.active
            and self.wind_effect_overlay.pending_food_count is not None
        ):
            self.wind_effect_overlay.adjust_pending_food_count(actual)
        if actual < 0:
            self.eaten_count += -actual
        self._cancel_drag()
        self._sync_food_widgets()
        self._update_count_display()
        # 礼物在 activity 中播放专属音效，避免同一事件连续响两次。
        if not source.startswith("礼物 "):
            self.sound_player.play("add" if actual > 0 else "remove")

    def _sync_food_widgets(self) -> None:
        desired = self.food_count
        removed_any = False
        while len(self.food_items) > desired:
            item = self.food_items.pop()
            self._release_pile_slot(item.pile_slot)
            item.release_media()
            item.hide()
            item.deleteLater()
            removed_any = True
        if removed_any:
            self._compact_pile_slots()
        while len(self.food_items) < desired:
            self._create_food_item()
        # 批量创建结束后只调整一次层级，避免 +100 时重复做数百次窗口重排。
        self.consumer.raise_()
        if self.log_panel.isVisible():
            self.log_panel.raise_()
        self.toolbar.raise_()
        self._raise_gift_effect()
        if self.blessing_bubble.isVisible():
            self.blessing_bubble.reposition()
            self.blessing_bubble.raise_()
        if self.stats_overlay.isVisible():
            self.stats_overlay.raise_()
        if self.blessing_bubble.isVisible():
            self.blessing_bubble.raise_()
        if hasattr(self, "wind_effect_overlay") and self.wind_effect_overlay.active:
            self.wind_effect_overlay._capture_foods()
        else:
            self._wake_physics()
        self._update_count_display()

    def _create_food_item(self) -> None:
        slot = self._allocate_pile_slot()
        # 三档轻微尺寸差异让同一堆食物更自然；同档 GIF 继续共用解码器，
        # 不会因为每个食物都生成独立尺寸而拖慢性能。
        size_factors = (0.90, 1.0, 1.10)
        size = max(18, round(self._base_food_size() * size_factors[slot % 3]))
        angles = (-43, -34, -26, -18, -10, -6, 7, 13, 21, 29, 37, 45)
        angle_index = min(
            len(angles) - 1,
            int(self._slot_noise(slot, 127) * len(angles)),
        )
        rotation_angle = angles[angle_index]
        path = self._next_food_path()
        item = FoodItem(
            self,
            path,
            self._food_fallback_pixmap,
            size,
            rotation_angle,
        )
        item.pile_slot = slot
        item.show()
        self.food_items.append(item)
        self._spawn_food_item(item)

    def _next_food_path(self) -> str:
        paths = [path for path in self.config.get("food_images", []) if Path(path).is_file()]
        if not paths:
            return ""
        if self.config.get("food_image_order") == "sequential":
            path = paths[self._image_index % len(paths)]
            self._image_index += 1
        else:
            path = random.choice(paths)
        return path

    def _cached_food_pixmap(self, path: str, size: int, fallback: QPixmap) -> QPixmap:
        """缓存已经缩放好的静态食物贴图，批量加食物时不重复读盘和缩放。"""
        key = (str(path), int(size))
        cached = self._food_pixmap_cache.get(key)
        if cached is not None:
            return cached
        source = load_media_pixmap(path)
        if source.isNull():
            source = fallback
        scaled = source.scaled(
            QSize(size, size),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._food_pixmap_cache[key] = scaled
        return scaled

    @staticmethod
    def _rotate_into_square(source: QPixmap, size: int, angle: int) -> QPixmap:
        """把任意贴图平滑旋转后居中放回固定方形，避免旋转边缘被裁切。"""
        if source.isNull():
            return QPixmap()
        transformed = source.transformed(
            QTransform().rotate(float(angle)),
            Qt.SmoothTransformation,
        )
        transformed = transformed.scaled(
            QSize(size, size),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(
            (size - transformed.width()) // 2,
            (size - transformed.height()) // 2,
            transformed,
        )
        painter.end()
        return canvas

    def _rotated_food_pixmap(
        self,
        path: str,
        size: int,
        fallback: QPixmap,
        angle: int,
    ) -> QPixmap:
        key = (str(path), int(size), int(angle))
        cached = self._rotated_food_pixmap_cache.get(key)
        if cached is not None:
            return cached
        source = self._cached_food_pixmap(path, size, fallback)
        rotated = self._rotate_into_square(source, size, angle)
        self._rotated_food_pixmap_cache[key] = rotated
        return rotated

    def _shared_food_movie(self, path: str, size: int) -> Optional[QMovie]:
        """相同 GIF 食物共享解码器和帧缓存，大幅减少 CPU 与内存占用。"""
        if not path or Path(path).suffix.lower() != ".gif":
            return None
        key = (str(path), int(size))
        movie = self._food_movie_cache.get(key)
        if movie is not None:
            return movie
        movie = create_movie(path, self, QSize(size, size))
        if movie is None:
            return None
        self._food_movie_cache[key] = movie
        movie.start()
        return movie

    def _register_movie_food(self, movie: QMovie, item: FoodItem) -> None:
        items = self._food_movie_items.get(movie)
        if items is None:
            items = []
            self._food_movie_items[movie] = items
            movie.frameChanged.connect(
                lambda _frame, shared_movie=movie: self._update_food_movie_group(
                    shared_movie
                )
            )
        items.append(item)
        if movie.state() != QMovie.Running:
            movie.start()
        self._update_food_movie_group(movie)

    def _unregister_movie_food(self, movie: QMovie, item: FoodItem) -> None:
        items = self._food_movie_items.get(movie)
        if not items:
            return
        try:
            items.remove(item)
        except ValueError:
            return
        if not items:
            movie.stop()

    def _update_food_movie_group(self, movie: QMovie) -> None:
        """每个 GIF 帧只旋转有限个角度，再复用给同角度的全部食物。"""
        items = self._food_movie_items.get(movie, [])
        if not items:
            return
        source = movie.currentPixmap()
        if source.isNull():
            return
        frame_variants: Dict[tuple[int, int], QPixmap] = {}
        for item in items:
            key = (item.width(), item.rotation_angle)
            pixmap = frame_variants.get(key)
            if pixmap is None:
                pixmap = self._rotate_into_square(source, item.width(), item.rotation_angle)
                frame_variants[key] = pixmap
            item.setPixmap(pixmap)

    def _allocate_pile_slot(self) -> int:
        if self._free_pile_slots:
            return heapq.heappop(self._free_pile_slots)
        slot = self._next_pile_slot
        self._next_pile_slot += 1
        return slot

    def _release_pile_slot(self, slot: int) -> None:
        if slot >= 0:
            heapq.heappush(self._free_pile_slots, slot)

    def _compact_pile_slots(
        self, excluded_items: Optional[set[FoodItem]] = None
    ) -> None:
        """按当前视觉竖列压紧食物，让空洞上方的食物垂直下落。"""
        excluded = excluded_items or set()
        stacked_items = [
            item
            for item in self.food_items
            if item not in excluded and item.pile_slot >= 0
        ]
        if not stacked_items:
            self._free_pile_slots.clear()
            self._next_pile_slot = 0
            return

        column_count = self._pile_column_count()
        by_column: Dict[int, List[FoodItem]] = {}
        for item in stacked_items:
            column = self._nearest_pile_column(
                item.x() + item.width() / 2.0, column_count
            )
            by_column.setdefault(column, []).append(item)

        occupied_slots = set()
        for column, entries in by_column.items():
            # 屏幕坐标越大越靠下；先锁定每列最底部的食物，再依次安排上层。
            entries.sort(
                key=lambda item: (
                    -item.y(),
                    self._pile_slot_info(item.pile_slot)[1],
                    item.pile_slot,
                )
            )
            for level, item in enumerate(entries):
                new_slot = level * column_count + column
                occupied_slots.add(new_slot)
                item.pile_slot = new_slot
                canonical_target = self._pile_target(new_slot, item.width())
                # 只允许向下补位，不瞬移也不横向吸附；即使食物曾被自由拖放，
                # 当前竖列中存在空洞时，上方物体仍会落到下一层表面。
                if canonical_target.y() > item.y() + 1:
                    item.physics_x = float(item.x())
                    item.physics_y = float(item.y())
                    item.velocity_x = 0.0
                    item.velocity_y = max(0.0, item.velocity_y)
                    item.is_sleeping = False
                    item.free_falling = False
                    item.gravity_target = QPoint(item.x(), canonical_target.y())

        self._rebuild_pile_allocator(occupied_slots)
        if any(not item.is_sleeping for item in stacked_items):
            self._wake_physics()

    def _rebuild_pile_allocator(self, occupied_slots: Optional[set[int]] = None) -> None:
        """根据当前占用槽位重建分配器，避免释放、拖放后出现幽灵占位。"""
        occupied = occupied_slots
        if occupied is None:
            occupied = {
                item.pile_slot for item in self.food_items if item.pile_slot >= 0
            }
        self._next_pile_slot = max(occupied, default=-1) + 1
        self._free_pile_slots = [
            candidate
            for candidate in range(self._next_pile_slot)
            if candidate not in occupied
        ]
        heapq.heapify(self._free_pile_slots)

    def _pile_column_count(self) -> int:
        """按游戏宽度计算横向堆积列数。"""
        base_size = self._base_food_size()
        margin = max(6, round(base_size * 0.10))
        usable_width = max(base_size, self.width() - margin * 2)
        spacing_x = max(12, round(base_size * 0.72))
        return max(1, int(max(0, usable_width - base_size) / spacing_x) + 1)

    def _nearest_pile_column(self, center_x: float, column_count: int) -> int:
        """把自由落点归入最近竖列，之后该列仍能正常向下补位。"""
        if column_count <= 1:
            return 0
        base_size = self._base_food_size()
        margin = max(6, round(base_size * 0.10))
        left_center = margin + base_size / 2.0
        right_center = self.width() - margin - base_size / 2.0
        step = max(1.0, (right_center - left_center) / (column_count - 1))
        return max(
            0,
            min(column_count - 1, round((center_x - left_center) / step)),
        )

    def _pile_slot_info(self, slot: int) -> tuple[int, int]:
        """返回稳定槽位所属竖列，以及该食物从底部起的层数。"""
        column_count = self._pile_column_count()
        column_index = int(slot) % column_count
        level = int(slot) // column_count
        return column_index, level

    @staticmethod
    def _slot_noise(slot: int, salt: int) -> float:
        """与运行次数无关的稳定伪随机数，用于自然错位但绝不逐帧抖动。"""
        value = ((slot + 1) * 0x9E3779B1 + (salt + 11) * 0x85EBCA77) & 0xFFFFFFFF
        value ^= value >> 16
        value = (value * 0x7FEB352D) & 0xFFFFFFFF
        value ^= value >> 15
        value = (value * 0x846CA68B) & 0xFFFFFFFF
        value ^= value >> 16
        return value / 0xFFFFFFFF

    def _pile_target(self, slot: int, size: int) -> QPoint:
        """从底部横向铺层并逐层堆高，稳定后不会逐帧抖动。"""
        cache_key = (int(slot), int(size), self.width(), self.height())
        cached = self._pile_target_cache.get(cache_key)
        if cached is not None:
            return QPoint(cached)
        base_size = self._base_food_size()
        margin = max(6, round(base_size * 0.10))
        usable_width = max(base_size, self.width() - margin * 2)
        spacing_x = max(12, round(base_size * 0.72))
        spacing_y = max(10, round(base_size * 0.61))
        column_count = max(
            1,
            int(max(0, usable_width - base_size) / spacing_x) + 1,
        )
        column, level = self._pile_slot_info(slot)

        # 每层在水平方向轻微错开，再叠加确定性小扰动，视觉上像相互挤压的
        # 松散食物堆；扰动只由槽位决定，因此静止后不会抽搐。
        if column_count == 1:
            center_x = self.width() / 2.0
        else:
            left_center = margin + base_size / 2.0
            right_center = self.width() - margin - base_size / 2.0
            column_step = (right_center - left_center) / (column_count - 1)
            stagger = (column_step * 0.18) * (1 if level % 2 else -1)
            jitter_x = (self._slot_noise(slot, 41) - 0.5) * base_size * 0.25
            center_x = left_center + column * column_step + stagger + jitter_x

        jitter_y = (self._slot_noise(slot, 73) - 0.5) * base_size * 0.12
        x = round(center_x - size / 2.0)
        y = round(self.height() - size - margin - level * spacing_y + jitter_y)
        x = min(max(margin, x), max(margin, self.width() - size - margin))
        y = min(max(margin, y), max(margin, self.height() - size - margin))
        result = QPoint(x, y)
        self._pile_target_cache[cache_key] = result
        return QPoint(result)

    def _reflow_pile(self) -> None:
        """窗口尺寸改变时重排分层食物堆，坐标一次到位、不产生抖动。"""
        for item in self.food_items:
            item.gravity_target = None
            target = self._pile_target(item.pile_slot, item.width())
            if item.is_sleeping:
                item.physics_x = float(target.x())
                item.physics_y = float(target.y())
                item.move(target)
            else:
                item.physics_x = float(target.x())

    @staticmethod
    def _load_pixmap(path: str, kind: str) -> QPixmap:
        pixmap = load_media_pixmap(path)
        if not pixmap.isNull():
            return pixmap

        # 无贴图时绘制清晰的占位图，使项目开箱即可试玩。
        canvas_size = 256
        pixmap = QPixmap(canvas_size, canvas_size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        if kind == "consumer":
            painter.setBrush(QColor("#7a6ff0"))
            painter.setPen(QPen(QColor("#5148b8"), 8))
            painter.drawEllipse(18, 18, 220, 220)
            painter.setBrush(QColor("white"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(68, 82, 32, 42)
            painter.drawEllipse(156, 82, 32, 42)
            painter.setBrush(QColor("#25314a"))
            painter.drawEllipse(78, 94, 13, 18)
            painter.drawEllipse(166, 94, 13, 18)
            painter.setPen(QPen(QColor("white"), 9, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(72, 112, 112, 78, 200 * 16, 140 * 16)
        else:
            # 默认食物：胡萝卜。使用矢量路径绘制，任何缩放尺寸都保持清晰。
            painter.setPen(QPen(QColor("#d75a27"), 8, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(QColor("#ff7b32"))
            carrot = QPainterPath()
            carrot.moveTo(52, 77)
            carrot.cubicTo(78, 54, 176, 54, 203, 80)
            carrot.cubicTo(190, 130, 159, 191, 126, 233)
            carrot.cubicTo(99, 188, 68, 129, 52, 77)
            carrot.closeSubpath()
            painter.drawPath(carrot)

            painter.setPen(QPen(QColor("#267d45"), 6, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(QColor("#51b96c"))
            left_leaf = QPainterPath()
            left_leaf.moveTo(126, 70)
            left_leaf.cubicTo(75, 65, 67, 25, 75, 14)
            left_leaf.cubicTo(105, 17, 125, 43, 126, 70)
            painter.drawPath(left_leaf)
            right_leaf = QPainterPath()
            right_leaf.moveTo(128, 70)
            right_leaf.cubicTo(148, 26, 183, 19, 198, 29)
            right_leaf.cubicTo(191, 57, 163, 72, 128, 70)
            painter.drawPath(right_leaf)
            center_leaf = QPainterPath()
            center_leaf.moveTo(127, 68)
            center_leaf.cubicTo(106, 35, 119, 5, 135, 3)
            center_leaf.cubicTo(157, 24, 149, 52, 127, 68)
            painter.drawPath(center_leaf)

            painter.setPen(QPen(QColor("#ffc08e"), 7, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(84, 111, 114, 105)
            painter.drawLine(119, 151, 151, 143)
            painter.drawLine(111, 190, 133, 184)
        painter.end()
        return pixmap

    def _spawn_food_item(self, item: FoodItem) -> None:
        """新增食物从对应稳定槽位上方落下。"""
        size = item.width()
        item.gravity_target = None
        target = self._pile_target(item.pile_slot, size)
        x = float(target.x())
        y = float(random.randint(-size, 8))
        item.physics_x = x
        item.physics_y = y
        item.velocity_x = 0.0
        item.velocity_y = random.uniform(-20.0, 45.0)
        item.is_sleeping = False
        item.move(round(x), round(y))

    def _wake_physics(self) -> None:
        """有新物体或外力时唤醒物理模拟。"""
        if not hasattr(self, "physics_timer"):
            return
        if hasattr(self, "wind_effect_overlay") and self.wind_effect_overlay.active:
            return
        # 稳定槽位只做线性下落计算，可以保持更顺滑的动画。
        count = len(self.food_items)
        interval = 16 if count <= 300 else 25 if count <= 1000 else 33
        if self.physics_timer.interval() != interval:
            self.physics_timer.setInterval(interval)
        self._physics_stable_frames = 0
        now = time.monotonic()
        self._physics_last_time = now
        self._physics_awake_since = now
        if not self.physics_timer.isActive():
            self.physics_timer.start()

    def _physics_tick(self) -> None:
        """把食物落到确定性自然堆槽位；到位即休眠，绝不相互推挤。"""
        now = time.monotonic()
        dt = max(0.005, min(0.050, now - self._physics_last_time))
        self._physics_last_time = now
        if not self.food_items:
            self.physics_timer.stop()
            return
        # 拖拽食物或圆形范围拾取时冻结物理，避免鼠标与重力互相抢位置。
        if self._drag_kind in {"single", "range_fixed", "marquee"}:
            return

        active_items = [item for item in self.food_items if not item.is_sleeping]
        if not active_items:
            self.physics_timer.stop()
            return

        gravity = 1650.0 * self._display_scale
        auto_eaten: List[FoodItem] = []
        for item in active_items:
            target = (
                QPoint(item.gravity_target)
                if item.gravity_target is not None
                else self._pile_target(item.pile_slot, item.width())
            )
            target_x = float(target.x())
            horizontal_gap = target_x - item.physics_x
            if abs(horizontal_gap) <= 0.6:
                item.physics_x = target_x
                horizontal_settled = True
            else:
                # 槽位补齐时水平位置也柔和靠拢，不会突然横向跳动。
                item.physics_x += horizontal_gap * min(1.0, dt * 11.0)
                horizontal_settled = False
            previous_y = item.physics_y
            item.velocity_y += gravity * dt
            item.physics_y += item.velocity_y * dt
            reached_target = item.physics_y >= target.y()
            if item.physics_y >= target.y():
                item.physics_y = float(target.y())
                item.velocity_x = 0.0
                item.velocity_y = 0.0
                item.is_sleeping = horizontal_settled
            if self._falling_item_hits_consumer(
                item, previous_y, item.physics_y
            ):
                auto_eaten.append(item)
                continue
            if reached_target and item.is_sleeping:
                item.free_falling = False
            render_x = round(item.physics_x)
            render_y = round(item.physics_y)
            if item.x() != render_x or item.y() != render_y:
                item.move(render_x, render_y)
        if auto_eaten:
            self._consume_items(auto_eaten)
        self.consumer.raise_()
        # 用户松手后仍在自由下落的食物保持在食用者前面，画面上会清楚地
        # 看到食物从头顶落入口中；普通堆里的食物继续位于食用者后方。
        for item in self.food_items:
            if item.free_falling:
                item.raise_()
        if self.log_panel.isVisible():
            self.log_panel.raise_()
        self.toolbar.raise_()
        if hasattr(self, "stats_overlay") and self.stats_overlay.isVisible():
            self.stats_overlay.raise_()
        self._raise_gift_effect()

        if all(item.is_sleeping for item in self.food_items):
            self.physics_timer.stop()

    def _nearby_food_pairs(self):
        """按空间网格生成可能碰撞的食物对，数量增长时仍接近线性开销。"""
        cell_size = max(20.0, float(self._base_food_size()))
        grid: Dict[tuple[int, int], List[FoodItem]] = {}
        for item in self.food_items:
            center_x = item.physics_x + item.width() * 0.5
            center_y = item.physics_y + item.height() * 0.5
            cell = (math.floor(center_x / cell_size), math.floor(center_y / cell_size))
            grid.setdefault(cell, []).append(item)

        # 同一格内部，以及右侧四个方向的相邻格；每一对只生成一次。
        neighbor_offsets = ((1, -1), (1, 0), (1, 1), (0, 1))
        for (cell_x, cell_y), bucket in grid.items():
            for index, first in enumerate(bucket):
                for second in bucket[index + 1 :]:
                    if not (first.is_sleeping and second.is_sleeping):
                        yield first, second
            for offset_x, offset_y in neighbor_offsets:
                neighbor = grid.get((cell_x + offset_x, cell_y + offset_y))
                if neighbor:
                    for first in bucket:
                        for second in neighbor:
                            if not (first.is_sleeping and second.is_sleeping):
                                yield first, second

    def _resolve_world_bounds(self, item: FoodItem) -> None:
        margin = 10.0
        maximum_x = max(margin, self.width() - item.width() - margin)
        floor_y = max(12.0, self.height() - item.height() - 12.0)
        if item.physics_x < margin:
            item.physics_x = margin
            if item.velocity_x < 0:
                item.velocity_x *= -0.18
        elif item.physics_x > maximum_x:
            item.physics_x = maximum_x
            if item.velocity_x > 0:
                item.velocity_x *= -0.18
        if item.physics_y > floor_y:
            item.physics_y = floor_y
            if item.velocity_y > 0:
                item.velocity_y *= -0.05
            item.velocity_x *= 0.82
            if abs(item.velocity_y) < 20.0:
                item.velocity_y = 0.0

    @staticmethod
    def _resolve_food_collision(first: FoodItem, second: FoodItem) -> float:
        if first.is_sleeping and second.is_sleeping:
            return 0.0
        first_cx = first.physics_x + first.width() / 2
        first_cy = first.physics_y + first.height() / 2
        second_cx = second.physics_x + second.width() / 2
        second_cy = second.physics_y + second.height() / 2
        dx = second_cx - first_cx
        dy = second_cy - first_cy
        minimum_distance = first.collision_radius + second.collision_radius
        distance_squared = dx * dx + dy * dy
        if distance_squared >= minimum_distance * minimum_distance:
            return 0.0
        if distance_squared < 0.0001:
            dx, dy = 1.0, 0.0
            distance = 1.0
        else:
            distance = math.sqrt(distance_squared)
        normal_x = dx / distance
        normal_y = dy / distance
        overlap = minimum_distance - distance

        if first.is_sleeping:
            # 已休眠物体作为静态碰撞体，只修正仍在运动的 second。
            second.physics_x += normal_x * overlap
            second.physics_y += normal_y * overlap
            normal_velocity = second.velocity_x * normal_x + second.velocity_y * normal_y
            if normal_velocity < 0:
                second.velocity_x -= 1.08 * normal_velocity * normal_x
                second.velocity_y -= 1.08 * normal_velocity * normal_y
            second.velocity_x *= 0.97
            return overlap
        if second.is_sleeping:
            first.physics_x -= normal_x * overlap
            first.physics_y -= normal_y * overlap
            normal_velocity = first.velocity_x * normal_x + first.velocity_y * normal_y
            if normal_velocity > 0:
                first.velocity_x -= 1.08 * normal_velocity * normal_x
                first.velocity_y -= 1.08 * normal_velocity * normal_y
            first.velocity_x *= 0.97
            return overlap

        correction = overlap * 0.51
        first.physics_x -= normal_x * correction
        first.physics_y -= normal_y * correction
        second.physics_x += normal_x * correction
        second.physics_y += normal_y * correction

        relative_velocity = (
            (second.velocity_x - first.velocity_x) * normal_x
            + (second.velocity_y - first.velocity_y) * normal_y
        )
        if relative_velocity < 0:
            impulse = -(1.0 + 0.08) * relative_velocity / 2.0
            first.velocity_x -= impulse * normal_x
            first.velocity_y -= impulse * normal_y
            second.velocity_x += impulse * normal_x
            second.velocity_y += impulse * normal_y
        first.velocity_x *= 0.985
        second.velocity_x *= 0.985
        return overlap

    def _resolve_consumer_collision(self, item: FoodItem) -> float:
        """食用者平时作为静态碰撞体，拖喂时物理会暂停所以不影响投喂。"""
        rect = self.consumer.geometry().adjusted(8, 8, -8, -8)
        center_x = item.physics_x + item.width() / 2
        center_y = item.physics_y + item.height() / 2
        closest_x = max(rect.left(), min(rect.right(), center_x))
        closest_y = max(rect.top(), min(rect.bottom(), center_y))
        dx = center_x - closest_x
        dy = center_y - closest_y
        distance_squared = dx * dx + dy * dy
        radius = item.collision_radius
        if distance_squared >= radius * radius:
            return 0.0

        if distance_squared > 0.0001:
            distance = math.sqrt(distance_squared)
            normal_x, normal_y = dx / distance, dy / distance
            overlap = radius - distance
        else:
            distances = [
                (abs(center_x - rect.left()), -1.0, 0.0),
                (abs(rect.right() - center_x), 1.0, 0.0),
                (abs(center_y - rect.top()), 0.0, -1.0),
                (abs(rect.bottom() - center_y), 0.0, 1.0),
            ]
            edge_distance, normal_x, normal_y = min(distances, key=lambda value: value[0])
            overlap = radius + edge_distance

        item.physics_x += normal_x * overlap
        item.physics_y += normal_y * overlap
        normal_velocity = item.velocity_x * normal_x + item.velocity_y * normal_y
        if normal_velocity < 0:
            item.velocity_x -= 1.1 * normal_velocity * normal_x
            item.velocity_y -= 1.1 * normal_velocity * normal_y
        return overlap

    def _default_consumer_position(self) -> QPoint:
        margin = self._scaled_px(42, 26)
        return QPoint(
            max(margin, self.width() - self.consumer.width() - margin),
            max(
                self._scaled_px(100, 68),
                self.height() - self.consumer.height() - margin,
            ),
        )

    def _update_count_display(self) -> None:
        self.count_label.setText(
            f"<span style='color:#e06a84'>已吃：{self.eaten_count}</span>"
            "<span style='color:#b0b2b5'> · </span>"
            f"<span style='color:#e66f2d'>剩余：{self.food_count}</span>"
        )
        if hasattr(self, "stats_overlay"):
            self.stats_overlay.update_counts(self.eaten_count, self.food_count)
            if self.stats_overlay.isVisible():
                self.stats_overlay.raise_()
        self.food_count_changed.emit(self.eaten_count, self.food_count)
        self._refresh_toolbar_size()
        self.empty_label.setVisible(self.food_count == 0)
        if self.food_count == 0:
            self.empty_label.raise_()
            self.toolbar.raise_()
        self._raise_gift_effect()

    def begin_food_drag(self, item: FoodItem, global_pos: QPoint) -> None:
        if item not in self.food_items:
            return
        self._cancel_drag()
        self._drag_anchor = self.mapFromGlobal(global_pos)
        if self.range_active:
            radius = self._scaled_px(int(self.config["range_radius"]), 18)
            center = item.geometry().center()
            box = QRect(
                center.x() - radius,
                center.y() - radius,
                radius * 2,
                radius * 2,
            )
            self._drag_items = self._items_matching_circle(center, radius)
            if item not in self._drag_items:
                self._drag_items.append(item)
            self._drag_kind = "range_fixed"
            self._selection_rect = box
            self._fixed_box_origin = QRect(box)
        else:
            self._drag_items = [item]
            self._drag_kind = "single"
        self._drag_start_positions = {food: QPoint(food.pos()) for food in self._drag_items}
        # 拖喂时食物必须位于食用者前方；日志和工具条仍保持最上层。
        self.consumer.raise_()
        for food in self._drag_items:
            food.raise_()
        if self.log_panel.isVisible():
            self.log_panel.raise_()
        self.toolbar.raise_()
        self._raise_gift_effect()
        if self.blessing_bubble.isVisible():
            self.blessing_bubble.reposition()
            self.blessing_bubble.raise_()
        self.update()

    def begin_consumer_drag(self, global_pos: QPoint) -> None:
        """开始移动食用者；移动过程中食用判定区域会实时跟随。"""
        self._cancel_drag()
        self._drag_kind = "consumer"
        self._drag_anchor = self.mapFromGlobal(global_pos)
        self._consumer_drag_start = QPoint(self.consumer.pos())
        self.consumer.raise_()
        if self.log_panel.isVisible():
            self.log_panel.raise_()
        self.toolbar.raise_()
        self._raise_gift_effect()
        if self.blessing_bubble.isVisible():
            self.blessing_bubble.reposition()
            self.blessing_bubble.raise_()

    def move_consumer_drag(self, global_pos: QPoint) -> None:
        if self._drag_kind != "consumer":
            return
        delta = self.mapFromGlobal(global_pos) - self._drag_anchor
        desired = self._consumer_drag_start + delta
        minimum_y = 0
        x = max(0, min(self.width() - self.consumer.width(), desired.x()))
        y = max(
            minimum_y,
            min(self.height() - self.consumer.height(), desired.y()),
        )
        self.consumer.move(x, y)
        self.consumer.raise_()
        if self.log_panel.isVisible():
            self.log_panel.raise_()
        self.toolbar.raise_()
        self._raise_gift_effect()
        if self.blessing_bubble.isVisible():
            self.blessing_bubble.reposition()
            self.blessing_bubble.raise_()

    def finish_consumer_drag(self) -> None:
        if self._drag_kind != "consumer":
            return
        self._consumer_was_moved = True
        self._clear_drag_state()

    def move_food_drag(self, global_pos: QPoint) -> None:
        if self._drag_kind not in {"single", "range_fixed"}:
            return
        current = self.mapFromGlobal(global_pos)
        delta = current - self._drag_anchor
        for item, start in self._drag_start_positions.items():
            item.move(start + delta)
        if self._drag_kind == "range_fixed" and self._fixed_box_origin is not None:
            self._selection_rect = self._fixed_box_origin.translated(delta)
        self.update()

    def finish_food_drag(self, global_pos: QPoint) -> None:
        if self._drag_kind not in {"single", "range_fixed"}:
            return
        local_pos = self.mapFromGlobal(global_pos)
        items = list(self._drag_items)
        if items and self._consumer_hit(local_pos):
            self._consume_items(items)
        else:
            self._release_items_to_gravity(items)
        self._clear_drag_state()

    def _release_items_to_gravity(self, items: List[FoodItem]) -> None:
        """释放旧槽位并在当前位置垂直下落，同时压紧原竖列。"""
        dropped = [item for item in items if item in self.food_items]
        if not dropped:
            return
        excluded = set(dropped)
        # 拖走的食物不再占用原槽位；先让原位置上方的物体向下补齐。
        for item in dropped:
            self._release_pile_slot(item.pile_slot)
            item.pile_slot = -1
            item.gravity_target = None
        self._compact_pile_slots(excluded)

        column_count = self._pile_column_count()
        column_levels = {column: 0 for column in range(column_count)}
        occupied_slots = {
            item.pile_slot
            for item in self.food_items
            if item not in excluded and item.pile_slot >= 0
        }
        for slot in occupied_slots:
            column, level = self._pile_slot_info(slot)
            column_levels[column] = max(column_levels[column], level + 1)

        # 先处理位置较低的物体，范围拖放时仍保持大致的上下关系。
        dropped.sort(key=lambda food: food.y(), reverse=True)
        for item in dropped:
            x = max(0, min(self.width() - item.width(), item.x()))
            y = max(0, min(self.height() - item.height(), item.y()))
            column = self._nearest_pile_column(
                x + item.width() / 2.0, column_count
            )
            level = column_levels[column]
            slot = level * column_count + column
            while slot in occupied_slots:
                level += 1
                slot = level * column_count + column
            item.pile_slot = slot
            occupied_slots.add(slot)
            column_levels[column] = level + 1
            item.move(x, y)
            item.physics_x = float(x)
            item.physics_y = float(y)
            item.velocity_x = 0.0
            item.velocity_y = 0.0
            item.is_sleeping = False
            item.free_falling = True
            target_y = self._free_drop_target_y(item, excluded)
            item.gravity_target = QPoint(x, max(y, target_y))
        self._rebuild_pile_allocator(occupied_slots)
        self._wake_physics()

    def _free_drop_target_y(self, item: FoodItem, excluded: set) -> int:
        """寻找当前横向位置下方最近的食物表面或地面。"""
        margin = max(6, round(self._base_food_size() * 0.10))
        ground_y = max(0, self.height() - item.height() - margin)
        target_y = ground_y
        item_left = item.x() + round(item.width() * 0.18)
        item_right = item.x() + round(item.width() * 0.82)
        for other in self.food_items:
            if other is item or other in excluded or not other.isVisible():
                continue
            other_left = other.x() + round(other.width() * 0.18)
            other_right = other.x() + round(other.width() * 0.82)
            overlap = min(item_right, other_right) - max(item_left, other_left)
            if overlap <= min(item.width(), other.width()) * 0.18:
                continue
            step = max(9, round(min(item.height(), other.height()) * 0.54))
            candidate = other.y() - step
            if item.y() <= candidate < target_y:
                target_y = candidate
        return max(item.y(), target_y)

    def _falling_item_hits_consumer(
        self, item: FoodItem, previous_y: float, current_y: float
    ) -> bool:
        """只在自由下落穿过食用者上半部时自动判定喂食。"""
        if not item.free_falling:
            return False
        consumer = self.consumer.geometry()
        item_left = item.physics_x + item.width() * 0.22
        item_right = item.physics_x + item.width() * 0.78
        horizontal_overlap = min(item_right, consumer.right()) - max(
            item_left, consumer.left()
        )
        if horizontal_overlap <= item.width() * 0.20:
            return False
        catch_line = consumer.top() + consumer.height() * 0.34
        previous_bottom = previous_y + item.height() * 0.72
        current_bottom = current_y + item.height() * 0.72
        return previous_bottom <= catch_line <= current_bottom

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.range_active:
            self._cancel_drag()
            self._drag_kind = "marquee"
            self._drag_anchor = QPoint(event.pos())
            self._selection_rect = QRect(self._drag_anchor, self._drag_anchor)
            self._selection_cursor = QPoint(self._drag_anchor)
            self._marquee_all_positions = {
                item: QPoint(item.pos()) for item in self.food_items
            }
            event.accept()
            self.update()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_kind == "marquee" and event.buttons() & Qt.LeftButton:
            current = event.pos()
            radius = max(
                1,
                int(
                    math.ceil(
                        math.hypot(
                            current.x() - self._drag_anchor.x(),
                            current.y() - self._drag_anchor.y(),
                        )
                    )
                ),
            )
            box = QRect(
                self._drag_anchor.x() - radius,
                self._drag_anchor.y() - radius,
                radius * 2,
                radius * 2,
            )
            delta = current - self._drag_anchor
            matched = self._items_matching_original_circle(self._drag_anchor, radius)
            matched_set = set(matched)
            for item, start in self._marquee_all_positions.items():
                item.move(start + delta if item in matched_set else start)
            self.consumer.raise_()
            for item in matched:
                item.raise_()
            if self.log_panel.isVisible():
                self.log_panel.raise_()
            self.toolbar.raise_()
            self._raise_gift_effect()
            self._drag_items = matched
            self._selection_rect = box
            self._selection_cursor = QPoint(current)
            event.accept()
            self.update()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._drag_kind == "marquee":
            if self._drag_items and self._consumer_hit(event.pos()):
                self._consume_items(list(self._drag_items))
            else:
                self._release_items_to_gravity(list(self._drag_items))
                if not self._drag_items:
                    self.show_activity("圆形范围内没有食物")
            self._clear_drag_state()
            event.accept()
            return
        event.ignore()

    @staticmethod
    def _circle_matches_rect(
        center: QPoint, radius: int, rect: QRect, contains: bool
    ) -> bool:
        """判断圆形范围与食物矩形是否命中，支持部分碰到和完整包含。"""
        radius_squared = radius * radius
        if contains:
            corners = (
                rect.topLeft(),
                rect.topRight(),
                rect.bottomLeft(),
                rect.bottomRight(),
            )
            return all(
                (point.x() - center.x()) ** 2 + (point.y() - center.y()) ** 2
                <= radius_squared
                for point in corners
            )
        closest_x = max(rect.left(), min(center.x(), rect.right()))
        closest_y = max(rect.top(), min(center.y(), rect.bottom()))
        return (
            (closest_x - center.x()) ** 2 + (closest_y - center.y()) ** 2
            <= radius_squared
        )

    def _items_matching_circle(
        self, center: QPoint, radius: int
    ) -> List[FoodItem]:
        contains = self.config.get("range_hit_mode") == "contains"
        matches = [
            item
            for item in self.food_items
            if self._circle_matches_rect(center, radius, item.geometry(), contains)
        ]
        matches.sort(
            key=lambda item: (
                (item.geometry().center().x() - center.x()) ** 2
                + (item.geometry().center().y() - center.y()) ** 2,
                item.pile_slot,
            )
        )
        return matches[: self._range_pickup_limit()]

    def _items_matching_original_circle(
        self, center: QPoint, radius: int
    ) -> List[FoodItem]:
        contains = self.config.get("range_hit_mode") == "contains"
        matches = [
            (item, QRect(start, item.size()))
            for item, start in self._marquee_all_positions.items()
            if self._circle_matches_rect(
                center, radius, QRect(start, item.size()), contains
            )
        ]
        matches.sort(
            key=lambda entry: (
                (entry[1].center().x() - center.x()) ** 2
                + (entry[1].center().y() - center.y()) ** 2,
                entry[0].pile_slot,
            )
        )
        return [item for item, _rect in matches[: self._range_pickup_limit()]]

    def _range_pickup_limit(self) -> int:
        """单次范围拾取数量上限；旧配置缺失时默认 100。"""
        try:
            value = int(self.config.get("range_pickup_limit", 100))
        except (TypeError, ValueError):
            value = 100
        return max(1, min(10000, value))

    def _consumer_hit(self, local_pos: QPoint) -> bool:
        # 以松开鼠标的位置为准，避免多个食物保留间距时难以全部塞进贴图。
        padding = self._scaled_px(12, 8)
        return self.consumer.geometry().adjusted(
            -padding, -padding, padding, padding
        ).contains(local_pos)

    def _consume_items(self, items: List[FoodItem]) -> None:
        valid_items = list(dict.fromkeys(item for item in items if item in self.food_items))
        if not valid_items:
            return
        # 范围一次吃掉多种食物时，以第一个被吃掉的食物音效为本次提示音，
        # 避免同时播放大量声音造成爆音。
        food_sound_map = self.config.get("food_sound_files", {})
        specific_sound = str(
            food_sound_map.get(valid_items[0].source_path, "")
            if isinstance(food_sound_map, dict)
            else ""
        )
        star_wish = bool(
            self.config.get("active_theme_id") == "stars_jar"
            and any(Path(item.source_path).name.lower() == "star.png" for item in valid_items)
        )
        for item in valid_items:
            self.food_items.remove(item)
            self._release_pile_slot(item.pile_slot)
            item.release_media()
            item.hide()
            item.deleteLater()
        eaten = min(len(valid_items), self.food_count)
        self.food_count -= eaten
        self.eaten_count += eaten
        self._compact_pile_slots()
        self._sync_food_widgets()
        self._show_eating_effect(eaten)
        self.sound_player.play_file(specific_sound, "eat")
        if star_wish:
            self._show_star_blessing()

    def _show_star_blessing(self) -> None:
        messages = self.config.get("star_blessings", [])
        if not isinstance(messages, list):
            return
        choices = [str(message).strip() for message in messages if str(message).strip()]
        if choices:
            self.blessing_bubble.show_message(random.choice(choices))

    def _show_eating_effect(self, eaten: int) -> None:
        self.effect_card.pop(eaten, self.consumer.geometry())
        self.toolbar.raise_()
        self.effect_timer.start(1900)

    def _restore_dragged_items(self) -> None:
        for item, start in self._drag_start_positions.items():
            if item in self.food_items:
                item.move(start)

    def _clear_drag_state(self) -> None:
        affected_items = [item for item in self._drag_items if item in self.food_items]
        for item in affected_items:
            item.physics_x = float(item.x())
            item.physics_y = float(item.y())
            item.velocity_x = 0.0
            item.velocity_y = 0.0
            item.is_sleeping = False
        self._drag_kind = None
        self._drag_items = []
        self._drag_start_positions = {}
        self._marquee_all_positions = {}
        self._selection_rect = None
        self._selection_cursor = None
        self._fixed_box_origin = None
        self.update()
        if affected_items:
            self._wake_physics()

    def _cancel_drag(self) -> None:
        if self._drag_kind in {"single", "range_fixed"}:
            self._restore_dragged_items()
        elif self._drag_kind == "marquee":
            for item, start in self._marquee_all_positions.items():
                if item in self.food_items:
                    item.move(start)
        self._clear_drag_state()

    def paintEvent(self, event) -> None:  # noqa: N802
        # 每次重绘先用 Source 模式把顶层窗口清成真实 Alpha=0，避免某些显卡
        # 或采集方式把未初始化像素显示为黑色。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        if self._selection_rect is None or not self.range_active:
            painter.end()
            return
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setPen(
            QPen(
                QColor(64, 240, 184, 235),
                self._scaled_px(3, 2),
                Qt.DashLine,
            )
        )
        painter.setBrush(QColor(45, 219, 164, 35))
        painter.drawEllipse(self._selection_rect)
        if self._drag_kind == "marquee" and self._selection_cursor is not None:
            painter.setPen(
                QPen(
                    QColor(255, 255, 255, 220),
                    self._scaled_px(2, 1),
                    Qt.SolidLine,
                )
            )
            painter.drawLine(self._drag_anchor, self._selection_cursor)
            painter.setBrush(QColor(64, 240, 184, 245))
            painter.setPen(Qt.NoPen)
            center_radius = self._scaled_px(5, 4)
            painter.drawEllipse(self._drag_anchor, center_radius, center_radius)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_pile_target_cache"):
            self._pile_target_cache.clear()
        if hasattr(self, "toolbar"):
            if self._toolbar_was_dragged:
                self.toolbar.move(
                    max(0, min(self.width() - self.toolbar.width(), self.toolbar.x())),
                    max(0, min(self.height() - self.toolbar.height(), self.toolbar.y())),
                )
            else:
                self.toolbar.move(self._toolbar_margin, self._toolbar_margin)
        if hasattr(self, "consumer"):
            if self._consumer_was_moved:
                self.consumer.move(
                    max(0, min(self.width() - self.consumer.width(), self.consumer.x())),
                    max(0, min(self.height() - self.consumer.height(), self.consumer.y())),
                )
            else:
                self.consumer.move(self._default_consumer_position())
        if hasattr(self, "food_items"):
            self._reflow_pile()
            if any(not item.is_sleeping for item in self.food_items):
                self._wake_physics()
        if hasattr(self, "empty_label"):
            self.empty_label.move(
                (self.width() - self.empty_label.width()) // 2,
                (self.height() - self.empty_label.height()) // 2,
            )
        if hasattr(self, "log_panel"):
            self.log_panel.setFixedWidth(min(480, max(380, self.width() - 32)))
            if getattr(self.log_panel, "_was_dragged", False):
                self.log_panel.move(
                    max(0, min(self.width() - self.log_panel.width(), self.log_panel.x())),
                    max(0, min(self.height() - self.log_panel.height(), self.log_panel.y())),
                )
            else:
                self.log_panel.move(16, self.toolbar.geometry().bottom() + 10)
        if hasattr(self, "stats_overlay"):
            self.stats_overlay._clamp_inside_parent()
            if self.stats_overlay.isVisible():
                self.stats_overlay.raise_()
        if hasattr(self, "gift_effect_overlay") and self.gift_effect_overlay.isVisible():
            self.gift_effect_overlay.reposition()
            self.gift_effect_overlay.raise_()
        if hasattr(self, "blessing_bubble") and self.blessing_bubble.isVisible():
            self.blessing_bubble.reposition()
            self.blessing_bubble.raise_()
        if hasattr(self, "wind_effect_overlay"):
            self.wind_effect_overlay.setGeometry(self.rect())

    def _interactive_at(self, local_pos: QPoint) -> bool:
        if self.range_active:
            return True
        if self.toolbar.isVisible() and self.toolbar.geometry().contains(local_pos):
            return True
        if self.log_panel.isVisible() and self.log_panel.geometry().contains(local_pos):
            return True
        if self.consumer.geometry().contains(local_pos):
            return True
        if (
            hasattr(self, "gift_effect_overlay")
            and self.gift_effect_overlay.isVisible()
            and self.gift_effect_overlay.geometry().contains(local_pos)
        ):
            return True
        if (
            hasattr(self, "stats_overlay")
            and self.stats_overlay.isVisible()
            and self.stats_overlay.geometry().contains(local_pos)
        ):
            return True
        return any(item.geometry().contains(local_pos) for item in self.food_items)

    def nativeEvent(self, event_type, message):  # noqa: N802
        """Windows 透明像素点击穿透；游戏控件和食物仍可接收鼠标。"""
        if sys.platform == "win32":
            try:
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    local = self.mapFromGlobal(QPoint(x, y))
                    return True, HTCLIENT if self._interactive_at(local) else HTTRANSPARENT
            except (ValueError, TypeError, OSError):
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.quit_requested.emit()
        event.accept()
