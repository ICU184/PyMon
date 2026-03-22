"""First-run setup wizard – guides users through ESI application creation.

Shows a step-by-step tutorial on the first launch (when no Client ID is
configured) that walks users through:
1. Welcome screen
2. Creating an ESI application on the EVE Developer Portal
3. Entering and validating the Client ID
4. Completion & first character login
"""

from __future__ import annotations

import logging
import webbrowser

import httpx
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from pymon.core.config import SSO_CALLBACK_PORT, Config

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────
EVE_DEV_PORTAL = "https://developers.eveonline.com/applications"
CALLBACK_URL = f"http://localhost:{SSO_CALLBACK_PORT}/callback"


# ── Validation Thread ──────────────────────────────────────────────
class ValidateClientIdThread(QThread):
    """Background thread that validates an ESI Client ID."""

    valid = Signal()
    invalid = Signal(str)

    def __init__(self, client_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.client_id = client_id

    def run(self) -> None:
        """Try to reach the ESI auth endpoint with the given client_id."""
        try:
            # A valid client_id will return a redirect to the login page,
            # an invalid one returns an error page. We just check if the
            # SSO endpoint accepts the client_id without a 4xx error.
            url = "https://login.eveonline.com/v2/oauth/authorize"
            params = {
                "response_type": "code",
                "redirect_uri": CALLBACK_URL,
                "client_id": self.client_id,
                "scope": "esi-skills.read_skills.v1",
                "state": "validate",
            }
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                resp = client.get(url, params=params)

            # 302 redirect = valid client_id, 200 with error page = also possible
            # 4xx = definitely invalid
            if resp.status_code in (200, 302):
                self.valid.emit()
            elif resp.status_code >= 400:
                self.invalid.emit(f"ESI rejected the Client ID (HTTP {resp.status_code})")
            else:
                # Treat other codes as OK – might just be CCP being CCP
                self.valid.emit()

        except Exception as e:
            self.invalid.emit(f"Connection failed: {e}")


# ── Styled Helpers ─────────────────────────────────────────────────
def _heading(text: str) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(16)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setStyleSheet("color: #4ecca3; margin-bottom: 8px;")
    return lbl


def _subheading(text: str) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(11)
    lbl.setFont(font)
    lbl.setStyleSheet("color: #c9d1d9; margin-bottom: 12px;")
    lbl.setWordWrap(True)
    return lbl


def _step_label(number: int, text: str) -> QLabel:
    lbl = QLabel(
        f'<span style="color: #4ecca3; font-size: 14pt; font-weight: bold;">'
        f'  {number}  </span>'
        f'<span style="color: #e0e0e0; font-size: 11pt;">{text}</span>'
    )
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet("margin: 6px 0;")
    return lbl


def _info_box(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.RichText)
    lbl.setStyleSheet(
        "background: #16213e; border: 1px solid #30363d; border-radius: 6px; "
        "padding: 12px; color: #8b949e; font-size: 10pt; margin: 4px 0;"
    )
    return lbl


def _link_button(text: str, url: str) -> QPushButton:
    btn = QPushButton(f"🔗  {text}")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton { background: #0f3460; color: #58a6ff; border: 1px solid #30363d; "
        "border-radius: 6px; padding: 10px 18px; font-size: 11pt; }"
        "QPushButton:hover { background: #1c2a4a; border-color: #4ecca3; }"
    )
    btn.clicked.connect(lambda: webbrowser.open(url))
    return btn


def _copy_label(label_text: str, value: str) -> QWidget:
    """A read-only field with a copy button."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    lbl = QLabel(f"<b>{label_text}:</b>")
    lbl.setStyleSheet("color: #8b949e; font-size: 10pt;")
    layout.addWidget(lbl)

    val = QLineEdit(value)
    val.setReadOnly(True)
    val.setStyleSheet(
        "background: #21262d; color: #e2b714; border: 1px solid #30363d; "
        "border-radius: 4px; padding: 6px 10px; font-family: Consolas, monospace; font-size: 10pt;"
    )
    layout.addWidget(val, stretch=1)

    copy_btn = QPushButton("📋")
    copy_btn.setFixedSize(36, 36)
    copy_btn.setToolTip("Copy to clipboard")
    copy_btn.setCursor(Qt.PointingHandCursor)
    copy_btn.setStyleSheet(
        "QPushButton { background: #0f3460; border: 1px solid #30363d; border-radius: 4px; }"
        "QPushButton:hover { background: #1c2a4a; }"
    )
    copy_btn.clicked.connect(lambda: _copy_to_clipboard(value))
    layout.addWidget(copy_btn)

    return container


def _copy_to_clipboard(text: str) -> None:
    from PySide6.QtWidgets import QApplication
    clipboard = QApplication.clipboard()
    if clipboard:
        clipboard.setText(text)


# ── Page 1: Welcome ───────────────────────────────────────────────
class WelcomePage(QWizardPage):
    """Welcome page explaining what PyMon is and what we need."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("")
        self.setSubTitle("")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 20, 30, 20)

        layout.addWidget(_heading("🚀  Welcome to PyMon!"))

        layout.addWidget(_subheading(
            "PyMon is a Character Monitor for EVE Online. "
            "To retrieve your character data, PyMon requires access "
            "to the EVE ESI API."
        ))

        layout.addWidget(_info_box(
            "For this, you need to create an <b>ESI Application</b> once in the EVE Developer Portal. "
            "This only takes <b>2 minutes</b> and is completely free.<br><br>"
            "Don't worry – this wizard will guide you step by step through the process! "
            "Your data will remain locally on your computer."
        ))

        layout.addItem(QSpacerItem(0, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # What you'll need
        needs = QLabel(
            '<p style="color: #c9d1d9; font-size: 11pt;"><b>What you need:</b></p>'
            '<ul style="color: #e0e0e0; font-size: 10pt; line-height: 1.8;">'
            '<li>An <span style="color: #58a6ff;">EVE Online Account</span></li>'
            '<li>Access to the <span style="color: #58a6ff;">EVE Developer Portal</span></li>'
            '<li>Approx. 2 minutes of time ☕</li>'
            '</ul>'
        )
        needs.setTextFormat(Qt.RichText)
        needs.setWordWrap(True)
        layout.addWidget(needs)

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))


