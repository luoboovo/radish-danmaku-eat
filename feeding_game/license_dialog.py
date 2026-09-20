"""软件激活窗口。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .licensing import LicenseStatus, machine_code, save_license_key, validate_license_key


class LicenseDialog(QDialog):
    def __init__(self, license_path: Path, status: LicenseStatus, parent=None) -> None:
        super().__init__(parent)
        self.license_path = Path(license_path)
        self.setWindowTitle("小萝卜吃吃吃 · 软件激活")
        self.setFixedSize(620, 430)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        title = QLabel("激活小萝卜吃吃吃")
        title.setStyleSheet("font-size:26px; font-weight:900; color:#202020;")
        subtitle = QLabel("复制本机机器码给授权方，收到密钥后粘贴到下方。密钥仅适用于本机。")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#76716d; font-size:14px;")
        machine_title = QLabel("本机机器码")
        machine_title.setStyleSheet("font-weight:800;")
        self.machine_label = QLabel(machine_code())
        self.machine_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.machine_label.setStyleSheet(
            "background:#f7f5f2; border:1px solid #ded9d3; border-radius:10px;"
            "padding:12px; font-family:Consolas; font-size:18px; font-weight:800;"
        )
        copy_button = QPushButton("复制机器码")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.machine_label.text())
        )
        machine_row = QHBoxLayout()
        machine_row.addWidget(self.machine_label, 1)
        machine_row.addWidget(copy_button)

        key_title = QLabel("授权密钥")
        key_title.setStyleSheet("font-weight:800;")
        self.key_edit = QPlainTextEdit()
        self.key_edit.setPlaceholderText("粘贴以 RDEC1. 开头的授权密钥")
        self.key_edit.setMinimumHeight(120)
        current_text = (
            f"当前授权：{status.plan_label}，有效期至 {status.expiry_text}"
            if status.valid
            else status.message
        )
        self.status_label = QLabel(current_text)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "color:#21863a; font-weight:700;"
            if status.valid
            else "color:#c54a3a; font-weight:700;"
        )

        activate = QPushButton("验证并激活")
        activate.setObjectName("activate")
        activate.clicked.connect(self._activate)
        exit_button = QPushButton("取消" if parent is not None else "退出")
        exit_button.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(exit_button)
        actions.addWidget(activate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(4)
        layout.addWidget(machine_title)
        layout.addLayout(machine_row)
        layout.addWidget(key_title)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.status_label)
        layout.addLayout(actions)
        self.setStyleSheet(
            "QDialog{background:#fffdfb;color:#262321;font-family:'Microsoft YaHei UI';font-size:15px;}"
            "QPlainTextEdit{background:white;border:1px solid #ddd7d1;border-radius:10px;padding:10px;}"
            "QPushButton{background:white;border:1px solid #d9d3cd;border-radius:9px;padding:10px 17px;font-weight:700;}"
            "QPushButton:hover{border-color:#ff7650;color:#ed522d;background:#fff5ef;}"
            "QPushButton#activate{background:#ff5a2f;color:white;border-color:#ff5a2f;}"
        )

    def _activate(self) -> None:
        key = self.key_edit.toPlainText().strip()
        status = validate_license_key(key)
        if not status.valid:
            self.status_label.setText(status.message)
            return
        try:
            save_license_key(self.license_path, status.key)
        except OSError as error:
            QMessageBox.critical(self, "保存失败", f"无法保存授权信息：{error}")
            return
        self.status_label.setStyleSheet("color:#21863a; font-weight:800;")
        self.status_label.setText(
            f"激活成功：{status.plan_label}授权，有效期至 {status.expiry_text}"
        )
        self.accept()
