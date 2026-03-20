"""API Tester Widget – manually call ESI endpoints for debugging."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_EXAMPLE_ENDPOINTS = [
    "/status/",
    "/characters/{character_id}/",
    "/characters/{character_id}/skills/",
    "/characters/{character_id}/skillqueue/",
    "/characters/{character_id}/wallet/",
    "/characters/{character_id}/assets/?page=1",
    "/characters/{character_id}/mail/",
    "/characters/{character_id}/contracts/?page=1",
    "/characters/{character_id}/industry/jobs/",
    "/characters/{character_id}/orders/",
    "/characters/{character_id}/fittings/",
    "/characters/{character_id}/blueprints/?page=1",
    "/characters/{character_id}/killmails/recent/?page=1",
    "/characters/{character_id}/planets/",
    "/characters/{character_id}/contacts/?page=1",
    "/characters/{character_id}/notifications/",
    "/characters/{character_id}/calendar/",
    "/characters/{character_id}/clones/",
    "/characters/{character_id}/implants/",
    "/characters/{character_id}/loyalty/points/",
    "/characters/{character_id}/attributes/",
    "/characters/{character_id}/standings/",
    "/characters/{character_id}/medals/",
    "/characters/{character_id}/agents_research/",
    "/universe/types/{type_id}/",
    "/universe/systems/{system_id}/",
    "/universe/stations/{station_id}/",
    "/markets/prices/",
    "/sovereignty/map/",
]


class APITesterWidget(QWidget):
    """Interactive ESI API tester for debugging."""

    _result_ready = Signal(str)

    def __init__(self, esi_client, token_manager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.esi = esi_client
        self.token_manager = token_manager
        self._current_character_id: int | None = None
        self._result_ready.connect(self._on_result)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("🔧 ESI API Tester")
        title.setProperty("cssClass", "widget-title")
        layout.addWidget(title)

        # Method + Endpoint row
        row1 = QHBoxLayout()

        self._method_combo = QComboBox()
        self._method_combo.addItems(["GET", "POST"])
        self._method_combo.setFixedWidth(80)
        row1.addWidget(self._method_combo)

        self._endpoint_input = QLineEdit()
        self._endpoint_input.setPlaceholderText("/characters/{character_id}/skills/")
        self._endpoint_input.returnPressed.connect(self._on_send)
        row1.addWidget(self._endpoint_input, stretch=1)

        self._send_btn = QPushButton("▶ Send")
        self._send_btn.setProperty("cssClass", "action")
        self._send_btn.clicked.connect(self._on_send)
        row1.addWidget(self._send_btn)

        clear_btn = QPushButton("✕ Clear")
        clear_btn.setProperty("cssClass", "danger")
        clear_btn.clicked.connect(self._on_clear)
        row1.addWidget(clear_btn)

        layout.addLayout(row1)

        # Examples dropdown
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Example:"))
        self._examples_combo = QComboBox()
        self._examples_combo.addItem("— Select Endpoint —")
        for ep in _EXAMPLE_ENDPOINTS:
            self._examples_combo.addItem(ep)
        self._examples_combo.currentTextChanged.connect(self._on_example_selected)
        row2.addWidget(self._examples_combo, stretch=1)

        self._auth_check = QComboBox()
        self._auth_check.addItems(["🔒 With Token", "🔓 Without Token"])
        self._auth_check.setFixedWidth(150)
        row2.addWidget(self._auth_check)

        layout.addLayout(row2)

        # POST body (only for POST)
        self._body_label = QLabel("POST Body (JSON):")
        self._body_label.setVisible(False)
        layout.addWidget(self._body_label)

        self._body_input = QPlainTextEdit()
        self._body_input.setMaximumHeight(100)
        self._body_input.setPlaceholderText('{"ids": [95465499]}')
        self._body_input.setVisible(False)
        layout.addWidget(self._body_input)

        self._method_combo.currentTextChanged.connect(self._on_method_changed)

        # Status
        self._status = QLabel("Ready")
        self._status.setProperty("cssClass", "hint")
        layout.addWidget(self._status)

        # Response area
        self._response = QPlainTextEdit()
        self._response.setReadOnly(True)
        self._response.setProperty("cssClass", "code")
        self._response.setPlaceholderText("Response will be displayed here…")
        mono = QFont("Consolas", 11)
        self._response.setFont(mono)
        layout.addWidget(self._response, stretch=1)

    def set_character_id(self, character_id: int | None) -> None:
        """Set the current character ID for token auth."""
        self._current_character_id = character_id

    def _on_method_changed(self, method: str) -> None:
        is_post = method == "POST"
        self._body_label.setVisible(is_post)
        self._body_input.setVisible(is_post)

    def _on_example_selected(self, text: str) -> None:
        if text.startswith("—"):
            return
        self._endpoint_input.setText(text)

    def _on_clear(self) -> None:
        self._response.clear()
        self._status.setText("Ready")

    def _on_send(self) -> None:
        endpoint = self._endpoint_input.text().strip()
        if not endpoint:
            self._status.setText("⚠ Please enter endpoint")
            return

        # Replace {character_id} placeholder
        if "{character_id}" in endpoint:
            if not self._current_character_id:
                self._status.setText("⚠ No character selected")
                return
            endpoint = endpoint.replace("{character_id}", str(self._current_character_id))

        method = self._method_combo.currentText()
        use_auth = self._auth_check.currentIndex() == 0

        self._send_btn.setEnabled(False)
        self._status.setText(f"⏳ {method} {endpoint} …")

        def _do_request() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                start = datetime.now(UTC)

                # Get token if needed
                token = None
                if use_auth and self._current_character_id:
                    token = loop.run_until_complete(
                        self.token_manager.get_valid_token(self._current_character_id)
                    )

                if method == "GET":
                    result = loop.run_until_complete(
                        self.esi.get(endpoint, token=token)
                    )
                else:
                    body_text = self._body_input.toPlainText().strip()
                    json_data = json.loads(body_text) if body_text else None
                    result = loop.run_until_complete(
                        self.esi.post(endpoint, token=token, json_data=json_data)
                    )

                elapsed = (datetime.now(UTC) - start).total_seconds()

                # Format response
                if isinstance(result, (dict, list)):
                    formatted = json.dumps(result, indent=2, ensure_ascii=False)
                else:
                    formatted = str(result)

                lines = formatted.count("\n") + 1
                size = len(formatted)
                header = (
                    f"// ✓ {method} {endpoint}\n"
                    f"// {elapsed:.2f}s | {lines} lines | {size:,} bytes\n"
                    f"// {datetime.now(UTC).strftime('%H:%M:%S UTC')}\n"
                    f"// {'🔒 Authenticated' if token else '🔓 No Auth'}\n\n"
                )
                self._result_ready.emit(header + formatted)

            except Exception as e:
                self._result_ready.emit(f"// ✗ ERROR: {e}\n\n{type(e).__name__}: {e}")
            finally:
                loop.close()

        thread = threading.Thread(target=_do_request, daemon=True, name="api-tester")
        thread.start()

    def _on_result(self, text: str) -> None:
        self._response.setPlainText(text)
        self._send_btn.setEnabled(True)
        if "✓" in text.split("\n")[0]:
            self._status.setText("✓ Successful")
        else:
            self._status.setText("✗ Error")