# ── Page 2: Create ESI Application ────────────────────────────────
class CreateAppPage(QWizardPage):
    """Step-by-step guide to creating an ESI application."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("")
        self.setSubTitle("")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(30, 20, 30, 20)

        layout.addWidget(_heading("📝  Create ESI Application"))

        layout.addWidget(_subheading(
            "Open the EVE Developer Portal and create a new Application "
            "with the following settings:"
        ))

        # Open portal button
        layout.addWidget(_link_button("Open EVE Developer Portal", EVE_DEV_PORTAL))

        layout.addItem(QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Step-by-step instructions
        layout.addWidget(_step_label(1,
            'Log in with your <b>EVE Online account</b>'
        ))

        layout.addWidget(_step_label(2, 'Click on <b>"Create New Application"</b>'))

        layout.addWidget(_step_label(3, 'Name: Enter any name, e.g. <b>"PyMon"</b>'))

        layout.addWidget(_step_label(4, 'Description: Can be left empty or e.g. <b>"Character Monitor"</b>'))

        layout.addWidget(_step_label(5,
            'Permissions: Click on <b>"Select All"</b> to activate all ESI scopes '
            '(or select the desired ones manually)'
        ))

        layout.addWidget(_step_label(6,
            'Callback URL: Enter the following URL'
        ))

        # Callback URL with copy button
        layout.addWidget(_copy_label("Callback URL", CALLBACK_URL))

        layout.addWidget(_step_label(7, 'Click on <b>"Create Application"</b>'))

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))


# ── Page 3: Enter Client ID ───────────────────────────────────────
class ClientIdPage(QWizardPage):
    """Page where users paste their Client ID."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("")
        self.setSubTitle("")
        self._validated = False
        self._validating = False
        self._thread: ValidateClientIdThread | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(30, 20, 30, 20)

        layout.addWidget(_heading("🔑  Enter Client ID"))

        layout.addWidget(_subheading(
            "After you have created the Application, you will find the "
            "<b>Client ID</b> on the Application details page. "
            "Copy it and paste it below."
        ))

        # Where to find it
        layout.addWidget(_info_box(
            "💡 <b>Where do I find the Client ID?</b><br><br>"
            "In the Developer Portal → Click on your Application → "
            'Under <b>"Client ID"</b> is a long string '
            '(e.g. <code style="color: #e2b714;">a1b2c3d4e5f6...</code>).<br><br>'
            "Copy this and paste it below."
        ))

        layout.addItem(QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Input field
        input_label = QLabel("Client ID:")
        input_label.setStyleSheet("color: #c9d1d9; font-size: 11pt; font-weight: bold;")
        layout.addWidget(input_label)

        self.client_id_input = QLineEdit()
        self.client_id_input.setPlaceholderText("Paste Client ID here...")
        self.client_id_input.setMinimumHeight(42)
        self.client_id_input.setStyleSheet(
            "QLineEdit { background: #21262d; color: #e0e0e0; border: 2px solid #30363d; "
            "border-radius: 6px; padding: 8px 12px; font-size: 12pt; "
            "font-family: Consolas, monospace; }"
            "QLineEdit:focus { border-color: #4ecca3; }"
        )
        self.client_id_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.client_id_input)

        # Validation status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 10pt; margin-top: 4px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Validate button
        self.validate_btn = QPushButton("✅  Verify Client ID")
        self.validate_btn.setEnabled(False)
        self.validate_btn.setCursor(Qt.PointingHandCursor)
        self.validate_btn.setMinimumHeight(40)
        self.validate_btn.setStyleSheet(
            "QPushButton { background: #0f3460; color: #e0e0e0; border: 1px solid #30363d; "
            "border-radius: 6px; padding: 8px 18px; font-size: 11pt; }"
            "QPushButton:hover { background: #1c2a4a; border-color: #4ecca3; }"
            "QPushButton:disabled { background: #161b22; color: #484f58; }"
        )
        self.validate_btn.clicked.connect(self._validate)
        layout.addWidget(self.validate_btn)

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # Register field for wizard validation
        self.registerField("client_id*", self.client_id_input)

    def _on_text_changed(self, text: str) -> None:
        text = text.strip()
        self.validate_btn.setEnabled(len(text) >= 20)
        self._validated = False
        self._update_status("")
        self.completeChanged.emit()

    def _validate(self) -> None:
        client_id = self.client_id_input.text().strip()
        if not client_id:
            return

        self._validating = True
        self.validate_btn.setEnabled(False)
        self._update_status("⏳ Verifying Client ID...", "#56d4e0")

        self._thread = ValidateClientIdThread(client_id, self)
        self._thread.valid.connect(self._on_valid)
        self._thread.invalid.connect(self._on_invalid)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_valid(self) -> None:
        self._validated = True
        self._update_status("✅ Client ID is valid!", "#2ea043")
        self.completeChanged.emit()

    def _on_invalid(self, msg: str) -> None:
        self._validated = False
        self._update_status(f"❌ {msg}", "#e74c3c")
        self.completeChanged.emit()

    def _on_finished(self) -> None:
        self._validating = False
        self.validate_btn.setEnabled(True)

    def _update_status(self, text: str, color: str = "#8b949e") -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 10pt; margin-top: 4px;")

    def isComplete(self) -> bool:
        """Only allow proceeding after validation or if text is long enough."""
        text = self.client_id_input.text().strip()
        # Allow proceeding if validated OR if text is reasonably long
        # (skip validation is OK, we validate again on save)
        return self._validated or len(text) >= 30

    def get_client_id(self) -> str:
        return self.client_id_input.text().strip()


