"""PyMon application lifecycle and main window setup."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication, QDialog

from pymon.core.config import Config
from pymon.core.database import Database
from pymon.ui.dark_theme import apply_theme
from pymon.ui.main_window import MainWindow
from pymon.ui.setup_wizard import SetupWizard

logger = logging.getLogger(__name__)


class PyMonApp:
    """Main application controller managing lifecycle and dependencies."""

    def __init__(self, argv: list[str]) -> None:
        self.config = Config()
        self.qt_app = QApplication(argv)
        self.qt_app.setApplicationName("PyMon")
        self.qt_app.setApplicationVersion("0.1.0")
        self.qt_app.setOrganizationName("PyMon")

        # Apply global dark theme
        apply_theme(self.qt_app)

        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG if self.config.debug else logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        # Initialize database
        self.db = Database(self.config.db_path)

        # Main window
        self.main_window: MainWindow | None = None

        # Connect aboutToQuit for reliable cleanup
        self.qt_app.aboutToQuit.connect(self._on_quit)

    def run(self) -> int:
        """Start the application and enter the event loop."""
        logger.info("Starting PyMon v%s", self.qt_app.applicationVersion())

        self.db.initialize()

        # Show setup wizard on first run (no Client ID configured)
        if not self.config.client_id:
            logger.info("No Client ID configured – launching setup wizard")
            wizard = SetupWizard(self.config)
            if wizard.exec() != QDialog.DialogCode.Accepted:
                logger.info("Setup wizard cancelled by user")
                # Allow app to start without client_id – features will be limited
                if not self.config.client_id:
                    logger.warning("Continuing without Client ID – ESI features disabled")

        self.main_window = MainWindow(self.config, self.db)
        self.main_window.show()

        return self.qt_app.exec()

    def _on_quit(self) -> None:
        """Final cleanup when Qt event loop is about to exit."""
        logger.info("Application quitting")
        if self.main_window:
            self.main_window.shutdown()
