"""主设置界面。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import normalize_config
from .gift_catalog import GiftCatalogSyncThread, load_cached_gifts
from .media import load_pixmap, set_label_media
from .sound import GameSoundPlayer
from .templates import builtin_templates, materialize_builtin_template


IMAGE_FILTER = "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.svg);;所有文件 (*)"
AUDIO_FILTER = "音频文件 (*.wav *.mp3 *.ogg *.m4a *.aac *.flac);;所有文件 (*)"
SOUND_EVENTS = (
    ("add", "增加食物"),
    ("remove", "减少食物"),
    ("eat", "吃掉食物"),
    ("gift", "收到礼物"),
)
GIFT_RULE_TEMPLATE_PRESETS = (
    {
        "id": "daily_feed",
        "name": "日常投喂",
        "description": "人气票投喂 10、花花投喂 100、小花花开启范围拾取 3 秒",
        "gift_food_rules": [
            {"gift_name": "人气票", "operation": "add", "value": 10.0},
            {"gift_name": "花花", "operation": "add", "value": 100.0},
        ],
        "gift_range_rules": [
            {"gift_name": "小花花", "seconds": 3},
        ],
    },
    {
        "id": "double_challenge",
        "name": "倍率挑战",
        "description": "一整套包含增加、减少、乘以、除以与范围拾取的玩法",
        "gift_food_rules": [
            {"gift_name": "人气票", "operation": "add", "value": 10.0},
            {"gift_name": "辣条", "operation": "subtract", "value": 20.0},
            {"gift_name": "牛哇牛哇", "operation": "multiply", "value": 2.0},
            {"gift_name": "打call", "operation": "divide", "value": 2.0},
        ],
        "gift_range_rules": [
            {"gift_name": "小花花", "seconds": 5},
        ],
    },
    {
        "id": "wind_party",
        "name": "大风派对",
        "description": "包含普通投喂、刮大风、清空和限时范围拾取",
        "gift_food_rules": [
            {"gift_name": "人气票", "operation": "add", "value": 10.0},
            {"gift_name": "打call", "operation": "wind", "value": 1.0},
            {"gift_name": "这个好诶", "operation": "clear", "value": 1.0},
        ],
        "gift_range_rules": [
            {"gift_name": "小花花", "seconds": 8},
        ],
    },
)


class EditableNumberInput(QSpinBox):
    """外观像普通输入框、仍带整数范围校验的数值输入控件。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # 隐藏容易被误认为“只能点选”的上下箭头，数字区域可直接键盘输入。
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lineEdit().setCursor(Qt.IBeamCursor)
        self.lineEdit().setPlaceholderText("请输入数字")
        self.setToolTip("点击输入数字，按 Enter 确认")

    def wheelEvent(self, event) -> None:  # noqa: N802
        # 禁止滚动设置页时误改数值；用户仍可点击后直接键盘输入。
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """禁用滚轮改值，避免滚动页面时意外修改规则。"""

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class NoWheelComboBox(QComboBox):
    """禁用滚轮切换下拉项，选项只能通过点击主动修改。"""

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class MediaPreview(QLabel):
    """设置页素材预览，GIF 会直接循环播放。"""

    def __init__(self, size: int = 120, parent=None) -> None:
        super().__init__(parent)
        self.preview_size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background: #fafaf8; border: 1px dashed #c9c9c3; border-radius: 10px;"
            "color: #777771;"
        )
        self.show_path("")

    def show_path(self, path: str) -> None:
        if not path:
            set_label_media(self, "", QSize(self.preview_size - 10, self.preview_size - 10))
            self.setText("暂无预览")
            return
        loaded = set_label_media(
            self,
            path,
            QSize(self.preview_size - 10, self.preview_size - 10),
        )
        if not loaded:
            self.setText("图片无法读取")


