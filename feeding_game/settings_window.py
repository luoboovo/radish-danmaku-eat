"""主设置界面。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPen, QPolygon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
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
from .media import load_pixmap, set_label_media
from .sound import GameSoundPlayer


IMAGE_FILTER = "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.svg);;所有文件 (*)"
AUDIO_FILTER = "音频文件 (*.wav *.mp3 *.ogg *.m4a *.aac *.flac);;所有文件 (*)"
SOUND_EVENTS = (
    ("add", "增加食物"),
    ("remove", "减少食物"),
    ("eat", "吃掉食物"),
    ("gift", "收到礼物"),
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


class RuleTable(QWidget):
    """两列规则表，第二列固定为整数。"""

    def __init__(self, first_title: str, second_title: str, parent=None) -> None:
        super().__init__(parent)
        self.first_title = first_title
        self.second_title = second_title
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([first_title, second_title])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(150)

        add_button = QPushButton("＋ 添加规则")
        remove_button = QPushButton("删除选中")
        add_button.clicked.connect(lambda: self.add_row("", 1))
        remove_button.clicked.connect(self.remove_selected)

        button_layout = QHBoxLayout()
        button_layout.addWidget(add_button)
        button_layout.addWidget(remove_button)
        button_layout.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(button_layout)

    def add_row(self, name: str, value: int) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(name)))
        self.table.setItem(row, 1, QTableWidgetItem(str(value)))

    def remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def set_rows(self, rows: List[Dict], name_key: str, value_key: str) -> None:
        self.table.setRowCount(0)
        for row in rows:
            self.add_row(str(row.get(name_key, "")), int(row.get(value_key, 1)))

    def get_rows(self, name_key: str, value_key: str) -> List[Dict]:
        rows: List[Dict] = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            try:
                value = int(value_item.text().strip()) if value_item else 0
            except ValueError as error:
                raise ValueError(f"{self.first_title}“{name}”的{self.second_title}必须是整数") from error
            rows.append({name_key: name, value_key: value})
        return rows


class GiftFoodRuleTable(QWidget):
    """礼物食物运算表：每条规则可选择加、减、乘、除。"""

    OPERATIONS = (
        ("增加", "add"),
        ("减少", "subtract"),
        ("乘以", "multiply"),
        ("除以", "divide"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["礼物名称", "运算方式", "数值 / 倍数"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(190)

        add_button = QPushButton("＋ 添加规则")
        remove_button = QPushButton("删除选中")
        add_button.clicked.connect(lambda: self.add_row("", "add", 1.0))
        remove_button.clicked.connect(self.remove_selected)
        actions = QHBoxLayout()
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(actions)

    def add_row(self, gift_name: str, operation: str, value: float) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(gift_name)))
        operation_combo = QComboBox()
        for label, data in self.OPERATIONS:
            operation_combo.addItem(label, data)
        index = operation_combo.findData(operation)
        operation_combo.setCurrentIndex(max(0, index))
        self.table.setCellWidget(row, 1, operation_combo)
        value_text = f"{float(value):g}"
        self.table.setItem(row, 2, QTableWidgetItem(value_text))

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
            )

    def get_rows(self) -> List[Dict]:
        result: List[Dict] = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 2)
            gift_name = name_item.text().strip() if name_item else ""
            if not gift_name:
                continue
            operation_combo = self.table.cellWidget(row, 1)
            operation = operation_combo.currentData() if operation_combo else "add"
            try:
                value = float(value_item.text().strip()) if value_item else 0.0
            except ValueError as error:
                raise ValueError(f"礼物“{gift_name}”的数值/倍数必须是数字") from error
            if value <= 0:
                raise ValueError(f"礼物“{gift_name}”的数值/倍数必须大于 0")
            if operation in {"multiply", "divide"} and value <= 1:
                raise ValueError(f"礼物“{gift_name}”的乘除倍数必须大于 1")
            result.append(
                {"gift_name": gift_name, "operation": operation, "value": value}
            )
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

    def __init__(self, config: dict) -> None:
        super().__init__()
        self._game_running = False
        self._log_count = 0
        self._sound_preview_player: Optional[GameSoundPlayer] = None
        self._config = normalize_config(config)
        self.setWindowTitle("萝卜弹幕吃吃吃 · 直播控制台")
        self.resize(1240, 820)
        self.setMinimumSize(1060, 680)
        self._build_ui()
        self.set_config(self._config)

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
        title = QLabel("萝卜弹幕吃吃吃")
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
        version = QLabel("萝卜弹幕吃吃吃  ·  控制台")
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

    def _build_gameplay_group(self) -> QGroupBox:
        group = QGroupBox("游戏与范围拾取")
        layout = QGridLayout(group)
        self.initial_count_spin = self._spin(0, 100000)
        self.manual_step_spin = self._spin(1, 10000)
        self.manual_step_spin.valueChanged.connect(self._update_manual_button_text)
        self.food_size_spin = self._spin(24, 256, " px")
        self.consumer_size_spin = self._spin(60, 600, " px")
        self.food_order_combo = QComboBox()
        self.food_order_combo.addItem("随机选择贴图", "random")
        self.food_order_combo.addItem("按列表顺序循环", "sequential")
        self.range_hit_combo = QComboBox()
        self.range_hit_combo.addItem("食物碰到圆形范围就选中", "intersects")
        self.range_hit_combo.addItem("食物完整位于圆内才选中", "contains")
        self.range_radius_spin = self._spin(25, 1000, " px")
        self.range_pickup_limit_spin = self._spin(1, 10000, " 个")
        self.sound_checkbox = QCheckBox("启用轻量提示音")

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
        layout.addWidget(QLabel("游戏音效"), 4, 0)
        layout.addWidget(self.sound_checkbox, 4, 1)
        scale_note = QLabel(
            "食物会从底部开始逐层自然堆高，数量足够时可堆满整个游戏区域；不会散布悬浮。"
        )
        scale_note.setWordWrap(True)
        scale_note.setStyleSheet("color: #27866a; font-weight: 600;")
        layout.addWidget(scale_note, 5, 0, 1, 4)
        note = QLabel(
            "范围模式中：按住食物或从空白处拉出圆形范围；命中数量超过上限时，优先抓取离圆心最近的食物。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #777771;")
        layout.addWidget(note, 6, 0, 1, 4)
        layout.addWidget(RangePickupDemo(group), 7, 0, 1, 4)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        return group

    def _build_sound_group(self) -> QGroupBox:
        """四类游戏事件可分别换成本地音频，并可在保存前试听。"""
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

    def _build_danmaku_group(self) -> QGroupBox:
        group = QGroupBox("弹幕规则")
        layout = QVBoxLayout(group)
        options = QHBoxLayout()
        self.match_mode_combo = QComboBox()
        self.match_mode_combo.addItem("整条弹幕完全匹配", "exact")
        self.match_mode_combo.addItem("弹幕中包含触发词", "contains")
        self.case_checkbox = QCheckBox("区分大小写")
        self.cooldown_spin = QDoubleSpinBox()
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
        operation_note = QLabel(
            "每种礼物可设置增加、减少、乘以或除以。连送数量会让规则连续执行；"
            "例如当前 10 个食物，礼物 ×2 连送 3 个，结果为 80。"
        )
        operation_note.setWordWrap(True)
        operation_note.setStyleSheet("color:#7c7773;")
        layout.addWidget(operation_note)
        self.gift_food_table = GiftFoodRuleTable()
        layout.addWidget(self.gift_food_table)
        layout.addWidget(QLabel("礼物范围拾取：触发后自动开启对应秒数，多次触发会延长时间。"))
        self.gift_range_table = RuleTable("礼物名称", "开启秒数")
        layout.addWidget(self.gift_range_table)
        return group

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
        if paths and self.food_list.count():
            last_path = paths[-1]
            for index in range(self.food_list.count()):
                if self._food_path(self.food_list.item(index)) == last_path:
                    self.food_list.setCurrentRow(index)
                    break

    def _remove_food_images(self) -> None:
        for item in self.food_list.selectedItems():
            self.food_list.takeItem(self.food_list.row(item))
        if not self.food_list.count():
            self.food_preview.show_path("")

    def _choose_consumer_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择食用者贴图", "", IMAGE_FILTER)
        if path:
            self.consumer_edit.setText(path)
            self.consumer_preview.show_path(path)

    def _clear_consumer_image(self) -> None:
        self.consumer_edit.clear()
        self.consumer_preview.show_path("")

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
            "initial_food_count": self.initial_count_spin.value(),
            "manual_step": self.manual_step_spin.value(),
            "food_size": self.food_size_spin.value(),
            "consumer_size": self.consumer_size_spin.value(),
            "sound_enabled": self.sound_checkbox.isChecked(),
            "sound_files": self._sound_files_from_ui(),
            "food_image_order": self.food_order_combo.currentData(),
            "food_layout_mode": "piles",
            "danmaku_match_mode": self.match_mode_combo.currentData(),
            "danmaku_case_sensitive": self.case_checkbox.isChecked(),
            "danmaku_rules": self.danmaku_table.get_rows("keyword", "delta"),
            "gift_food_rules": self.gift_food_table.get_rows(),
            "gift_range_rules": self.gift_range_table.get_rows("gift_name", "seconds"),
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
