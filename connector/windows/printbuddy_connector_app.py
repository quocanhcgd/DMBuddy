"""Windows desktop UI for the Printbuddy Connector.

The UI owns only the short-lived login/enrollment flow. The long-lived
Connector credential remains in the agent state file and is never displayed.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Any

import httpx
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from connector.printbuddy_connector import ConnectorAgent

APP_NAME = "Printbuddy Connector"
STATE_PATH = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Printbuddy" / "Connector" / "connector-state.json"
SETTINGS_PATH = STATE_PATH.with_name("ui-settings.json")


def _api_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        detail = data.get("detail", data.get("message")) if isinstance(data, dict) else None
        if isinstance(detail, list):
            return "; ".join(str(item.get("msg", item)) for item in detail)
        if detail:
            return str(detail)
    except (ValueError, TypeError):
        pass
    return f"Máy chủ trả về HTTP {response.status_code}."


class EnrollmentWorker(QThread):
    """Authenticate the user and create one one-time Connector enrollment."""

    completed = Signal(str, bool)
    requires_2fa = Signal(str, object)
    failed = Signal(str)

    def __init__(
        self,
        server_url: str,
        username: str,
        password: str,
        state_exists: bool,
        pre_auth_token: str | None = None,
        two_fa_code: str | None = None,
        two_fa_method: str = "totp",
    ) -> None:
        super().__init__()
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password
        self.state_exists = state_exists
        self.pre_auth_token = pre_auth_token
        self.two_fa_code = two_fa_code
        self.two_fa_method = two_fa_method

    def run(self) -> None:
        try:
            with httpx.Client(timeout=20) as client:
                if self.pre_auth_token:
                    response = client.post(
                        f"{self.server_url}/api/v1/auth/2fa/verify",
                        json={
                            "pre_auth_token": self.pre_auth_token,
                            "code": self.two_fa_code,
                            "method": self.two_fa_method,
                        },
                    )
                else:
                    response = client.post(
                        f"{self.server_url}/api/v1/auth/login",
                        json={"username": self.username, "password": self.password},
                    )
                if response.is_error:
                    raise RuntimeError(_api_error(response))
                login_data = response.json()
                if login_data.get("requires_2fa"):
                    self.requires_2fa.emit(
                        str(login_data.get("pre_auth_token", "")),
                        login_data.get("two_fa_methods") or ["totp"],
                    )
                    return
                access_token = login_data.get("access_token")
                if not access_token:
                    raise RuntimeError("Máy chủ không trả về access token.")

                # An existing state already contains the long-lived credential.
                # Do not create an unused enrollment or rotate connectors here.
                if self.state_exists:
                    self.completed.emit("", True)
                    return

                name = f"Windows Connector - {platform.node() or 'PC'}"
                response = client.post(
                    f"{self.server_url}/api/v1/connectors/enrollments",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"name": name[:100], "ttl_seconds": 600},
                )
                if response.is_error:
                    raise RuntimeError(_api_error(response))
                enrollment_code = response.json().get("enrollment_code")
                if not enrollment_code:
                    raise RuntimeError("Máy chủ không trả về enrollment code.")
                self.completed.emit(str(enrollment_code), False)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            self.failed.emit(str(exc))


class AgentLogHandler(logging.Handler):
    def __init__(self, signal: Signal) -> None:
        super().__init__()
        self.signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.signal.emit(self.format(record))
        except RuntimeError:
            pass


class AgentWorker(QThread):
    log_message = Signal(str)
    stopped = Signal()
    failed = Signal(str)

    def __init__(self, server_url: str, enrollment_code: str | None) -> None:
        super().__init__()
        self.server_url = server_url
        self.enrollment_code = enrollment_code
        self.stop_event = threading.Event()

    def run(self) -> None:
        logger = logging.getLogger("printbuddy.connector")
        handler = AgentLogHandler(self.log_message)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        try:
            agent = ConnectorAgent(self.server_url, STATE_PATH, self.enrollment_code, self.stop_event)
            import asyncio

            asyncio.run(agent.run())
        except Exception as exc:  # noqa: BLE001 - surface the safe exception text in the UI
            self.failed.emit(str(exc))
        finally:
            logger.removeHandler(handler)
            self.stopped.emit()

    def stop(self) -> None:
        self.stop_event.set()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.auth_worker: EnrollmentWorker | None = None
        self.agent_worker: AgentWorker | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(760, 600)
        self._build_ui()
        self._load_settings()
        self._refresh_state_hint()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(32, 28, 32, 28)
        root_layout.setSpacing(18)

        header = QHBoxLayout()
        badge = QLabel("PB")
        badge.setObjectName("brandBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(52, 52)
        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel("Kết nối máy in trong mạng riêng với máy chủ Printbuddy")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addWidget(badge)
        header.addSpacing(14)
        header.addLayout(title_box)
        header.addStretch()
        root_layout.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(22, 20, 22, 22)
        form.setVerticalSpacing(13)
        form.setHorizontalSpacing(18)

        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("https://printbuddy.example.com")
        self.server_input.setClearButtonEnabled(True)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Tên đăng nhập hoặc email")
        self.username_input.setClearButtonEnabled(True)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Mật khẩu chỉ dùng trong lần đăng nhập này")
        self.password_input.returnPressed.connect(self.connect)
        form.addRow("Máy chủ", self.server_input)
        form.addRow("Tài khoản", self.username_input)
        form.addRow("Mật khẩu", self.password_input)
        root_layout.addWidget(card)

        actions = QHBoxLayout()
        self.connect_button = QPushButton("Đăng nhập và kết nối")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self.connect)
        self.existing_button = QPushButton("Kết nối Connector hiện tại")
        self.existing_button.clicked.connect(self.connect_existing)
        self.stop_button = QPushButton("Dừng")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_agent)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.existing_button)
        actions.addStretch()
        actions.addWidget(self.stop_button)
        root_layout.addLayout(actions)

        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        root_layout.addWidget(self.status_label)

        log_label = QLabel("Hoạt động gần đây")
        log_label.setObjectName("sectionTitle")
        root_layout.addWidget(log_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        root_layout.addWidget(self.log_view, 1)

        self.setStyleSheet(
            """
            QWidget { background: #0f172a; color: #e5e7eb; font-size: 14px; }
            QMainWindow { background: #0b1120; }
            #brandBadge { background: #20c997; color: #06251d; border-radius: 14px; font-size: 20px; font-weight: 800; }
            #title { color: #f8fafc; font-size: 25px; font-weight: 700; }
            #subtitle { color: #94a3b8; font-size: 13px; }
            #card { background: #172033; border: 1px solid #263550; border-radius: 12px; }
            QLineEdit { background: #0d1628; border: 1px solid #334155; border-radius: 7px; padding: 10px 12px; color: #f8fafc; }
            QLineEdit:focus { border: 1px solid #20c997; }
            QPushButton { background: #24324a; border: 1px solid #3b4b66; border-radius: 7px; padding: 10px 15px; color: #e2e8f0; font-weight: 600; }
            QPushButton:hover { background: #30425f; }
            QPushButton:disabled { color: #64748b; background: #1a2538; }
            #primaryButton { background: #20c997; color: #06251d; border: 0; }
            #primaryButton:hover { background: #35dfaa; }
            #dangerButton { color: #fecaca; border-color: #7f1d1d; }
            #status { background: #132238; border: 1px solid #263550; border-radius: 7px; padding: 10px 12px; color: #a7f3d0; }
            #sectionTitle { color: #cbd5e1; font-weight: 700; }
            QPlainTextEdit { background: #090f1c; border: 1px solid #263550; border-radius: 8px; padding: 10px; color: #a7f3d0; font-family: Consolas, monospace; }
            """
        )

    def _load_settings(self) -> None:
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            data = {}
        self.server_input.setText(str(data.get("server_url", "")))
        self.username_input.setText(str(data.get("username", "")))

    def _save_settings(self) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(
                {"server_url": self.server_input.text().strip(), "username": self.username_input.text().strip()},
                indent=2,
            ),
            encoding="utf-8",
        )

    def _refresh_state_hint(self) -> None:
        if STATE_PATH.exists():
            self.existing_button.setEnabled(True)
            self.set_status("Đã tìm thấy Connector đã đăng ký trên máy này.", "ready")
        else:
            self.existing_button.setEnabled(False)
            self.set_status("Chưa đăng ký Connector. Đăng nhập để bắt đầu.", "ready")

    def set_status(self, message: str, state: str = "ready") -> None:
        colors = {"ready": "#a7f3d0", "busy": "#fde68a", "error": "#fca5a5", "online": "#86efac"}
        self.status_label.setStyleSheet(f"color: {colors.get(state, colors['ready'])};")
        self.status_label.setText(message)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def connect(self) -> None:
        server = self.server_input.text().strip().rstrip("/")
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not server.startswith(("http://", "https://")):
            self.set_status("Địa chỉ máy chủ phải bắt đầu bằng http:// hoặc https://.", "error")
            return
        if not username or not password:
            self.set_status("Vui lòng nhập tài khoản và mật khẩu.", "error")
            return
        self._save_settings()
        self._set_auth_busy(True)
        self.set_status("Đang đăng nhập và tạo liên kết Connector...", "busy")
        self.auth_worker = EnrollmentWorker(server, username, password, STATE_PATH.exists())
        self.auth_worker.completed.connect(self._enrollment_completed)
        self.auth_worker.requires_2fa.connect(self._two_factor_required)
        self.auth_worker.failed.connect(self._auth_failed)
        self.auth_worker.start()

    def _two_factor_required(self, pre_auth_token: str, methods: Any) -> None:
        method_list = [str(value) for value in methods] or ["totp"]
        method, ok = QInputDialog.getItem(self, "Xác thực hai bước", "Phương thức:", method_list, 0, False)
        if not ok:
            self._set_auth_busy(False)
            self.set_status("Đã hủy xác thực hai bước.", "error")
            return
        code, ok = QInputDialog.getText(self, "Xác thực hai bước", "Nhập mã xác thực:")
        if not ok or not code.strip():
            self._set_auth_busy(False)
            self.set_status("Đã hủy xác thực hai bước.", "error")
            return
        self.auth_worker = EnrollmentWorker(
            self.server_input.text().strip().rstrip("/"),
            self.username_input.text().strip(),
            "",
            STATE_PATH.exists(),
            pre_auth_token=pre_auth_token,
            two_fa_code=code.strip(),
            two_fa_method=method,
        )
        self.auth_worker.completed.connect(self._enrollment_completed)
        self.auth_worker.requires_2fa.connect(self._two_factor_required)
        self.auth_worker.failed.connect(self._auth_failed)
        self.auth_worker.start()

    def _enrollment_completed(self, enrollment_code: str, existing: bool) -> None:
        self.password_input.clear()
        self._set_auth_busy(False)
        self.append_log("Đăng nhập máy chủ thành công.")
        self._start_agent(None if existing else enrollment_code)

    def _auth_failed(self, message: str) -> None:
        self._set_auth_busy(False)
        self.set_status(f"Đăng nhập thất bại: {message}", "error")
        self.append_log(f"Lỗi xác thực: {message}")

    def _set_auth_busy(self, busy: bool) -> None:
        self.connect_button.setEnabled(not busy)
        self.server_input.setEnabled(not busy)
        self.username_input.setEnabled(not busy)
        self.password_input.setEnabled(not busy)

    def connect_existing(self) -> None:
        if not STATE_PATH.exists():
            self._refresh_state_hint()
            return
        if not self.server_input.text().strip():
            self.set_status("Nhập địa chỉ máy chủ trước khi kết nối.", "error")
            return
        self._start_agent(None)

    def _start_agent(self, enrollment_code: str | None) -> None:
        self.connect_button.setEnabled(False)
        self.existing_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.set_status("Đang kết nối đến máy chủ...", "busy")
        self.agent_worker = AgentWorker(self.server_input.text().strip().rstrip("/"), enrollment_code)
        self.agent_worker.log_message.connect(self.append_log)
        self.agent_worker.failed.connect(self._agent_failed)
        self.agent_worker.stopped.connect(self._agent_stopped)
        self.agent_worker.start()

    def _agent_failed(self, message: str) -> None:
        self.set_status(f"Connector gặp lỗi: {message}", "error")
        self.append_log(f"Lỗi Connector: {message}")

    def _agent_stopped(self) -> None:
        self.stop_button.setEnabled(False)
        self.connect_button.setEnabled(True)
        self._refresh_state_hint()
        if self.status_label.text().startswith("Đang kết nối"):
            self.set_status("Connector đã dừng.", "ready")

    def stop_agent(self) -> None:
        if self.agent_worker and self.agent_worker.isRunning():
            self.set_status("Đang dừng Connector...", "busy")
            self.agent_worker.stop()

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
        if self.agent_worker and self.agent_worker.isRunning():
            self.agent_worker.stop()
            self.agent_worker.wait(4000)
        event.accept()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if "--agent" in sys.argv:
        server_url = os.getenv("PRINTBUDDY_SERVER_URL")
        if not server_url:
            raise SystemExit("PRINTBUDDY_SERVER_URL is required")
        import asyncio

        asyncio.run(
            ConnectorAgent(
                server_url,
                STATE_PATH,
                enrollment_code=os.getenv("PRINTBUDDY_ENROLLMENT_CODE"),
            ).run()
        )
        return
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