class RangePickupDemo(QWidget):
    """设置页中的圆形范围拾取操作示意图。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setToolTip("圆内碰到的食物会一起跟随鼠标，拖到食用者后松开即可投喂")

    @staticmethod
    def _draw_carrot(painter: QPainter, center: QPoint, selected: bool) -> None:
        painter.save()
        painter.translate(center)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(219, 249, 239))
            painter.drawEllipse(QPoint(0, 2), 17, 17)
        painter.setPen(QPen(QColor("#d96727") if selected else QColor("#b6b9b7"), 1))
        painter.setBrush(QColor("#ff8a3d") if selected else QColor("#d9dcda"))
        painter.drawPolygon(QPolygon([QPoint(-8, -6), QPoint(8, -6), QPoint(0, 17)]))
        painter.setPen(QPen(QColor("#42a978") if selected else QColor("#aeb4b0"), 4))
        painter.drawLine(-4, -8, -8, -16)
        painter.drawLine(0, -8, 0, -18)
        painter.drawLine(4, -8, 9, -15)
        painter.restore()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#e5e7e5"), 1))
        painter.setBrush(QColor("#fbfcfb"))
        painter.drawRoundedRect(card, 14, 14)

        width = self.width()
        center_y = 98
        circle_center = QPoint(max(105, width // 4), center_y)
        target_center = QPoint(min(width - 88, width * 3 // 4), center_y)
        radius = max(48, min(67, width // 10))

        title_font = painter.font()
        title_font.setPixelSize(15)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#343936"))
        painter.drawText(
            QRect(18, 10, width - 36, 24),
            Qt.AlignLeft | Qt.AlignVCenter,
            "圆形范围拾取示意",
        )

        circle_rect = QRect(
            circle_center.x() - radius,
            circle_center.y() - radius,
            radius * 2,
            radius * 2,
        )
        painter.setPen(QPen(QColor(43, 184, 137, 230), 3, Qt.DashLine))
        painter.setBrush(QColor(69, 219, 168, 35))
        painter.drawEllipse(circle_rect)
        painter.setPen(QPen(QColor("#82cdb3"), 2))
        painter.drawLine(circle_center, QPoint(circle_center.x() + radius, center_y))
        painter.setBrush(QColor("#2bb889"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(circle_center, 5, 5)

        for offset in (QPoint(-30, -17), QPoint(24, -26), QPoint(15, 29)):
            self._draw_carrot(painter, circle_center + offset, True)
        self._draw_carrot(
            painter, QPoint(circle_center.x() - radius - 25, center_y + 35), False
        )

        arrow_start = QPoint(circle_center.x() + radius + 13, center_y)
        arrow_end = QPoint(target_center.x() - 48, center_y)
        painter.setPen(QPen(QColor("#ee8aa8"), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(arrow_start, arrow_end)
        painter.drawLine(arrow_end, arrow_end + QPoint(-11, -8))
        painter.drawLine(arrow_end, arrow_end + QPoint(-11, 8))

        painter.setPen(QPen(QColor("#e27899"), 3))
        painter.setBrush(QColor("#fff0f5"))
        painter.drawEllipse(target_center, 42, 42)
        painter.setBrush(QColor("#3b4140"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(target_center + QPoint(-14, -8), 4, 5)
        painter.drawEllipse(target_center + QPoint(14, -8), 4, 5)
        painter.setPen(QPen(QColor("#e27899"), 3))
        painter.drawArc(
            QRect(target_center.x() - 17, target_center.y() - 2, 34, 24),
            200 * 16,
            140 * 16,
        )

        note_font = painter.font()
        note_font.setPixelSize(13)
        note_font.setBold(False)
        painter.setFont(note_font)
        painter.setPen(QColor("#6d736f"))
        painter.drawText(
            QRect(16, 151, width - 32, 28),
            Qt.AlignCenter,
            "① 按住食物或空白处拉出圆形范围    ② 拖到食用者身上松开",
        )
        painter.end()


class GiftNameCombo(NoWheelComboBox):
    """带礼物图标、搜索补全，同时允许保留手工输入名称。"""

    def __init__(self, gifts: Optional[List[Dict]] = None, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setIconSize(QSize(30, 30))
        self.setMaxVisibleItems(14)
        self.lineEdit().setPlaceholderText("输入或选择礼物")
        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(completer)
        self.set_catalog(gifts or [])

    def set_catalog(self, gifts: List[Dict]) -> None:
        current = self.currentText().strip()
        current_id = self.selected_gift_id()
        self.blockSignals(True)
        self.clear()
        for gift in gifts:
            name = str(gift.get("name", "")).strip()
            if not name:
                continue
            icon_path = str(gift.get("icon_path", "")).strip()
            icon = QIcon(icon_path) if icon_path else QIcon()
            price = int(gift.get("price", 0) or 0)
            self.addItem(icon, name, gift)
            index = self.count() - 1
            if price > 0:
                self.setItemData(index, f"{name} · {price / 1000:g} 元", Qt.ToolTipRole)
        self.set_gift_name(current, current_id)
        self.blockSignals(False)

    def set_gift_name(self, name: str, gift_id: int = 0) -> None:
        """显式选择对应项，确保图标与文字来自同一条礼物记录。"""
        target_name = str(name).strip()
        target_id = int(gift_id or 0)
        matched = -1
        if target_id:
            for index in range(self.count()):
                gift = self.itemData(index) or {}
                if int(gift.get("id", 0) or 0) == target_id:
                    matched = index
                    break
        # B 站可能为同名礼物更新 ID；旧 ID 不存在时按名称迁移到当前项。
        if matched < 0:
            matched = self.findText(target_name, Qt.MatchExactly)
        if matched >= 0:
            self.setCurrentIndex(matched)
        else:
            self.setCurrentIndex(-1)
            self.setEditText(target_name)

    def selected_gift_id(self) -> int:
        gift = self.currentData() or {}
        if str(gift.get("name", "")).strip() != self.currentText().strip():
            return 0
        return int(gift.get("id", 0) or 0)

    def selected_gift(self) -> Dict:
        """仅在输入文字与目录项完全一致时返回绑定的礼物数据。"""
        gift = self.currentData() or {}
        if str(gift.get("name", "")).strip() != self.currentText().strip():
            return {}
        return dict(gift)


class RuleTable(QWidget):
    """两列规则表，第二列固定为整数。"""

    def __init__(
        self,
        first_title: str,
        second_title: str,
        parent=None,
        gift_picker: bool = False,
    ) -> None:
        super().__init__(parent)
        self.first_title = first_title
        self.second_title = second_title
        self.gift_picker = bool(gift_picker)
        self._gift_catalog: List[Dict] = []
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([first_title, second_title])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(150)

        add_button = QPushButton("＋ 添加规则")
        remove_button = QPushButton("删除选中")
        add_button.clicked.connect(lambda: self.add_row("", 1, 0))
        remove_button.clicked.connect(self.remove_selected)

        button_layout = QHBoxLayout()
        button_layout.addWidget(add_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(button_layout)

    def add_row(self, name: str, value: int, gift_id: int = 0) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        if self.gift_picker:
            combo = GiftNameCombo(self._gift_catalog)
            combo.set_gift_name(str(name), gift_id)
            self.table.setCellWidget(row, 0, combo)
            self.table.setRowHeight(row, 48)
        else:
            self.table.setItem(row, 0, QTableWidgetItem(str(name)))
        self.table.setItem(row, 1, QTableWidgetItem(str(value)))

    def set_gift_catalog(self, gifts: List[Dict]) -> None:
        self._gift_catalog = list(gifts)
        if not self.gift_picker:
            return
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            if isinstance(combo, GiftNameCombo):
                combo.set_catalog(self._gift_catalog)

    def remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def set_rows(self, rows: List[Dict], name_key: str, value_key: str) -> None:
        self.table.setRowCount(0)
        for row in rows:
            self.add_row(
                str(row.get(name_key, "")),
                int(row.get(value_key, 1)),
                int(row.get("gift_id", 0) or 0),
            )

    def get_rows(self, name_key: str, value_key: str) -> List[Dict]:
        rows: List[Dict] = []
        for row in range(self.table.rowCount()):
            name_widget = self.table.cellWidget(row, 0)
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if isinstance(name_widget, GiftNameCombo):
                name = name_widget.currentText().strip()
            else:
                name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            try:
                value = int(value_item.text().strip()) if value_item else 0
            except ValueError as error:
                raise ValueError(f"{self.first_title}“{name}”的{self.second_title}必须是整数") from error
            result = {name_key: name, value_key: value}
            if self.gift_picker and isinstance(name_widget, GiftNameCombo):
                gift_id = name_widget.selected_gift_id()
                if gift_id:
                    result["gift_id"] = gift_id
            rows.append(result)
        return rows


class GiftFoodRuleTable(QWidget):
    """礼物食物运算表：支持固定运算、清空和随机风暴。"""

    OPERATIONS = (
        ("增加", "add"),
        ("减少", "subtract"),
        ("乘以", "multiply"),
        ("除以", "divide"),
        ("清空", "clear"),
        ("刮大风", "wind"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gift_catalog: List[Dict] = []
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["礼物名称", "运算方式", "数值 / 倍数"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(190)

        add_button = QPushButton("＋ 添加规则")
        remove_button = QPushButton("删除选中")
        add_button.clicked.connect(lambda: self.add_row("", "add", 1.0, 0))
        remove_button.clicked.connect(self.remove_selected)
        actions = QHBoxLayout()
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(actions)

    def add_row(
        self, gift_name: str, operation: str, value: float, gift_id: int = 0
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        gift_combo = GiftNameCombo(self._gift_catalog)
        gift_combo.set_gift_name(str(gift_name), gift_id)
        self.table.setCellWidget(row, 0, gift_combo)
        operation_combo = NoWheelComboBox()
        for label, data in self.OPERATIONS:
            operation_combo.addItem(label, data)
        index = operation_combo.findData(operation)
        operation_combo.setCurrentIndex(max(0, index))
        self.table.setCellWidget(row, 1, operation_combo)
        value_text = f"{float(value):g}"
        self.table.setItem(row, 2, QTableWidgetItem(value_text))
        operation_combo.currentIndexChanged.connect(
            lambda _index, combo=operation_combo: self._operation_changed(combo)
        )
        self._operation_changed(operation_combo)
        self.table.setRowHeight(row, 48)

    def _operation_changed(self, combo: QComboBox) -> None:
        row = next(
            (
                index
                for index in range(self.table.rowCount())
                if self.table.cellWidget(index, 1) is combo
            ),
            -1,
        )
        if row < 0:
            return
        value_item = self.table.item(row, 2)
        if value_item is None:
            value_item = QTableWidgetItem("1")
            self.table.setItem(row, 2, value_item)
        operation = str(combo.currentData() or "add")
        if operation in {"clear", "wind"}:
            value_item.setText("—")
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            value_item.setToolTip(
                "此操作不需要数值"
                if operation == "clear"
                else "随机增加或减少当前食物的 10%～50%"
            )
        else:
            if value_item.text().strip() in {"", "—"}:
                value_item.setText("2" if operation in {"multiply", "divide"} else "1")
            value_item.setFlags(value_item.flags() | Qt.ItemIsEditable)
            value_item.setToolTip("")

    def set_gift_catalog(self, gifts: List[Dict]) -> None:
        self._gift_catalog = list(gifts)
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            if isinstance(combo, GiftNameCombo):
                combo.set_catalog(self._gift_catalog)

    def remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def set_rows(self, rows: List[Dict]) -> None:
        self.table.setRowCount(0)
        for row in rows:
            self.add_row(
                str(row.get("gift_name", "")),
                str(row.get("operation", "add")),
                float(row.get("value", 1.0)),
                int(row.get("gift_id", 0) or 0),
            )

    def get_rows(self) -> List[Dict]:
        result: List[Dict] = []
        for row in range(self.table.rowCount()):
            name_widget = self.table.cellWidget(row, 0)
            value_item = self.table.item(row, 2)
            gift_name = (
                name_widget.currentText().strip()
                if isinstance(name_widget, GiftNameCombo)
                else ""
            )
            if not gift_name:
                continue
            operation_combo = self.table.cellWidget(row, 1)
            operation = operation_combo.currentData() if operation_combo else "add"
            if operation in {"clear", "wind"}:
                value = 1.0
            else:
                try:
                    value = float(value_item.text().strip()) if value_item else 0.0
                except ValueError as error:
                    raise ValueError(f"礼物“{gift_name}”的数值/倍数必须是数字") from error
                if value <= 0:
                    raise ValueError(f"礼物“{gift_name}”的数值/倍数必须大于 0")
                if operation in {"multiply", "divide"} and value <= 1:
                    raise ValueError(f"礼物“{gift_name}”的乘除倍数必须大于 1")
            item = {"gift_name": gift_name, "operation": operation, "value": value}
            if isinstance(name_widget, GiftNameCombo):
                gift_id = name_widget.selected_gift_id()
                if gift_id:
                    item["gift_id"] = gift_id
            result.append(item)
        return result


class ConsoleLogCard(QFrame):
    """控制台直播互动列表中的单条记录。"""

    THEMES = {
        "feed": ("投", "#f4511e", "#fff0e9"),
        "decrease": ("吃", "#7b61c9", "#f2efff"),
        "gift": ("礼", "#e85f87", "#fff0f5"),
    }

    def __init__(self, event_type: str, title: str, detail: str) -> None:
        super().__init__()
        glyph, accent, tint = self.THEMES.get(event_type, self.THEMES["feed"])
        self.setObjectName("consoleLogCard")
        badge = QLabel(glyph)
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background:{tint}; color:{accent}; border-radius:19px; font-weight:800;"
        )
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size:16px; font-weight:700; color:#222222;")
        detail_label = QLabel(detail)
        detail_label.setStyleSheet("font-size:13px; color:#858585;")
        detail_label.setVisible(bool(detail))
        timestamp = QLabel(time.strftime("%H:%M:%S"))
        timestamp.setStyleSheet("font-size:12px; color:#aaaaaa;")
        timestamp.setAlignment(Qt.AlignTop | Qt.AlignRight)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(3)
        texts.addWidget(title_label)
        texts.addWidget(detail_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        layout.addWidget(badge)
        layout.addLayout(texts, 1)
        layout.addWidget(timestamp)


class SettingsWindow(QMainWindow):
    start_game = pyqtSignal(dict)
    apply_config_requested = pyqtSignal(dict)
    quit_requested = pyqtSignal()
    manual_delta_requested = pyqtSignal(int)
    range_toggle_requested = pyqtSignal()
    stats_visibility_requested = pyqtSignal(bool)
    stats_reset_position_requested = pyqtSignal()
    stats_reset_scale_requested = pyqtSignal()
    close_game_requested = pyqtSignal()
    license_activation_requested = pyqtSignal()

    def __init__(self, config: dict, data_dir: Optional[Path] = None) -> None:
        super().__init__()
        self._game_running = False
        self._log_count = 0
        self._sound_preview_player: Optional[GameSoundPlayer] = None
        self._food_sound_map: Dict[str, str] = {}
        self._gift_catalog: List[Dict] = load_cached_gifts()
        self._gift_catalog_thread: Optional[GiftCatalogSyncThread] = None
        self._gift_sync_room = ""
        self._license_valid = False
        self._license_plan_label = ""
        self._license_expires_at = 0
        self._config = normalize_config(config)
        self._data_dir = Path(data_dir or Path.cwd()).resolve()
        self._custom_templates: List[Dict] = list(
            self._config.get("custom_templates", [])
        )
        self._gift_rule_templates: List[Dict] = list(
            self._config.get("gift_rule_templates", [])
        )
        self._active_theme_id = str(self._config.get("active_theme_id", ""))
        self.setWindowTitle("小萝卜吃吃吃 · 直播控制台")
        self.resize(1240, 820)
        self.setMinimumSize(1060, 680)
        self._build_ui()
        self.set_config(self._config)
        self.license_countdown_timer = QTimer(self)
        self.license_countdown_timer.setInterval(1000)
        self.license_countdown_timer.timeout.connect(self._update_license_countdown)
        self.license_countdown_timer.start()
        # 设置页打开后自动同步当前房间；已缓存列表会先立即显示，无需等网络。
        QTimer.singleShot(450, self._auto_sync_gifts)

    def _build_ui(self) -> None:
        page = QWidget()
        page.setObjectName("page")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # 顶部固定为直播状态与窗口级操作，和参考稿保持一致。
        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 20, 30, 20)
        header_layout.setSpacing(18)
        title = QLabel("小萝卜吃吃吃")
        title.setObjectName("title")
        subtitle = QLabel("直播控制台")
        subtitle.setObjectName("headerSubtitle")
        self.connection_status_label = QLabel("●  等待启动")
        self.connection_status_label.setObjectName("connectionStatus")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addSpacing(16)
        header_layout.addWidget(self.connection_status_label)
        header_layout.addStretch(1)

        self.start_button = QPushButton("保存并圈选区域")
        self.start_button.setObjectName("startButton")
        self.start_button.setMinimumSize(176, 48)
        self.start_button.clicked.connect(self._submit)
        self.apply_button = QPushButton("保存并应用")
        self.apply_button.setObjectName("applyButton")
        self.apply_button.setMinimumSize(138, 48)
        self.apply_button.setEnabled(False)
        self.apply_button.setToolTip("不关闭游戏，立即应用贴图、范围和直播规则")
        self.apply_button.clicked.connect(self._apply_current_game)
        self.close_game_button = QPushButton("关闭游戏")
        self.close_game_button.setObjectName("closeGameButton")
        self.close_game_button.setMinimumSize(126, 48)
        self.close_game_button.setEnabled(False)
        self.close_game_button.clicked.connect(lambda: self.close_game_requested.emit())
        header_layout.addWidget(self.apply_button)
        header_layout.addWidget(self.start_button)
        header_layout.addWidget(self.close_game_button)
        page_layout.addWidget(header)

        body = QFrame()
        body.setObjectName("body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 22, 16, 22)
        sidebar_layout.setSpacing(10)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_labels = ("游戏控制", "显示设置", "直播互动")
        self.nav_buttons = []
        for index, label in enumerate(nav_labels):
            button = QPushButton(label)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setMinimumHeight(54)
            button.clicked.connect(lambda checked, value=index: self.pages.setCurrentIndex(value))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch()

        license_card = QFrame()
        license_card.setObjectName("licenseCard")
        license_layout = QVBoxLayout(license_card)
        license_layout.setContentsMargins(12, 10, 12, 10)
        license_layout.setSpacing(4)
        license_header = QHBoxLayout()
        license_title = QLabel("授权剩余")
        license_title.setObjectName("licenseTitle")
        self.license_activate_button = QPushButton("重新激活")
        self.license_activate_button.setObjectName("licenseActivateButton")
        self.license_activate_button.setFixedHeight(28)
        self.license_activate_button.clicked.connect(
            lambda: self.license_activation_requested.emit()
        )
        license_header.addWidget(license_title)
        license_header.addStretch(1)
        license_header.addWidget(self.license_activate_button)
        self.license_countdown_label = QLabel("正在读取…")
        self.license_countdown_label.setObjectName("licenseCountdown")
        self.license_countdown_label.setWordWrap(True)
        self.license_expiry_label = QLabel("")
        self.license_expiry_label.setObjectName("licenseExpiry")
        self.license_expiry_label.setWordWrap(True)
        license_layout.addLayout(license_header)
        license_layout.addWidget(self.license_countdown_label)
        license_layout.addWidget(self.license_expiry_label)
        sidebar_layout.addWidget(license_card)

        version = QLabel("小萝卜吃吃吃  ·  v2.0.0")
        version.setObjectName("sidebarVersion")
        version.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(version)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.pages.addWidget(self._build_dashboard_page())
        self.pages.addWidget(
            self._make_settings_page(
                "显示设置",
                "管理贴图、尺寸、圆形拾取和游戏显示效果",
                [
                    self._build_template_group(),
                    self._build_asset_group(),
                    self._build_gameplay_group(),
                    self._build_sound_group(),
                ],
            )
        )
        self.pages.addWidget(
            self._make_settings_page(
                "直播互动",
                "连接直播间，并统一设置弹幕与礼物的加、减、乘、除规则",
                [
                    self._build_live_group(),
                    self._build_danmaku_group(),
                    self._build_gift_group(),
                ],
            )
        )
        self.nav_buttons[0].setChecked(True)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(self.pages, 1)
        page_layout.addWidget(body, 1)
        self.setCentralWidget(page)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#page, QFrame#body, QStackedWidget#pages,
            QScrollArea#settingsScroll, QScrollArea#settingsScroll > QWidget > QWidget,
            QWidget#settingsContent, QWidget#dashboardContent { background: #faf9f7; }
            QWidget { color: #242424; font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 15px; }
            QFrame#header { background: #ffffff; border-bottom: 1px solid #e8e6e2; }
            QLabel#title { font-size: 28px; font-weight: 800; color: #181818; }
            QLabel#headerSubtitle { font-size: 17px; color: #77736f; }
            QLabel#connectionStatus {
                color: #77736f; background: #f4f3f1; border-radius: 12px;
                padding: 9px 15px; font-weight: 700;
            }
            QFrame#sidebar { background: #ffffff; border-right: 1px solid #ebe8e4; }
            QPushButton[nav="true"] {
                text-align: left; background: transparent; color: #46413e; border: 0;
                border-radius: 12px; padding: 12px 22px; font-size: 17px; font-weight: 650;
            }
            QPushButton[nav="true"]:hover { background: #fff5ef; color: #ef572f; }
            QPushButton[nav="true"]:checked {
                background: #fff0e8; color: #f04f25; font-weight: 800;
                border-left: 4px solid #ff5a2f;
            }
            QLabel#sidebarVersion { color: #b5b0aa; font-size: 12px; }
            QFrame#licenseCard {
                background: #fff8f3; border: 1px solid #f3d9cc; border-radius: 11px;
            }
            QLabel#licenseTitle { color: #7c716b; font-size: 12px; font-weight: 700; }
            QLabel#licenseCountdown { color: #e95029; font-size: 15px; font-weight: 850; }
            QLabel#licenseExpiry { color: #9a918b; font-size: 11px; }
            QPushButton#licenseActivateButton {
                min-width: 62px; max-width: 74px; padding: 3px 7px;
                border-radius: 7px; font-size: 12px; color: #e95029;
                background: #ffffff; border: 1px solid #f0b9a6;
            }
            QPushButton#licenseActivateButton:hover {
                background: #ffede5; border-color: #ff7953;
            }
            QLabel#pageTitle { font-size: 25px; font-weight: 800; color: #1f1f1f; }
            QLabel#pageSubtitle { font-size: 14px; color: #85817d; }
            QFrame#dashboardCard {
                background: #ffffff; border: 1px solid #e8e5e1; border-radius: 16px;
            }
            QLabel#cardTitle { font-size: 21px; font-weight: 800; color: #202020; }
            QLabel#metricCaption { font-size: 16px; color: #77736f; }
            QLabel#remainingValue { color: #f45127; font-size: 50px; font-weight: 900; }
            QGroupBox {
                background: #ffffff; border: 1px solid #e8e5e1; border-radius: 16px;
                margin-top: 18px;
                padding: 18px 16px 16px 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 7px;
                color: #20201f; font-size: 18px; font-weight: 800;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QTableWidget {
                background: white;
                border: 1px solid #ddd9d4; border-radius: 9px; padding: 8px 10px;
                selection-background-color: #fff0e8; selection-color: #4a2c20; min-height: 25px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
            QListWidget:focus, QTableWidget:focus { border: 1px solid #ff714a; }
            QHeaderView::section {
                background: #faf8f5; color: #5e5955; border: 0;
                border-bottom: 1px solid #e9e5e0; padding: 9px; font-weight: 700;
            }
            QTableWidget { gridline-color: #eeeae5; }
            QScrollBar:vertical {
                background: transparent; width: 10px; margin: 4px 2px;
            }
            QScrollBar::handle:vertical {
                background: #d6d2cd; border-radius: 4px; min-height: 32px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QPushButton {
                background: #ffffff; color: #37322f; border: 1px solid #ddd8d3;
                border-radius: 10px; padding: 9px 15px; font-size: 15px; font-weight: 650;
            }
            QPushButton:hover { background: #fff6f1; border-color: #ff9b7c; color: #e95029; }
            QPushButton#accentButton, QPushButton#rangeControlButton:checked {
                background: #ff5a2f; color: #ffffff; border-color: #ff5a2f;
            }
            QPushButton#toggleButton {
                background: #ece9e5; color: #716c68; border: 0; min-width: 82px;
            }
            QPushButton#toggleButton:checked { background: #ff5a2f; color: white; }
            QPushButton#startButton {
                background: #ffffff; color: #292522; border: 1px solid #cfcac5;
                border-radius: 10px; font-size: 16px; font-weight: 700; padding: 11px 18px;
            }
            QPushButton#startButton:hover { border-color: #ff6a42; color: #e94e28; }
            QPushButton#applyButton {
                background: #ff5a2f; color: #ffffff; border: 1px solid #ff5a2f;
                border-radius: 10px; font-size: 16px; font-weight: 750; padding: 11px 18px;
            }
            QPushButton#applyButton:hover { background:#ed4c23; border-color:#ed4c23; color:white; }
            QPushButton#applyButton:disabled { background:#e6e2df; border-color:#e6e2df; color:#aaa5a0; }
            QPushButton#closeGameButton {
                background: #ffffff; color: #e74733; border: 1px solid #f16c58;
                border-radius: 10px; font-size: 16px; font-weight: 700; padding: 11px 18px;
            }
            QPushButton#closeGameButton:hover { background: #fff0ed; }
            QPushButton#closeGameButton:disabled { color:#bbb7b3; border-color:#ddd9d5; }
            QListWidget#consoleLogList { background: #ffffff; border: 1px solid #e8e5e1; }
            QFrame#consoleLogCard { background: #ffffff; border-bottom: 1px solid #eeeae6; }
            """
        )

    def _make_settings_page(
        self, title_text: str, subtitle_text: str, widgets: List[QWidget]
    ) -> QScrollArea:
        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 30)
        layout.setSpacing(18)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _build_dashboard_page(self) -> QWidget:
        content = QWidget()
        content.setObjectName("dashboardContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 26)
        layout.setSpacing(18)

        heading = QLabel("游戏控制")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)

        cards = QHBoxLayout()
        cards.setSpacing(18)
        game_card = QFrame()
        game_card.setObjectName("dashboardCard")
        game_layout = QVBoxLayout(game_card)
        game_layout.setContentsMargins(24, 22, 24, 22)
        game_layout.setSpacing(10)
        game_title = QLabel("游戏控制")
        game_title.setObjectName("cardTitle")
        caption = QLabel("剩余食物")
        caption.setObjectName("metricCaption")
        self.dashboard_remaining_label = QLabel("0")
        self.dashboard_remaining_label.setObjectName("remainingValue")
        game_layout.addWidget(game_title)
        game_layout.addWidget(caption)
        game_layout.addWidget(self.dashboard_remaining_label)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.game_minus_button = QPushButton("−1")
        self.game_plus_button = QPushButton("＋1")
        self.range_control_button = QPushButton("范围拾取：关闭")
        self.range_control_button.setObjectName("rangeControlButton")
        self.range_control_button.setCheckable(True)
        self.game_minus_button.clicked.connect(
            lambda: self.manual_delta_requested.emit(-self.manual_step_spin.value())
        )
        self.game_plus_button.clicked.connect(
            lambda: self.manual_delta_requested.emit(self.manual_step_spin.value())
        )
        self.range_control_button.clicked.connect(lambda: self.range_toggle_requested.emit())
        controls.addWidget(self.game_minus_button)
        controls.addWidget(self.game_plus_button)
        controls.addWidget(self.range_control_button, 1)
        game_layout.addLayout(controls)

        quick_toggles = QHBoxLayout()
        quick_toggles.setSpacing(10)
        self.sound_checkbox = QPushButton("游戏音效：开")
        self.sound_checkbox.setObjectName("toggleButton")
        self.sound_checkbox.setCheckable(True)
        self.sound_checkbox.setChecked(True)
        self.sound_checkbox.toggled.connect(self._sound_toggle_changed)
        self.gift_effect_toggle = QPushButton("礼物浮窗：开")
        self.gift_effect_toggle.setObjectName("toggleButton")
        self.gift_effect_toggle.setCheckable(True)
        self.gift_effect_toggle.setChecked(True)
        self.gift_effect_toggle.toggled.connect(self._gift_effect_toggle_changed)
        quick_toggles.addWidget(self.sound_checkbox)
        quick_toggles.addWidget(self.gift_effect_toggle)
        quick_toggles.addStretch(1)
        game_layout.addLayout(quick_toggles)

        display_card = QFrame()
        display_card.setObjectName("dashboardCard")
        display_layout = QVBoxLayout(display_card)
        display_layout.setContentsMargins(24, 22, 24, 22)
        display_layout.setSpacing(16)
        display_title = QLabel("展示框")
        display_title.setObjectName("cardTitle")
        toggle_row = QHBoxLayout()
        toggle_label = QLabel("显示已吃 / 剩余")
        toggle_label.setStyleSheet("font-size:17px; font-weight:700;")
        self.stats_toggle_button = QPushButton("显示")
        self.stats_toggle_button.setObjectName("toggleButton")
        self.stats_toggle_button.setCheckable(True)
        self.stats_toggle_button.toggled.connect(self._stats_toggle_changed)
        toggle_row.addWidget(toggle_label)
        toggle_row.addStretch()
        toggle_row.addWidget(self.stats_toggle_button)
        display_layout.addWidget(display_title)
        display_layout.addLayout(toggle_row)
        display_actions = QHBoxLayout()
        reset_position = QPushButton("重置位置")
        reset_scale = QPushButton("恢复默认大小")
        reset_position.clicked.connect(lambda: self.stats_reset_position_requested.emit())
        reset_scale.clicked.connect(lambda: self.stats_reset_scale_requested.emit())
        display_actions.addWidget(reset_position)
        display_actions.addWidget(reset_scale)
        display_layout.addLayout(display_actions)
        display_note = QLabel("展示框只显示文字；拖动文字移动，滚轮调整大小")
        display_note.setStyleSheet("color:#8b8783; font-size:13px;")
        display_note.setWordWrap(True)
        display_layout.addWidget(display_note)
        cards.addWidget(game_card, 1)
        cards.addWidget(display_card, 1)
        layout.addLayout(cards)

        log_card = QFrame()
        log_card.setObjectName("dashboardCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(20, 18, 20, 18)
        log_header = QHBoxLayout()
        log_title = QLabel("直播互动")
        log_title.setObjectName("cardTitle")
        self.log_count_label = QLabel("等待第一条互动")
        self.log_count_label.setStyleSheet("color:#999590; font-size:13px;")
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_logs)
        log_header.addWidget(log_title)
        log_header.addWidget(self.log_count_label)
        log_header.addStretch()
        log_header.addWidget(clear_button)
        self.console_log_list = QListWidget()
        self.console_log_list.setObjectName("consoleLogList")
        self.console_log_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.console_log_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.console_log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.console_log_list.setMinimumHeight(245)
        log_layout.addLayout(log_header)
        log_layout.addWidget(self.console_log_list, 1)
        layout.addWidget(log_card, 1)
        self._set_control_enabled(False)
        return content

    def _build_live_group(self) -> QGroupBox:
        group = QGroupBox("直播间连接")
        layout = QFormLayout(group)
        self.room_id_edit = QLineEdit()
        self.room_id_edit.setPlaceholderText("例如：21449083（直播间网址末尾数字）")
        self.room_id_edit.editingFinished.connect(self._auto_sync_gifts)
        self.sessdata_edit = QLineEdit()
        self.sessdata_edit.setEchoMode(QLineEdit.Password)
        self.sessdata_edit.setPlaceholderText("可留空；只粘贴 SESSDATA 的值")
        note = QLabel(
            "SESSDATA 非必需。留空仍能收弹幕和礼物，但用户名会脱敏、UID 可能为 0。"
            "请勿把配置文件发给他人。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #777771;")
        layout.addRow("直播间房间号", self.room_id_edit)
        layout.addRow("SESSDATA（可选）", self.sessdata_edit)
        layout.addRow("", note)
        return group

    def _build_asset_group(self) -> QGroupBox:
        group = QGroupBox("贴图素材")
        layout = QGridLayout(group)
        self.food_list = QListWidget()
        self.food_list.setMinimumHeight(110)
        self.food_list.setIconSize(QSize(48, 48))
        add_food = QPushButton("选择食物贴图（可多选）")
        remove_food = QPushButton("删除选中贴图")
        add_food.clicked.connect(self._choose_food_images)
        remove_food.clicked.connect(self._remove_food_images)
        self.food_preview = MediaPreview(126)
        self.food_list.currentItemChanged.connect(self._preview_food_item)

        self.consumer_edit = QLineEdit()
        self.consumer_edit.setReadOnly(True)
        choose_consumer = QPushButton("选择食用者贴图")
        clear_consumer = QPushButton("清空")
        choose_consumer.clicked.connect(self._choose_consumer_image)
        clear_consumer.clicked.connect(self._clear_consumer_image)
        self.consumer_preview = MediaPreview(126)

        food_preview_layout = QVBoxLayout()
        food_preview_layout.setContentsMargins(0, 0, 0, 0)
        food_preview_layout.addWidget(QLabel("所选食物预览"), 0, Qt.AlignCenter)
        food_preview_layout.addWidget(self.food_preview)
        consumer_preview_layout = QVBoxLayout()
        consumer_preview_layout.setContentsMargins(0, 0, 0, 0)
        consumer_preview_layout.addWidget(QLabel("食用者预览"), 0, Qt.AlignCenter)
        consumer_preview_layout.addWidget(self.consumer_preview)

        layout.addWidget(QLabel("食物贴图"), 0, 0, Qt.AlignTop)
        layout.addWidget(self.food_list, 0, 1, 1, 3)
        layout.addWidget(add_food, 1, 1)
        layout.addWidget(remove_food, 1, 2)
        layout.addLayout(food_preview_layout, 0, 4, 2, 1)
        layout.addWidget(QLabel("食用者贴图"), 2, 0)
        layout.addWidget(self.consumer_edit, 2, 1)
        layout.addWidget(choose_consumer, 2, 2)
        layout.addWidget(clear_consumer, 2, 3)
        layout.addLayout(consumer_preview_layout, 2, 4, 2, 1)
        fallback_note = QLabel("未选择贴图时食物默认为胡萝卜，食用者使用内置占位小人。")
        fallback_note.setStyleSheet("color: #777771;")
        layout.addWidget(fallback_note, 3, 1, 1, 3)
        layout.setColumnStretch(1, 1)
        return group

    def _build_template_group(self) -> QGroupBox:
        """主题模板：内置主题一键替换贴图，也允许保存用户自己的组合。"""
        group = QGroupBox("主题模板")
        layout = QVBoxLayout(group)
        intro = QLabel(
            "双击模板即可自动替换食物和食用者贴图；内置素材会复制到程序目录，重启后仍可使用。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#777771;")
        layout.addWidget(intro)

        self.template_list = QListWidget()
        self.template_list.setObjectName("templateList")
        self.template_list.setViewMode(QListView.IconMode)
        self.template_list.setFlow(QListView.LeftToRight)
        self.template_list.setWrapping(False)
        self.template_list.setMovement(QListView.Static)
        self.template_list.setResizeMode(QListView.Adjust)
        self.template_list.setIconSize(QSize(72, 72))
        self.template_list.setGridSize(QSize(164, 116))
        self.template_list.setMinimumHeight(132)
        self.template_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.template_list.itemDoubleClicked.connect(
            lambda _item: self._apply_selected_template()
        )
        layout.addWidget(self.template_list)

        buttons = QHBoxLayout()
        apply_button = QPushButton("应用选中模板")
        apply_button.setObjectName("accentButton")
        blank_button = QPushButton("新建空白模板")
        save_button = QPushButton("保存当前为模板")
        delete_button = QPushButton("删除自定义模板")
        apply_button.clicked.connect(self._apply_selected_template)
        blank_button.clicked.connect(self._new_blank_template)
        save_button.clicked.connect(self._save_current_template)
        delete_button.clicked.connect(self._delete_selected_template)
        buttons.addWidget(apply_button)
        buttons.addWidget(blank_button)
        buttons.addWidget(save_button)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.star_blessings_container = QFrame()
        blessings_layout = QVBoxLayout(self.star_blessings_container)
        blessings_layout.setContentsMargins(0, 4, 0, 0)
        blessings_layout.setSpacing(5)
        blessing_title = QLabel("星星收藏瓶祝福语（每行一条，投入星星时随机显示）")
        blessing_title.setStyleSheet("font-weight:700; color:#5d514c;")
        self.star_blessings_edit = QPlainTextEdit()
        self.star_blessings_edit.setPlaceholderText("例如：一切尽意,万事从欢")
        self.star_blessings_edit.setMinimumHeight(86)
        self.star_blessings_edit.setMaximumHeight(120)
        blessings_layout.addWidget(blessing_title)
        blessings_layout.addWidget(self.star_blessings_edit)
        layout.addWidget(self.star_blessings_container)
        self._refresh_template_list()
        self._update_star_blessings_visibility()
        return group

    def _refresh_template_list(self, select_key: str = "") -> None:
        if not hasattr(self, "template_list"):
            return
        self.template_list.clear()
        for template in builtin_templates():
            preview = template.get("consumer_image") or next(
                iter(template.get("food_images", [])), ""
            )
            item = QListWidgetItem(QIcon(load_pixmap(preview)), template["name"])
            item.setData(
                Qt.UserRole,
                {"kind": "builtin", "id": template["id"]},
            )
            item.setToolTip(template["description"] + "\n双击立即应用")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            self.template_list.addItem(item)
            if select_key == f"builtin:{template['id']}":
                self.template_list.setCurrentItem(item)

        for index, template in enumerate(self._custom_templates):
            preview = template.get("consumer_image") or next(
                iter(template.get("food_images", [])), ""
            )
            item = QListWidgetItem(
                QIcon(load_pixmap(preview)), f"自定义 · {template['name']}"
            )
            item.setData(Qt.UserRole, {"kind": "custom", "index": index})
            item.setToolTip("你保存的食物与食用者组合\n双击立即应用")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            self.template_list.addItem(item)
            if select_key == f"custom:{index}":
                self.template_list.setCurrentItem(item)

        if self.template_list.count() and self.template_list.currentRow() < 0:
            self.template_list.setCurrentRow(0)

    def _selected_template(self) -> Optional[Dict]:
        item = self.template_list.currentItem()
        payload = item.data(Qt.UserRole) if item else None
        if not isinstance(payload, dict):
            return None
        if payload.get("kind") == "builtin":
            template_id = str(payload.get("id", ""))
            return materialize_builtin_template(template_id, self._data_dir)
        if payload.get("kind") == "custom":
            index = int(payload.get("index", -1))
            if 0 <= index < len(self._custom_templates):
                return dict(self._custom_templates[index])
        return None

    def _apply_selected_template(self) -> None:
        template = self._selected_template()
        if template is None:
            QMessageBox.information(self, "请选择模板", "请先选择一个要应用的主题模板。")
            return
        food_images = [
            str(path)
            for path in template.get("food_images", [])
            if Path(str(path)).is_file()
        ]
        consumer_image = str(template.get("consumer_image", ""))
        if consumer_image and not Path(consumer_image).is_file():
            consumer_image = ""
        missing_count = len(template.get("food_images", [])) - len(food_images)
        if template.get("consumer_image") and not consumer_image:
            missing_count += 1
        self._replace_asset_paths(food_images, consumer_image)
        self._active_theme_id = str(
            template.get("id", "") or template.get("theme_id", "")
        )
        self._update_star_blessings_visibility()
        if missing_count:
            QMessageBox.warning(
                self,
                "部分素材已丢失",
                f"模板中有 {missing_count} 个素材文件不存在，已应用其余可用素材。",
            )

    def _replace_asset_paths(self, food_images: List[str], consumer_image: str) -> None:
        self.food_list.clear()
        for path in food_images:
            self._add_food_path(path)
        if self.food_list.count():
            self.food_list.setCurrentRow(0)
        else:
            self.food_preview.show_path("")
        self.consumer_edit.setText(consumer_image)
        self.consumer_preview.show_path(consumer_image)
        self._refresh_food_sound_choices()

    def _new_blank_template(self) -> None:
        """清空当前贴图，用户随后可添加素材并保存为自定义模板。"""
        self._replace_asset_paths([], "")
        self._active_theme_id = ""
        self._update_star_blessings_visibility()
        self.template_list.clearSelection()
        self.template_list.setCurrentRow(-1)

    def _update_star_blessings_visibility(self) -> None:
        """祝福语只属于星星收藏瓶，其他主题不占用设置页空间。"""
        if hasattr(self, "star_blessings_container"):
            self.star_blessings_container.setVisible(
                self._active_theme_id == "stars_jar"
            )

    def _mark_theme_as_customized(self) -> None:
        """手动更换贴图后不再视为正在使用完整的内置瓶子主题。"""
        if self._active_theme_id:
            self._active_theme_id = ""
            self._update_star_blessings_visibility()

    def _save_current_template(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "保存自定义模板",
            "模板名称：",
            QLineEdit.Normal,
        )
        name = name.strip()[:40]
        if not accepted:
            return
        if not name:
            QMessageBox.warning(self, "名称不能为空", "请输入一个模板名称。")
            return
        template = {
            "name": name,
            "food_images": [
                self._food_path(self.food_list.item(index))
                for index in range(self.food_list.count())
            ],
            "consumer_image": self.consumer_edit.text().strip(),
            "theme_id": self._active_theme_id,
        }
        existing_index = next(
            (
                index
                for index, item in enumerate(self._custom_templates)
                if item.get("name") == name
            ),
            -1,
        )
        if existing_index >= 0:
            self._custom_templates[existing_index] = template
            selected_key = f"custom:{existing_index}"
        else:
            self._custom_templates.append(template)
            selected_key = f"custom:{len(self._custom_templates) - 1}"
        self._refresh_template_list(selected_key)
        QMessageBox.information(
            self,
            "模板已保存",
            "自定义模板已加入列表；点击右上角“保存并应用”或“保存并圈选区域”后会写入配置文件。",
        )

    def _delete_selected_template(self) -> None:
        item = self.template_list.currentItem()
        payload = item.data(Qt.UserRole) if item else None
        if not isinstance(payload, dict) or payload.get("kind") != "custom":
            QMessageBox.information(self, "无法删除", "内置模板不会被删除，请选择一个自定义模板。")
            return
        index = int(payload.get("index", -1))
        if 0 <= index < len(self._custom_templates):
            self._custom_templates.pop(index)
            self._refresh_template_list()

    def _build_gameplay_group(self) -> QGroupBox:
        group = QGroupBox("游戏与范围拾取")
        layout = QGridLayout(group)
        self.initial_count_spin = self._spin(0, 100000)
        self.manual_step_spin = self._spin(1, 10000)
        self.manual_step_spin.valueChanged.connect(self._update_manual_button_text)
        self.food_size_spin = self._spin(24, 256, " px")
        self.consumer_size_spin = self._spin(60, 600, " px")
        self.food_order_combo = NoWheelComboBox()
        self.food_order_combo.addItem("随机选择贴图", "random")
        self.food_order_combo.addItem("按列表顺序循环", "sequential")
        self.range_hit_combo = NoWheelComboBox()
        self.range_hit_combo.addItem("食物碰到圆形范围就选中", "intersects")
        self.range_hit_combo.addItem("食物完整位于圆内才选中", "contains")
        self.range_radius_spin = self._spin(25, 1000, " px")
        self.range_pickup_limit_spin = self._spin(1, 10000, " 个")

        pairs = [
            ("初始食物数量", self.initial_count_spin),
            ("手动加减步长 N", self.manual_step_spin),
            ("食物显示尺寸", self.food_size_spin),
            ("食用者显示尺寸", self.consumer_size_spin),
            ("多食物贴图顺序", self.food_order_combo),
            ("单次范围最多抓取", self.range_pickup_limit_spin),
            ("圆形命中规则", self.range_hit_combo),
            ("按住食物时的圆形半径", self.range_radius_spin),
        ]
        for index, (label, widget) in enumerate(pairs):
            row, column = divmod(index, 2)
            layout.addWidget(QLabel(label), row, column * 2)
            layout.addWidget(widget, row, column * 2 + 1)
        scale_note = QLabel(
            "食物会从底部开始逐层自然堆高，数量足够时可堆满整个游戏区域；不会散布悬浮。"
        )
        scale_note.setWordWrap(True)
        scale_note.setStyleSheet("color: #27866a; font-weight: 600;")
        layout.addWidget(scale_note, 4, 0, 1, 4)
        note = QLabel(
            "范围模式中：按住食物或从空白处拉出圆形范围；命中数量超过上限时，优先抓取离圆心最近的食物。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #777771;")
        layout.addWidget(note, 5, 0, 1, 4)
        layout.addWidget(RangePickupDemo(group), 6, 0, 1, 4)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        return group

    def _build_sound_group(self) -> QGroupBox:
        """全局事件音效和每张食物贴图的独立吃掉音效。"""
        group = QGroupBox("音效设置与试听")
        layout = QGridLayout(group)
        self.sound_path_edits: Dict[str, QLineEdit] = {}
        for row, (event_name, label_text) in enumerate(SOUND_EVENTS):
            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.setPlaceholderText("使用内置默认音效")
            choose_button = QPushButton("选择音效")
            clear_button = QPushButton("恢复默认")
            preview_button = QPushButton("试听")
            choose_button.clicked.connect(
                lambda _checked=False, name=event_name: self._choose_sound_file(name)
            )
            clear_button.clicked.connect(
                lambda _checked=False, name=event_name: self._clear_sound_file(name)
            )
            preview_button.clicked.connect(
                lambda _checked=False, name=event_name: self._preview_sound(name)
            )
            self.sound_path_edits[event_name] = edit
            layout.addWidget(QLabel(label_text), row, 0)
            layout.addWidget(edit, row, 1)
            layout.addWidget(choose_button, row, 2)
            layout.addWidget(clear_button, row, 3)
            layout.addWidget(preview_button, row, 4)
        note = QLabel(
            "留空时使用程序内置的四种轻量音效；自定义音频建议使用 WAV 或 MP3，试听无需先保存。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#777771;")
        layout.addWidget(note, len(SOUND_EVENTS), 0, 1, 5)

        food_title_row = len(SOUND_EVENTS) + 1
        food_title = QLabel("不同食物的吃掉音效")
        food_title.setStyleSheet("font-size:17px; font-weight:800; margin-top:10px;")
        layout.addWidget(food_title, food_title_row, 0, 1, 5)
        self.food_sound_food_combo = NoWheelComboBox()
        self.food_sound_food_combo.setIconSize(QSize(34, 34))
        self.food_sound_food_combo.currentIndexChanged.connect(
            self._food_sound_selection_changed
        )
        self.food_sound_path_edit = QLineEdit()
        self.food_sound_path_edit.setReadOnly(True)
        self.food_sound_path_edit.setPlaceholderText("未单独设置，将使用上方“吃掉食物”音效")
        choose_food_sound = QPushButton("单独设置")
        clear_food_sound = QPushButton("清除单独设置")
        preview_food_sound = QPushButton("试听")
        choose_food_sound.clicked.connect(self._choose_food_specific_sound)
        clear_food_sound.clicked.connect(self._clear_food_specific_sound)
        preview_food_sound.clicked.connect(self._preview_food_specific_sound)
        layout.addWidget(QLabel("选择食物"), food_title_row + 1, 0)
        layout.addWidget(self.food_sound_food_combo, food_title_row + 1, 1)
        layout.addWidget(self.food_sound_path_edit, food_title_row + 2, 1)
        layout.addWidget(choose_food_sound, food_title_row + 2, 2)
        layout.addWidget(clear_food_sound, food_title_row + 2, 3)
        layout.addWidget(preview_food_sound, food_title_row + 2, 4)
        set_all_food_sounds = QPushButton("一键给所有食物设置")
        clear_all_food_sounds = QPushButton("清除全部单独音效")
        set_all_food_sounds.clicked.connect(self._set_all_food_sounds)
        clear_all_food_sounds.clicked.connect(self._clear_all_food_sounds)
        layout.addWidget(set_all_food_sounds, food_title_row + 3, 1, 1, 2)
        layout.addWidget(clear_all_food_sounds, food_title_row + 3, 3, 1, 2)
        layout.setColumnStretch(1, 1)
        return group

    def _choose_sound_file(self, event_name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择音效", "", AUDIO_FILTER)
        if path:
            self.sound_path_edits[event_name].setText(path)

    def _clear_sound_file(self, event_name: str) -> None:
        self.sound_path_edits[event_name].clear()

    def _sound_files_from_ui(self) -> Dict[str, str]:
        return {
            event_name: self.sound_path_edits[event_name].text().strip()
            for event_name, _label in SOUND_EVENTS
        }

    def _preview_sound(self, event_name: str) -> None:
        if self._sound_preview_player is not None:
            self._sound_preview_player.stop()
            self._sound_preview_player.deleteLater()
        self._sound_preview_player = GameSoundPlayer(
            True,
            self,
            self._sound_files_from_ui(),
        )
        self._sound_preview_player.play(event_name)

    def _food_sound_keys(self) -> List[str]:
        keys = [
            self._food_path(self.food_list.item(index))
            for index in range(self.food_list.count())
        ]
        return keys or ["__default__"]

    def _refresh_food_sound_choices(self) -> None:
        if not hasattr(self, "food_sound_food_combo"):
            return
        current = self.food_sound_food_combo.currentData()
        self.food_sound_food_combo.blockSignals(True)
        self.food_sound_food_combo.clear()
        keys = self._food_sound_keys()
        for key in keys:
            if key == "__default__":
                self.food_sound_food_combo.addItem("默认胡萝卜", key)
            else:
                pixmap = load_pixmap(key)
                self.food_sound_food_combo.addItem(QIcon(pixmap), Path(key).name, key)
                index = self.food_sound_food_combo.count() - 1
                self.food_sound_food_combo.setItemData(index, key, Qt.ToolTipRole)
        selected = self.food_sound_food_combo.findData(current)
        self.food_sound_food_combo.setCurrentIndex(max(0, selected))
        self.food_sound_food_combo.blockSignals(False)
        self._food_sound_selection_changed()

    def _food_sound_selection_changed(self, _index: int = -1) -> None:
        key = self.food_sound_food_combo.currentData()
        self.food_sound_path_edit.setText(self._food_sound_map.get(str(key), ""))

    def _choose_food_specific_sound(self) -> None:
        key = str(self.food_sound_food_combo.currentData() or "")
        if not key:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择该食物的吃掉音效", "", AUDIO_FILTER)
        if path:
            self._food_sound_map[key] = path
            self.food_sound_path_edit.setText(path)

    def _clear_food_specific_sound(self) -> None:
        key = str(self.food_sound_food_combo.currentData() or "")
        self._food_sound_map.pop(key, None)
        self.food_sound_path_edit.clear()

    def _set_all_food_sounds(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择所有食物共用的吃掉音效", "", AUDIO_FILTER)
        if not path:
            return
        for key in self._food_sound_keys():
            self._food_sound_map[key] = path
        self._food_sound_selection_changed()

    def _clear_all_food_sounds(self) -> None:
        self._food_sound_map.clear()
        self.food_sound_path_edit.clear()

    def _preview_food_specific_sound(self) -> None:
        key = str(self.food_sound_food_combo.currentData() or "")
        if self._sound_preview_player is not None:
            self._sound_preview_player.stop()
            self._sound_preview_player.deleteLater()
        self._sound_preview_player = GameSoundPlayer(
            True, self, self._sound_files_from_ui()
        )
        self._sound_preview_player.play_file(
            self._food_sound_map.get(key, ""), "eat"
        )

    def _build_danmaku_group(self) -> QGroupBox:
        group = QGroupBox("弹幕规则")
        layout = QVBoxLayout(group)
        options = QHBoxLayout()
        self.match_mode_combo = NoWheelComboBox()
        self.match_mode_combo.addItem("整条弹幕完全匹配", "exact")
        self.match_mode_combo.addItem("弹幕中包含触发词", "contains")
        self.case_checkbox = QCheckBox("区分大小写")
        self.cooldown_spin = NoWheelDoubleSpinBox()
        self.cooldown_spin.setRange(0, 3600)
        self.cooldown_spin.setDecimals(1)
        self.cooldown_spin.setSuffix(" 秒")
        options.addWidget(QLabel("匹配方式"))
        options.addWidget(self.match_mode_combo)
        options.addWidget(self.case_checkbox)
        options.addSpacing(20)
        options.addWidget(QLabel("同一用户弹幕触发间隔"))
        options.addWidget(self.cooldown_spin)
        options.addStretch()
        self.danmaku_table = RuleTable("触发词", "食物变化量（可为负）")
        layout.addLayout(options)
        layout.addWidget(self.danmaku_table)
        return group

    def _build_gift_group(self) -> QGroupBox:
        group = QGroupBox("礼物规则")
        layout = QVBoxLayout(group)
        sync_row = QHBoxLayout()
        self.sync_gifts_button = QPushButton("同步B站礼物")
        self.sync_gifts_button.setObjectName("accentButton")
        self.sync_gifts_button.clicked.connect(self._manual_sync_gifts)
        self.gift_sync_status = QLabel(
            f"已读取本地缓存 {len(self._gift_catalog)} 种礼物"
            if self._gift_catalog
            else "填写房间号后将自动同步礼物和图片"
        )
        self.gift_sync_status.setStyleSheet("color:#77736f;")
        sync_row.addWidget(self.sync_gifts_button)
        sync_row.addWidget(self.gift_sync_status, 1)
        layout.addLayout(sync_row)
        self.gift_food_table = GiftFoodRuleTable()
        self.gift_food_table.set_gift_catalog(self._gift_catalog)
        layout.addWidget(self._build_gift_rule_template_panel())
        operation_note = QLabel(
            "礼物名称可直接搜索或从带图标的列表选择。每种礼物可设置增加、减少、乘以、除以、"
            "清空或刮大风。"
            "连送数量会让规则连续执行；"
            "例如当前 10 个食物，礼物 ×2 连送 3 个，结果为 80。"
        )
        operation_note.setWordWrap(True)
        operation_note.setStyleSheet("color:#7c7773;")
        layout.addWidget(operation_note)
        layout.addWidget(self.gift_food_table)
        layout.addWidget(QLabel("礼物范围拾取：触发后自动开启对应秒数，多次触发会延长时间。"))
        self.gift_range_table = RuleTable(
            "礼物名称", "开启秒数", gift_picker=True
        )
        self.gift_range_table.set_gift_catalog(self._gift_catalog)
        layout.addWidget(self.gift_range_table)
        return group

    def _build_gift_rule_template_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("giftTemplatePanel")
        panel.setStyleSheet(
            "QFrame#giftTemplatePanel { background:#fff8f3; border:1px solid #ffd8c8;"
            " border-radius:12px; }"
        )
        layout = QGridLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(9)

        title = QLabel("礼物规则模板")
        title.setStyleSheet("font-size:17px; font-weight:800; color:#e95029;")
        note = QLabel(
            "每个模板是一整套玩法，同时保存下方所有礼物运算规则和范围拾取规则。"
            "应用另一个模板会整套替换当前规则；修改后可另存为任意多个自定义模板。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7c7773;")
        layout.addWidget(title, 0, 0)
        layout.addWidget(note, 0, 1, 1, 4)

        self.gift_rule_template_combo = NoWheelComboBox()
        self.gift_rule_template_combo.setMinimumWidth(280)
        self.gift_rule_template_combo.currentIndexChanged.connect(
            self._gift_rule_template_selection_changed
        )
        layout.addWidget(QLabel("整套玩法"), 1, 0)
        layout.addWidget(self.gift_rule_template_combo, 1, 1, 1, 4)

        self.gift_rule_template_summary = QLabel()
        self.gift_rule_template_summary.setWordWrap(True)
        self.gift_rule_template_summary.setStyleSheet(
            "color:#67615d; background:#ffffff; border:1px solid #f0ddd3;"
            " border-radius:8px; padding:8px 10px;"
        )
        layout.addWidget(self.gift_rule_template_summary, 2, 0, 1, 5)

        apply_button = QPushButton("应用整套模板")
        apply_button.setObjectName("accentButton")
        blank_button = QPushButton("新建空白模板")
        save_button = QPushButton("将当前规则另存为模板")
        delete_button = QPushButton("删除自定义模板")
        apply_button.clicked.connect(self._apply_gift_rule_template)
        blank_button.clicked.connect(self._new_blank_gift_rule_template)
        save_button.clicked.connect(self._save_gift_rule_template)
        delete_button.clicked.connect(self._delete_gift_rule_template)
        button_row = QHBoxLayout()
        button_row.addWidget(apply_button)
        button_row.addWidget(blank_button)
        button_row.addWidget(save_button)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        layout.addLayout(button_row, 3, 0, 1, 5)
        layout.setColumnStretch(1, 1)
        self._refresh_gift_rule_template_combo()
        return panel

    def _refresh_gift_rule_template_combo(self, select_key: str = "") -> None:
        if not hasattr(self, "gift_rule_template_combo"):
            return
        current = self.gift_rule_template_combo.currentData() or {}
        old_key = str(current.get("key", "")) if isinstance(current, dict) else ""
        target_key = select_key or old_key
        self.gift_rule_template_combo.clear()
        for template in GIFT_RULE_TEMPLATE_PRESETS:
            template_id = str(template["id"])
            payload = {"kind": "builtin", "id": template_id, "key": template_id}
            self.gift_rule_template_combo.addItem(
                f"内置 · {template['name']}", payload
            )
            index = self.gift_rule_template_combo.count() - 1
            self.gift_rule_template_combo.setItemData(
                index, str(template.get("description", "")), Qt.ToolTipRole
            )
            if target_key == template_id:
                self.gift_rule_template_combo.setCurrentIndex(index)
        for index, template in enumerate(self._gift_rule_templates):
            key = f"custom:{index}"
            self.gift_rule_template_combo.addItem(
                f"自定义 · {template['name']}",
                {"kind": "custom", "index": index, "key": key},
            )
            combo_index = self.gift_rule_template_combo.count() - 1
            self.gift_rule_template_combo.setItemData(
                combo_index, "恢复这套模板中保存的全部礼物与范围规则", Qt.ToolTipRole
            )
            if target_key == key:
                self.gift_rule_template_combo.setCurrentIndex(combo_index)
        self._gift_rule_template_selection_changed()

    def _selected_gift_rule_template(self) -> Optional[Dict]:
        payload = self.gift_rule_template_combo.currentData() or {}
        if payload.get("kind") == "custom":
            index = int(payload.get("index", -1))
            if 0 <= index < len(self._gift_rule_templates):
                return self._gift_rule_templates[index]
        elif payload.get("kind") == "builtin":
            template_id = str(payload.get("id", ""))
            return next(
                (
                    item
                    for item in GIFT_RULE_TEMPLATE_PRESETS
                    if str(item.get("id", "")) == template_id
                ),
                None,
            )
        return None

    def _gift_rule_template_selection_changed(self, _index: int = -1) -> None:
        if not hasattr(self, "gift_rule_template_summary"):
            return
        template = self._selected_gift_rule_template()
        if not isinstance(template, dict):
            self.gift_rule_template_summary.setText("请选择一套礼物规则模板。")
            return
        food_count = len(template.get("gift_food_rules", []))
        range_count = len(template.get("gift_range_rules", []))
        description = str(template.get("description", "")).strip()
        prefix = f"包含 {food_count} 条礼物运算、{range_count} 条范围拾取规则"
        self.gift_rule_template_summary.setText(
            f"{prefix} · {description}" if description else prefix
        )

    def _apply_gift_rule_template(self) -> None:
        template = self._selected_gift_rule_template()
        if not isinstance(template, dict):
            return
        self.gift_food_table.set_rows(template.get("gift_food_rules", []))
        self.gift_range_table.set_rows(
            template.get("gift_range_rules", []), "gift_name", "seconds"
        )
        self.gift_rule_template_summary.setText(
            "整套规则已载入下方表格；可继续逐条修改，完成后点击右上角“保存并应用”。"
        )

    def _new_blank_gift_rule_template(self) -> None:
        self.gift_food_table.set_rows([])
        self.gift_range_table.set_rows([], "gift_name", "seconds")

    def _save_gift_rule_template(self) -> None:
        try:
            food_rules = self.gift_food_table.get_rows()
            range_rules = self.gift_range_table.get_rows("gift_name", "seconds")
        except ValueError as error:
            QMessageBox.warning(self, "规则有误", str(error))
            return
        name, accepted = QInputDialog.getText(
            self, "保存整套礼物规则", "新模板名称：", QLineEdit.Normal
        )
        name = name.strip()[:40]
        if not accepted:
            return
        if not name:
            QMessageBox.warning(self, "名称不能为空", "请输入一个模板名称。")
            return
        template = {
            "name": name,
            "gift_food_rules": food_rules,
            "gift_range_rules": range_rules,
        }
        existing_index = next(
            (
                index
                for index, item in enumerate(self._gift_rule_templates)
                if item.get("name") == name
            ),
            -1,
        )
        if existing_index >= 0:
            self._gift_rule_templates[existing_index] = template
            select_key = f"custom:{existing_index}"
        else:
            self._gift_rule_templates.append(template)
            select_key = f"custom:{len(self._gift_rule_templates) - 1}"
        self._refresh_gift_rule_template_combo(select_key)

    def _delete_gift_rule_template(self) -> None:
        payload = self.gift_rule_template_combo.currentData() or {}
        if payload.get("kind") != "custom":
            QMessageBox.information(self, "无法删除", "内置礼物模板不会被删除。")
            return
        index = int(payload.get("index", -1))
        if 0 <= index < len(self._gift_rule_templates):
            self._gift_rule_templates.pop(index)
            self._refresh_gift_rule_template_combo()

    def _gift_effect_toggle_changed(self, visible: bool) -> None:
        self.gift_effect_toggle.setText(
            "礼物浮窗：开" if visible else "礼物浮窗：关"
        )

    def _sound_toggle_changed(self, enabled: bool) -> None:
        self.sound_checkbox.setText(
            "游戏音效：开" if enabled else "游戏音效：关"
        )

    def _manual_sync_gifts(self) -> None:
        self._start_gift_sync(force=True)

    def _auto_sync_gifts(self) -> None:
        self._start_gift_sync(force=False)

    def _start_gift_sync(self, force: bool) -> None:
        room_id = self.room_id_edit.text().strip()
        if not room_id or not room_id.isdigit() or int(room_id) <= 0:
            if force:
                self.gift_sync_status.setText("请先填写正确的直播间房间号")
                self.gift_sync_status.setStyleSheet("color:#c34b39;")
            return
        if self._gift_catalog_thread is not None and self._gift_catalog_thread.isRunning():
            return
        if not force and room_id == self._gift_sync_room:
            return
        self._gift_sync_room = room_id
        self.sync_gifts_button.setEnabled(False)
        self.gift_sync_status.setStyleSheet("color:#77736f;")
        self.gift_sync_status.setText("正在获取直播间礼物列表…")
        thread = GiftCatalogSyncThread(room_id, self)
        self._gift_catalog_thread = thread
        thread.progress.connect(self._gift_sync_progress)
        thread.catalog_ready.connect(self._gift_sync_ready)
        thread.failed.connect(self._gift_sync_failed)
        thread.finished.connect(self._gift_sync_finished)
        thread.start()

    def _gift_sync_progress(self, completed: int, total: int, message: str) -> None:
        self.gift_sync_status.setText(str(message))

    def _gift_sync_ready(self, gifts: List[Dict]) -> None:
        self._gift_catalog = list(gifts)
        self.gift_food_table.set_gift_catalog(self._gift_catalog)
        self.gift_range_table.set_gift_catalog(self._gift_catalog)
        with_icon = sum(bool(item.get("icon_path")) for item in gifts)
        self.gift_sync_status.setStyleSheet("color:#21863a; font-weight:650;")
        self.gift_sync_status.setText(
            f"同步完成：{len(gifts)} 种礼物，已缓存 {with_icon} 张图片"
        )

    def _gift_sync_failed(self, message: str) -> None:
        self._gift_sync_room = ""
        cached = len(self._gift_catalog)
        suffix = f"，继续使用本地缓存 {cached} 种" if cached else ""
        self.gift_sync_status.setStyleSheet("color:#c34b39;")
        self.gift_sync_status.setText(f"同步失败：{message}{suffix}")

    def _gift_sync_finished(self) -> None:
        self.sync_gifts_button.setEnabled(True)
        thread = self._gift_catalog_thread
        self._gift_catalog_thread = None
        if thread is not None:
            thread.deleteLater()

    @staticmethod
    def _spin(minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
        spin = EditableNumberInput()
        spin.setRange(minimum, maximum)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def _update_manual_button_text(self, value: int) -> None:
        if hasattr(self, "game_minus_button"):
            self.game_minus_button.setText(f"−{int(value)}")
            self.game_plus_button.setText(f"＋{int(value)}")

    def _stats_toggle_changed(self, visible: bool) -> None:
        self.stats_toggle_button.setText("已显示" if visible else "已隐藏")
        self._config["stats_visible"] = bool(visible)
        self.stats_visibility_requested.emit(bool(visible))

    def _set_control_enabled(self, running: bool) -> None:
        for widget in (
            self.game_minus_button,
            self.game_plus_button,
            self.range_control_button,
        ):
            widget.setEnabled(bool(running))

    def set_game_running(self, running: bool) -> None:
        self._game_running = bool(running)
        self._set_control_enabled(running)
        self.close_game_button.setEnabled(running)
        self.apply_button.setEnabled(running)
        self.start_button.setText("重新圈选区域" if running else "保存并圈选区域")
        if not running:
            self.set_range_state(False, 0)
            self.dashboard_remaining_label.setText("0")

    def set_connection_status(self, text: str, state: str = "info") -> None:
        colors = {
            "connected": ("#21863a", "#e2f7e6"),
            "reconnecting": ("#a56813", "#fff1d8"),
            "error": ("#cb3f4d", "#ffe8eb"),
            "offline": ("#77736f", "#f1efed"),
            "info": ("#64605c", "#f1efed"),
        }
        foreground, background = colors.get(state, colors["info"])
        self.connection_status_label.setText(f"●  {text}")
        self.connection_status_label.setStyleSheet(
            f"color:{foreground}; background:{background}; border-radius:12px; "
            "padding:9px 15px; font-weight:700;"
        )

    def set_license_status(self, status) -> None:
        """更新左下角授权信息；倒计时由本窗口每秒自行刷新。"""
        self._license_valid = bool(getattr(status, "valid", False))
        self._license_plan_label = str(getattr(status, "plan_label", "") or "")
        self._license_expires_at = int(getattr(status, "expires_at", 0) or 0)
        self._license_message = str(getattr(status, "message", "") or "")
        self._update_license_countdown()

    def _update_license_countdown(self) -> None:
        if not hasattr(self, "license_countdown_label"):
            return
        if self._license_valid and self._license_expires_at <= 0:
            self.license_countdown_label.setText("永久授权")
            self.license_countdown_label.setStyleSheet(
                "color:#21863a; font-size:15px; font-weight:850;"
            )
            self.license_expiry_label.setText("无需续期")
            self.license_activate_button.setText("重新激活")
            return

        remaining = self._license_expires_at - int(time.time())
        if self._license_valid and remaining > 0:
            days, remainder = divmod(remaining, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            if days:
                countdown = f"{days}天 {hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                countdown = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            self.license_countdown_label.setText(countdown)
            self.license_countdown_label.setStyleSheet(
                "color:#e95029; font-size:15px; font-weight:850;"
            )
            expiry_text = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(self._license_expires_at),
            )
            plan = f"{self._license_plan_label} · " if self._license_plan_label else ""
            self.license_expiry_label.setText(f"{plan}到期 {expiry_text}")
            self.license_activate_button.setText("重新激活")
            return

        self.license_countdown_label.setText("授权已到期" if self._license_expires_at else "尚未激活")
        self.license_countdown_label.setStyleSheet(
            "color:#c43f43; font-size:15px; font-weight:850;"
        )
        self.license_expiry_label.setText(
            getattr(self, "_license_message", "请粘贴新的授权密钥")
            or "请粘贴新的授权密钥"
        )
        self.license_activate_button.setText("立即激活")

    def set_game_counts(self, eaten: int, remaining: int) -> None:
        self.dashboard_remaining_label.setText(str(int(remaining)))

    def set_range_state(self, active: bool, remaining_seconds: int = 0) -> None:
        self.range_control_button.blockSignals(True)
        self.range_control_button.setChecked(bool(active))
        if active and remaining_seconds > 0:
            text = f"范围拾取：{int(remaining_seconds)}s"
        else:
            text = "范围拾取：开启" if active else "范围拾取：关闭"
        self.range_control_button.setText(text)
        self.range_control_button.blockSignals(False)

    def update_stats_preferences(self, preferences: dict) -> None:
        self._config.update(preferences)
        if "stats_visible" not in preferences:
            return
        visible = bool(preferences.get("stats_visible", True))
        self.stats_toggle_button.blockSignals(True)
        self.stats_toggle_button.setChecked(visible)
        self.stats_toggle_button.setText("已显示" if visible else "已隐藏")
        self.stats_toggle_button.blockSignals(False)

    def show_activity(self, text: str) -> None:
        """控制台只显示直播间弹幕加减与观众送礼。"""
        parts = str(text).split("\t")
        if len(parts) >= 4 and parts[0] == "gift":
            _, uname, gift_name, gift_num = parts[:4]
            self.add_log_event(
                "gift",
                f"{uname} 送出 {gift_name} ×{gift_num}",
                "礼物互动",
            )
            return
        if len(parts) >= 4 and parts[0] == "danmaku":
            _, uname, message, delta_text = parts[:4]
            try:
                delta = int(delta_text)
            except ValueError:
                return
            if delta > 0:
                self.add_log_event(
                    "feed", f"{uname} 投喂了 {delta} 个食物", f"弹幕：“{message}”"
                )
            elif delta < 0:
                self.add_log_event(
                    "decrease",
                    f"{uname} 触发减少 {abs(delta)} 个食物",
                    f"弹幕：“{message}”",
                )

    def add_log_event(self, event_type: str, title: str, detail: str = "") -> None:
        card = ConsoleLogCard(event_type, str(title), str(detail))
        item = QListWidgetItem()
        item.setSizeHint(QSize(620, 68))
        self.console_log_list.addItem(item)
        self.console_log_list.setItemWidget(item, card)
        while self.console_log_list.count() > 200:
            self.console_log_list.takeItem(0)
        self._log_count = self.console_log_list.count()
        self.log_count_label.setText(f"最近 {self._log_count} 条 · 可滚动查看")
        self.console_log_list.scrollToBottom()

    def clear_logs(self) -> None:
        self.console_log_list.clear()
        self._log_count = 0
        self.log_count_label.setText("等待第一条互动")

    def set_config(self, config: dict) -> None:
        config = normalize_config(config)
        self._config = dict(config)
        self._custom_templates = list(config.get("custom_templates", []))
        self._refresh_template_list()
        self._active_theme_id = str(config.get("active_theme_id", ""))
        self.star_blessings_edit.setPlainText(
            "\n".join(config.get("star_blessings", []))
        )
        self._update_star_blessings_visibility()
        self._gift_rule_templates = list(config.get("gift_rule_templates", []))
        self._refresh_gift_rule_template_combo()
        self.room_id_edit.setText(config["room_id"])
        self.sessdata_edit.setText(config["sessdata"])
        self.food_list.clear()
        for path in config["food_images"]:
            self._add_food_path(path)
        if self.food_list.count():
            self.food_list.setCurrentRow(0)
        else:
            self.food_preview.show_path("")
        self.consumer_edit.setText(config["consumer_image"])
        self.consumer_preview.show_path(config["consumer_image"])
        self.initial_count_spin.setValue(config["initial_food_count"])
        self.manual_step_spin.setValue(config["manual_step"])
        self.food_size_spin.setValue(config["food_size"])
        self.consumer_size_spin.setValue(config["consumer_size"])
        self.sound_checkbox.setChecked(config["sound_enabled"])
        for event_name, _label in SOUND_EVENTS:
            self.sound_path_edits[event_name].setText(
                config.get("sound_files", {}).get(event_name, "")
            )
        self._food_sound_map = dict(config.get("food_sound_files", {}))
        self._refresh_food_sound_choices()
        self._set_combo(self.food_order_combo, config["food_image_order"])
        self._set_combo(self.range_hit_combo, config["range_hit_mode"])
        self.range_radius_spin.setValue(config["range_radius"])
        self.range_pickup_limit_spin.setValue(config["range_pickup_limit"])
        self._set_combo(self.match_mode_combo, config["danmaku_match_mode"])
        self.case_checkbox.setChecked(config["danmaku_case_sensitive"])
        self.cooldown_spin.setValue(config["user_cooldown_seconds"])
        self.danmaku_table.set_rows(config["danmaku_rules"], "keyword", "delta")
        self.gift_food_table.set_rows(config["gift_food_rules"])
        self.gift_range_table.set_rows(config["gift_range_rules"], "gift_name", "seconds")
        self.gift_effect_toggle.blockSignals(True)
        self.gift_effect_toggle.setChecked(
            bool(config.get("gift_effect_overlay_enabled", True))
        )
        self.gift_effect_toggle.setText(
            "礼物浮窗：开"
            if config.get("gift_effect_overlay_enabled", True)
            else "礼物浮窗：关"
        )
        self.gift_effect_toggle.blockSignals(False)
        self.stats_toggle_button.blockSignals(True)
        self.stats_toggle_button.setChecked(config["stats_visible"])
        self.stats_toggle_button.setText("已显示" if config["stats_visible"] else "已隐藏")
        self.stats_toggle_button.blockSignals(False)
        self.game_minus_button.setText(f"−{config['manual_step']}")
        self.game_plus_button.setText(f"＋{config['manual_step']}")

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _choose_food_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择食物贴图", "", IMAGE_FILTER)
        existing = {
            self._food_path(self.food_list.item(i)) for i in range(self.food_list.count())
        }
        for path in paths:
            if path not in existing:
                self._add_food_path(path)
                existing.add(path)
        self._refresh_food_sound_choices()
        if paths:
            self._mark_theme_as_customized()
        if paths and self.food_list.count():
            last_path = paths[-1]
            for index in range(self.food_list.count()):
                if self._food_path(self.food_list.item(index)) == last_path:
                    self.food_list.setCurrentRow(index)
                    break

    def _remove_food_images(self) -> None:
        removed = bool(self.food_list.selectedItems())
        for item in self.food_list.selectedItems():
            self._food_sound_map.pop(self._food_path(item), None)
            self.food_list.takeItem(self.food_list.row(item))
        if not self.food_list.count():
            self.food_preview.show_path("")
        self._refresh_food_sound_choices()
        if removed:
            self._mark_theme_as_customized()

    def _choose_consumer_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择食用者贴图", "", IMAGE_FILTER)
        if path:
            self.consumer_edit.setText(path)
            self.consumer_preview.show_path(path)
            self._mark_theme_as_customized()

    def _clear_consumer_image(self) -> None:
        had_consumer = bool(self.consumer_edit.text().strip())
        self.consumer_edit.clear()
        self.consumer_preview.show_path("")
        if had_consumer:
            self._mark_theme_as_customized()

    def _add_food_path(self, path: str) -> None:
        pixmap = load_pixmap(path)
        item = QListWidgetItem(QIcon(pixmap), Path(path).name)
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        self.food_list.addItem(item)

    @staticmethod
    def _food_path(item: QListWidgetItem) -> str:
        return str(item.data(Qt.UserRole) or item.text())

    def _preview_food_item(self, current: QListWidgetItem, previous=None) -> None:
        self.food_preview.show_path(self._food_path(current) if current else "")

    def _collect_config(self) -> dict:
        return {
            "version": 2,
            "room_id": self.room_id_edit.text().strip(),
            "sessdata": self.sessdata_edit.text().strip(),
            "food_images": [
                self._food_path(self.food_list.item(i))
                for i in range(self.food_list.count())
            ],
            "consumer_image": self.consumer_edit.text().strip(),
            "active_theme_id": self._active_theme_id,
            "star_blessings": [
                line.strip()
                for line in self.star_blessings_edit.toPlainText().splitlines()
                if line.strip()
            ],
            "custom_templates": list(self._custom_templates),
            "initial_food_count": self.initial_count_spin.value(),
            "manual_step": self.manual_step_spin.value(),
            "food_size": self.food_size_spin.value(),
            "consumer_size": self.consumer_size_spin.value(),
            "sound_enabled": self.sound_checkbox.isChecked(),
            "sound_files": self._sound_files_from_ui(),
            "food_sound_files": dict(self._food_sound_map),
            "food_image_order": self.food_order_combo.currentData(),
            "food_layout_mode": "piles",
            "danmaku_match_mode": self.match_mode_combo.currentData(),
            "danmaku_case_sensitive": self.case_checkbox.isChecked(),
            "danmaku_rules": self.danmaku_table.get_rows("keyword", "delta"),
            "gift_food_rules": self.gift_food_table.get_rows(),
            "gift_range_rules": self.gift_range_table.get_rows("gift_name", "seconds"),
            "gift_rule_templates": list(self._gift_rule_templates),
            "gift_effect_overlay_enabled": self.gift_effect_toggle.isChecked(),
            "gift_effect_position_set": self._config.get(
                "gift_effect_position_set", False
            ),
            "gift_effect_x_ratio": self._config.get("gift_effect_x_ratio", 0.5),
            "gift_effect_y_ratio": self._config.get("gift_effect_y_ratio", 0.03),
            "range_hit_mode": self.range_hit_combo.currentData(),
            "range_radius": self.range_radius_spin.value(),
            "range_pickup_limit": self.range_pickup_limit_spin.value(),
            "user_cooldown_seconds": self.cooldown_spin.value(),
            "stats_visible": self.stats_toggle_button.isChecked(),
            "stats_scale": self._config.get("stats_scale", 1.0),
            "stats_x_ratio": self._config.get("stats_x_ratio", 0.03),
            "stats_y_ratio": self._config.get("stats_y_ratio", 0.03),
        }

    def _validated_config(self) -> Optional[dict]:
        room_id = self.room_id_edit.text().strip()
        if room_id and (not room_id.isdigit() or int(room_id) <= 0):
            QMessageBox.warning(self, "房间号有误", "直播间房间号应为正整数，或留空进行离线测试。")
            return None
        try:
            config = normalize_config(self._collect_config())
        except ValueError as error:
            QMessageBox.warning(self, "规则有误", str(error))
            return None

        missing = [path for path in config["food_images"] if not Path(path).is_file()]
        consumer = config["consumer_image"]
        if consumer and not Path(consumer).is_file():
            missing.append(consumer)
        missing.extend(
            path
            for path in config.get("sound_files", {}).values()
            if path and not Path(path).is_file()
        )
        missing.extend(
            path
            for path in config.get("food_sound_files", {}).values()
            if path and not Path(path).is_file()
        )
        if missing:
            QMessageBox.warning(
                self,
                "素材文件不存在",
                "以下贴图或音效无法读取，请重新选择：\n" + "\n".join(missing[:8]),
            )
            return None
        self._config = dict(config)
        return config

    def _submit(self) -> None:
        config = self._validated_config()
        if config is None:
            return
        self.start_game.emit(config)

    def _apply_current_game(self) -> None:
        config = self._validated_config()
        if config is None:
            return
        self.apply_config_requested.emit(config)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802（Qt 命名约定）
        self.quit_requested.emit()
        event.accept()
