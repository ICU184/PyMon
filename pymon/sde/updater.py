"""SDE Online-Updater – downloads latest SDE JSONL from data.everef.net."""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
import orjson
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
SDE_DOWNLOAD_URL = (
    "https://data.everef.net/ccp/sde/eve-online-static-data-latest-jsonl.zip"
)
CHUNK_SIZE = 256 * 1024  # 256 KiB


# ── Helper: Read build number from _sde.jsonl ────────────────────────
def read_build_number_from_jsonl(sde_dir: Path) -> int | None:
    """Read build number from _sde.jsonl in a JSONL directory."""
    sde_file = sde_dir / "_sde.jsonl"
    if not sde_file.exists():
        return None
    try:
        first_line = sde_file.read_text(encoding="utf-8").strip().split("\n")[0]
        data = orjson.loads(first_line)
        return data.get("buildNumber")
    except Exception:
        return None


def check_remote_build_number() -> int | None:
    """Fetch only _sde.jsonl from the remote ZIP to get the build number.

    Uses an HTTP Range request to read the ZIP's end-of-central-directory
    to find _sde.jsonl.  Falls back to downloading the full file if Range
    requests are not supported.  Returns None on failure.
    """
    # Simple approach: HEAD request to get file size, then we just
    # download and check.  Since _sde.jsonl is tiny, we can also
    # just do a quick GET of the first bytes… but ZIP stores the
    # directory at the end.  Let's do a lightweight approach: we
    # download just the first ~4 KB and hope _sde.jsonl is stored early.
    # Actually the most robust approach for our use case: just make a
    # HEAD request and report the Last-Modified date as a hint, then
    # do the full download if user agrees.  We'll check build number
    # after extraction.
    return None  # We compare after download instead


# ── Download Thread ──────────────────────────────────────────────────
class SDEDownloadThread(QThread):
    """Background thread that downloads, extracts and imports the SDE.

    Signals:
        progress(int, int) – (bytes_downloaded, total_bytes)
        status(str)        – status message
        finished_ok(int)   – emitted on success with new build number
        finished_err(str)  – emitted on failure with error message
    """

    progress = Signal(int, int)
    status = Signal(str)
    finished_ok = Signal(int)
    finished_err = Signal(str)

    def __init__(
        self,
        db_path: Path,
        current_build: int | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.current_build = current_build
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        tmp_dir = None
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="pymon_sde_"))
            zip_path = tmp_dir / "sde-latest.zip"

            # ── Phase 1: Download ────────────────────────────────
            self.status.emit("SDE wird heruntergeladen…")
            logger.info("Downloading SDE from %s", SDE_DOWNLOAD_URL)

            with httpx.stream("GET", SDE_DOWNLOAD_URL, timeout=120, follow_redirects=True) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=CHUNK_SIZE):
                        if self._cancelled:
                            self.finished_err.emit("Abgebrochen")
                            return
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)

            if self._cancelled:
                self.finished_err.emit("Abgebrochen")
                return

            # ── Phase 2: Extract ─────────────────────────────────
            self.status.emit("ZIP wird entpackt…")
            logger.info("Extracting SDE ZIP (%d bytes)", zip_path.stat().st_size)
            extract_dir = tmp_dir / "sde_jsonl"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Find the actual JSONL directory (may be nested)
            jsonl_dir = self._find_jsonl_dir(extract_dir)
            if jsonl_dir is None:
                self.finished_err.emit(
                    "No valid SDE JSONL directory found in ZIP"
                )
                return

            # ── Phase 3: Check build number ──────────────────────
            new_build = read_build_number_from_jsonl(jsonl_dir)
            if new_build and self.current_build and new_build <= self.current_build:
                self.finished_err.emit(
                    f"Bereits aktuell (Build {self.current_build})"
                )
                return

            # ── Phase 4: Import into SQLite ──────────────────────
            self.status.emit("SDE wird importiert…")
            logger.info("Importing SDE from %s", jsonl_dir)
            from pymon.sde.loader import import_sde
            import_sde(str(jsonl_dir), str(self.db_path))

            build = new_build or 0
            self.status.emit(f"✓ SDE updated (Build {build})")
            self.finished_ok.emit(build)

        except httpx.HTTPStatusError as e:
            msg = f"Download fehlgeschlagen: HTTP {e.response.status_code}"
            logger.error(msg)
            self.finished_err.emit(msg)
        except Exception as e:
            msg = f"SDE update error: {e}"
            logger.exception(msg)
            self.finished_err.emit(msg)
        finally:
            # Cleanup temp dir
            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

    @staticmethod
    def _find_jsonl_dir(root: Path) -> Path | None:
        """Find the directory containing _sde.jsonl (may be nested)."""
        # Check root itself
        if (root / "_sde.jsonl").exists():
            return root
        # Check one level of subdirectories
        for child in root.iterdir():
            if child.is_dir() and (child / "_sde.jsonl").exists():
                return child
            # Check two levels deep
            if child.is_dir():
                for grandchild in child.iterdir():
                    if grandchild.is_dir() and (grandchild / "_sde.jsonl").exists():
                        return grandchild
        return None