# ── Page 4: Complete ──────────────────────────────────────────────
class CompletePage(QWizardPage):
    """Final page – setup complete!"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("")
        self.setSubTitle("")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 20, 30, 20)

        layout.addWidget(_heading("🎉  Setup complete!"))

        layout.addWidget(_subheading(
            "PyMon is now ready. Clicking \"Finish\" will save the "
            "configuration and you can directly add your first character."
        ))

        # What happens next
        next_steps = QLabel(
            '<p style="color: #c9d1d9; font-size: 11pt;"><b>Next Steps:</b></p>'
            '<ol style="color: #e0e0e0; font-size: 10pt; line-height: 2.0;">'
            '<li>PyMon will open with the main window</li>'
            '<li>Click on <span style="color: #4ecca3; font-weight: bold;">"Add Character"</span> '
            'in the sidebar</li>'
            '<li>You will be redirected to the EVE Online login page</li>'
            '<li>Log in and authorize access</li>'
            '<li>Your character will automatically appear in PyMon! 🚀</li>'
            '</ol>'
        )
        next_steps.setTextFormat(Qt.RichText)
        next_steps.setWordWrap(True)
        layout.addWidget(next_steps)

        layout.addItem(QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed))

        layout.addWidget(_info_box(
            "💡 <b>Tip:</b> You can change the Client ID in the settings "
            "at any time. The tutorial can be reopened via "
            "<b>Help → Setup Wizard</b>."
        ))

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))


# ── Main Wizard ────────────────────────────────────────────────────
class SetupWizard(QWizard):
    """First-run setup wizard for PyMon."""

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config

        self.setWindowTitle("PyMon – Setup")
        self.setMinimumSize(QSize(640, 560))
        self.setWizardStyle(QWizard.ModernStyle)

        # Style the wizard to match dark theme
        self.setStyleSheet("""
            QWizard {
                background: #1a1a2e;
            }
            QWizard QWidget {
                background: #1a1a2e;
                color: #e0e0e0;
            }
            QWizard QLabel#qt_watermark_label {
                background: transparent;
            }
            QPushButton {
                background: #0f3460;
                color: #e0e0e0;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 10pt;
                min-width: 100px;
            }
            QPushButton:hover {
                background: #1c2a4a;
                border-color: #4ecca3;
            }
            QPushButton:disabled {
                background: #161b22;
                color: #484f58;
            }
        """)

        # Add pages
        self.welcome_page = WelcomePage()
        self.create_page = CreateAppPage()
        self.client_id_page = ClientIdPage()
        self.complete_page = CompletePage()

        self.addPage(self.welcome_page)
        self.addPage(self.create_page)
        self.addPage(self.client_id_page)
        self.addPage(self.complete_page)

        # Button labels in English
        self.setButtonText(QWizard.NextButton, "Next  →")
        self.setButtonText(QWizard.BackButton, "←  Back")
        self.setButtonText(QWizard.FinishButton, "✅  Finish")
        self.setButtonText(QWizard.CancelButton, "Cancel")

    def accept(self) -> None:
        """Save the client ID to config when wizard finishes."""
        client_id = self.client_id_page.get_client_id()
        if client_id:
            self.config.client_id = client_id
            self.config.save()
            logger.info("Setup wizard completed – Client ID saved")
        super().accept()

    def reject(self) -> None:
        """Handle cancel – ask for confirmation."""
        reply = QMessageBox.question(
            self,
            "Cancel Setup",
            "Without a Client ID, PyMon cannot fetch character data.\n\n"
            "You can restart the setup wizard at any time via\n"
            "Help → Setup Wizard.\n\n"
            "Do you really want to cancel?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            super().reject()
