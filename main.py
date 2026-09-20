"""程序入口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Qt 5 在部分含中文用户名的 Windows 环境中可能把默认插件路径错误转成“??”。
# 在导入 QtCore/QtWidgets 前显式提供真实平台插件目录，避免 QApplication 启动卡住。
import PyQt5

_qt_plugins = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins"
_qt_platforms = _qt_plugins / "platforms"
if _qt_plugins.is_dir():
    # GIF、SVG 等图片格式插件位于 imageformats 子目录，不能只设置 platforms。
    os.environ.setdefault("QT_PLUGIN_PATH", str(_qt_plugins))
if _qt_platforms.is_dir():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_qt_platforms))
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PyQt5.QtCore import QObject, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from feeding_game.bili_listener import BiliLiveThread
from feeding_game.config import load_config, save_config
from feeding_game.game_window import GameWindow
from feeding_game.license_dialog import LicenseDialog
from feeding_game.licensing import load_saved_license
from feeding_game.region_selector import RegionSelector
from feeding_game.settings_window import SettingsWindow


# 普通源码运行时读取项目目录；打包为单文件 EXE 后则把配置保存在 EXE 旁边，
# 避免 PyInstaller 临时解压目录被清理后丢失设置。
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CONFIG_PATH = BASE_DIR / "config.json"
LICENSE_PATH = BASE_DIR / "license.json"


class AppController(QObject):
    """负责在设置页、游戏页和直播监听线程之间切换。"""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.config = load_config(CONFIG_PATH)
        self.settings_window = SettingsWindow(self.config, BASE_DIR)
        self.settings_window.start_game.connect(self.start_game)
        self.settings_window.apply_config_requested.connect(
            self.apply_current_config
        )
        self.settings_window.quit_requested.connect(self.app.quit)
        self.settings_window.manual_delta_requested.connect(self._manual_delta)
        self.settings_window.range_toggle_requested.connect(self._toggle_range)
        self.settings_window.stats_visibility_requested.connect(self._set_stats_visible)
        self.settings_window.stats_reset_position_requested.connect(
            self._reset_stats_position
        )
        self.settings_window.stats_reset_scale_requested.connect(self._reset_stats_scale)
        self.settings_window.close_game_requested.connect(self.close_game)
        self.settings_window.license_activation_requested.connect(
            self._show_license_dialog
        )
        self.game_window: Optional[GameWindow] = None
        self.region_selector: Optional[RegionSelector] = None
        self.listener: Optional[BiliLiveThread] = None
        self._pending_game_counts: Optional[tuple[int, int]] = None
        # 限时授权不仅在启动时检查。程序长时间开着跨过到期点时，
        # 最迟一分钟内也会停止使用，避免必须重启后才发现已过期。
        self.license_timer = QTimer(self)
        self.license_timer.setInterval(60_000)
        self.license_timer.timeout.connect(self._check_runtime_license)
        self.license_timer.start()
        self.settings_window.set_license_status(load_saved_license(LICENSE_PATH))
        self.app.aboutToQuit.connect(self.shutdown)

    def show(self) -> None:
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def start_game(self, new_config: dict) -> None:
        self.config = save_config(CONFIG_PATH, new_config)
        # 先圈选区域；确认前保留正在运行的旧游戏，避免误操作导致直播中断。
        self._pending_game_counts = (
            (self.game_window.food_count, self.game_window.eaten_count)
            if self.game_window is not None
            else None
        )
        if self.region_selector is not None:
            self.region_selector.blockSignals(True)
            self.region_selector.close()
            self.region_selector.deleteLater()
        self.region_selector = RegionSelector()
        self.region_selector.region_selected.connect(self._launch_game_in_region)
        self.region_selector.cancelled.connect(self._region_selection_cancelled)
        self.region_selector.show()
        self.region_selector.raise_()

    def _launch_game_in_region(self, geometry) -> None:
        preserved_counts = self._pending_game_counts
        self._pending_game_counts = None
        if self.region_selector is not None:
            self.region_selector.deleteLater()
            self.region_selector = None
        self._dispose_game_window()

        game_config = dict(self.config)
        if preserved_counts is not None:
            game_config["initial_food_count"] = preserved_counts[0]
        self.game_window = GameWindow(game_config, geometry)
        if preserved_counts is not None:
            self.game_window.eaten_count = preserved_counts[1]
            self.game_window._update_count_display()
        self.game_window.quit_requested.connect(self._game_window_closed)
        self.game_window.food_count_changed.connect(self.settings_window.set_game_counts)
        self.game_window.range_state_changed.connect(self.settings_window.set_range_state)
        self.game_window.stats_preferences_changed.connect(
            self._save_stats_preferences
        )
        self.game_window.show()
        self.game_window.raise_()
        self.settings_window.set_game_running(True)
        self.settings_window.set_game_counts(
            self.game_window.eaten_count, self.game_window.food_count
        )
        self.settings_window.update_stats_preferences(
            {
                "stats_visible": self.config.get("stats_visible", True),
                "stats_scale": self.config.get("stats_scale", 1.0),
                "stats_x_ratio": self.config.get("stats_x_ratio", 0.03),
                "stats_y_ratio": self.config.get("stats_y_ratio", 0.03),
            }
        )

        self._start_listener()

    def _start_listener(self) -> None:
        """按当前配置启动直播监听；运行中应用规则时也复用这里。"""
        if self.game_window is None:
            return
        self.listener = BiliLiveThread(self.config)
        self.listener.status_changed.connect(self.game_window.set_connection_status)
        self.listener.status_changed.connect(self.settings_window.set_connection_status)
        self.listener.food_delta.connect(self.game_window.apply_external_delta)
        self.listener.food_operation.connect(self.game_window.apply_gift_operation)
        self.listener.range_triggered.connect(self.game_window.trigger_timed_range)
        self.listener.gift_effect.connect(self.game_window.show_gift_effect)
        self.listener.activity.connect(self.game_window.show_activity)
        self.listener.activity.connect(self.settings_window.show_activity)
        self.listener.start()

    def apply_current_config(self, new_config: dict) -> None:
        """保存设置，并在不重开本局的情况下立即更新游戏和直播规则。"""
        self.config = save_config(CONFIG_PATH, new_config)
        if self.game_window is None:
            self.settings_window.set_config(self.config)
            return

        self.game_window.apply_runtime_config(self.config)
        self.settings_window.set_config(self.config)
        # 房间号、登录凭据、弹幕与礼物规则都由监听线程持有，需重新连接后生效。
        self._stop_listener()
        self.settings_window.set_connection_status("配置已应用，正在重新连接…", "info")
        self._start_listener()

    def _manual_delta(self, delta: int) -> None:
        if self.game_window is not None:
            self.game_window.change_food_count(int(delta), "手动操作")

    def _toggle_range(self) -> None:
        if self.game_window is not None:
            self.game_window.toggle_manual_range()

    def _set_stats_visible(self, visible: bool) -> None:
        self.config["stats_visible"] = bool(visible)
        if self.game_window is not None:
            self.game_window.set_stats_visible(visible)

    def _reset_stats_position(self) -> None:
        if self.game_window is not None:
            self.game_window.reset_stats_position()

    def _reset_stats_scale(self) -> None:
        if self.game_window is not None:
            self.game_window.reset_stats_scale()

    def _save_stats_preferences(self, preferences: dict) -> None:
        self.config.update(preferences)
        self.config = save_config(CONFIG_PATH, self.config)
        self.settings_window.update_stats_preferences(preferences)

    def close_game(self) -> None:
        self._pending_game_counts = None
        self._dispose_game_window()
        self.settings_window.set_game_running(False)
        self.settings_window.set_connection_status("游戏未启动", "offline")

    def _region_selection_cancelled(self) -> None:
        self._pending_game_counts = None
        if self.region_selector is not None:
            self.region_selector.deleteLater()
            self.region_selector = None

    def return_to_settings(self) -> None:
        self._dispose_game_window()
        self.settings_window.set_config(self.config)
        self.show()

    def _game_window_closed(self) -> None:
        """游戏窗口关闭后只停止直播监听，设置窗口继续保留。"""
        self._stop_listener()
        if self.game_window is not None:
            self.game_window.deleteLater()
            self.game_window = None
        self.settings_window.set_game_running(False)
        self.settings_window.set_connection_status("游戏未启动", "offline")

    def _dispose_game_window(self) -> None:
        self._stop_listener()
        if self.game_window is None:
            return
        self.game_window.blockSignals(True)
        self.game_window.close()
        self.game_window.deleteLater()
        self.game_window = None

    def _stop_listener(self) -> None:
        if self.listener is None:
            return
        self.listener.request_stop()
        self.listener.wait(3000)
        self.listener.deleteLater()
        self.listener = None

    def _check_runtime_license(self) -> None:
        status = load_saved_license(LICENSE_PATH)
        self.settings_window.set_license_status(status)
        if status.valid:
            return
        self.license_timer.stop()
        self._dispose_game_window()
        QMessageBox.critical(
            self.settings_window,
            "授权已失效",
            f"{status.message}\n\n请联系授权方获取新的密钥。",
        )
        self.app.quit()

    def _show_license_dialog(self) -> None:
        """控制台内随时重新激活，成功后立即刷新倒计时。"""
        current_status = load_saved_license(LICENSE_PATH)
        dialog = LicenseDialog(
            LICENSE_PATH,
            current_status,
            self.settings_window,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        refreshed_status = load_saved_license(LICENSE_PATH)
        self.settings_window.set_license_status(refreshed_status)
        if refreshed_status.valid and not self.license_timer.isActive():
            self.license_timer.start()

    def shutdown(self) -> None:
        self._stop_listener()
        if self.region_selector is not None:
            self.region_selector.blockSignals(True)
            self.region_selector.close()
        if self.game_window is not None:
            self.game_window.blockSignals(True)
            self.game_window.close()


def main() -> int:
    # 在创建 QApplication 前开启 Qt 高 DPI 支持，Windows 100%～300% 缩放下
    # 坐标、字体和高清贴图都会跟随当前显示器自动换算。
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("小萝卜吃吃吃")
    app.setOrganizationName("RadishDanmakuEat")
    icon_path = RESOURCE_DIR / "cake.svg"
    if icon_path.is_file():
        # QApplication 全局图标会同时应用到设置、圈选和透明游戏窗口。
        app.setWindowIcon(QIcon(str(icon_path)))
    app_font = QFont("Microsoft YaHei UI", 11)
    app_font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(app_font)
    app.setQuitOnLastWindowClosed(False)
    license_status = load_saved_license(LICENSE_PATH)
    if not license_status.valid:
        activation = LicenseDialog(LICENSE_PATH, license_status)
        if activation.exec_() != QDialog.Accepted:
            return 0
    controller = AppController(app)
    controller.show()
    # controller 必须保持引用，否则可能被 Python 垃圾回收。
    app.controller = controller  # type: ignore[attr-defined]
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