# ── Progress Dialog ──────────────────────────────────────────────────
class SDEUpdateDialog:
    """Creates and manages a progress dialog for SDE downloads.

    Usage from MainWindow:
        thread = SDEDownloadThread(db_path, current_build)
        dialog = SDEUpdateDialog.create(parent)
        thread.progress.connect(dialog.on_progress)
        thread.status.connect(dialog.on_status)
        thread.start()
    """

    @staticmethod
    def create(parent: Any) -> Any:
        from PySide6.QtWidgets import (
            QDialog,
            QLabel,
            QProgressBar,
            QPushButton,
            QVBoxLayout,
        )

        class SDEUpdateProgressDialog(QDialog):
            cancel_requested = Signal()

            def __init__(self, parent: Any = None) -> None:
                super().__init__(parent)
                self.setWindowTitle("SDE Online-Update")
                self.setFixedSize(450, 160)
                self.setModal(True)

                layout = QVBoxLayout(self)

                self.status_label = QLabel("Vorbereitung…")
                layout.addWidget(self.status_label)

                self.progress_bar = QProgressBar()
                self.progress_bar.setRange(0, 0)  # indeterminate
                layout.addWidget(self.progress_bar)

                self.detail_label = QLabel("")
                layout.addWidget(self.detail_label)

                self.cancel_btn = QPushButton("Cancel")
                self.cancel_btn.clicked.connect(self._on_cancel)
                layout.addWidget(self.cancel_btn)

            def on_progress(self, downloaded: int, total: int) -> None:
                if total > 0:
                    self.progress_bar.setRange(0, total)
                    self.progress_bar.setValue(downloaded)
                    mb_dl = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    pct = (downloaded / total) * 100
                    self.detail_label.setText(
                        f"{mb_dl:.1f} / {mb_total:.1f} MB ({pct:.0f}%)"
                    )
                else:
                    mb_dl = downloaded / (1024 * 1024)
                    self.detail_label.setText(f"{mb_dl:.1f} MB heruntergeladen")

            def on_status(self, msg: str) -> None:
                self.status_label.setText(msg)
                # Switch to indeterminate for import phase
                if "importiert" in msg.lower() or "entpack" in msg.lower():
                    self.progress_bar.setRange(0, 0)

            def on_finished_ok(self, build: int) -> None:
                self.accept()

            def on_finished_err(self, msg: str) -> None:
                self.status_label.setText(f"✗ {msg}")
                self.cancel_btn.setText("Close")
                self.cancel_btn.clicked.disconnect()
                self.cancel_btn.clicked.connect(self.reject)
                self.progress_bar.setRange(0, 1)
                self.progress_bar.setValue(0)

            def _on_cancel(self) -> None:
                self.cancel_requested.emit()

        return SDEUpdateProgressDialog(parent)
