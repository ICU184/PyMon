"""Auto-update checker – polls GitHub Releases for new versions.

Compares the current version against the latest GitHub release tag
and shows a notification if an update is available.
"""

from __future__ import annotations

import logging
import re
import webbrowser

import httpx
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

# GitHub repository for release checks
GITHUB_REPO = "ICU184/PyMon"
CURRENT_VERSION = "1.0.0"


def parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v0.2.0' or '0.2.0' into (0, 2, 0)."""
    m = re.search(r"(\d+(?:\.\d+)+)", tag)
    if not m:
        return (0,)
    return tuple(int(x) for x in m.group(1).split("."))


class UpdateCheckThread(QThread):
    """Background thread that checks for updates."""

    update_available = Signal(str, str)  # (latest_version, download_url)
    no_update = Signal()
    check_failed = Signal(str)  # error message

    def __init__(
        self,
        repo: str = GITHUB_REPO,
        current: str = CURRENT_VERSION,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repo = repo
        self.current = current

    def run(self) -> None:
        try:
            url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            with httpx.Client(timeout=15) as client:
                resp = client.get(url, headers={"Accept": "application/vnd.github.v3+json"})

            if resp.status_code == 404:
                # No releases yet
                self.no_update.emit()
                return

            resp.raise_for_status()
            data = resp.json()

            latest_tag = data.get("tag_name", "")
            latest_ver = parse_version(latest_tag)
            current_ver = parse_version(self.current)

            if latest_ver > current_ver:
                dl_url = data.get("html_url", f"https://github.com/{self.repo}/releases")
                self.update_available.emit(latest_tag, dl_url)
            else:
                self.no_update.emit()

        except Exception as e:
            logger.debug("Update check failed: %s", e)
            self.check_failed.emit(str(e))


class UpdateDialog(QDialog):
    """Dialog showing an available update."""

    def __init__(
        self,
        latest_version: str,
        download_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.download_url = download_url
        self.setWindowTitle("Update Available")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            f"<h3>🆕 New Version Available</h3>"
            f"<p>Current Version: <b>v{CURRENT_VERSION}</b></p>"
            f"<p>Latest Version: <b>{latest_version}</b></p>"
        ))

        dl_btn = QPushButton("⬇️ Open Download Page")
        dl_btn.clicked.connect(self._open_download)
        layout.addWidget(dl_btn)

        close_btn = QPushButton("Later")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _open_download(self) -> None:
        webbrowser.open(self.download_url)
        self.close()
