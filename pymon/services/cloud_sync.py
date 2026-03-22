"""Cloud storage sync – export/import to local cloud folders.

Supports any cloud storage provider that syncs a local folder
(Dropbox, Google Drive, OneDrive, etc.). Copies config + DB to
the specified folder and can restore from it.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CloudSync:
    """Synchronise PyMon data to a local cloud-synced folder."""

    # Files to sync
    _FILES = ["config.json", "pymon.db"]

    def __init__(self, sync_folder: str = "", data_dir: str = "") -> None:
        self.sync_folder = sync_folder
        self.data_dir = data_dir

    @property
    def is_configured(self) -> bool:
        """Return True if sync folder is set and exists."""
        return bool(self.sync_folder and Path(self.sync_folder).is_dir())

    def update_settings(self, sync_folder: str, data_dir: str) -> None:
        """Update sync settings."""
        self.sync_folder = sync_folder
        self.data_dir = data_dir

    def export_to_cloud(self) -> tuple[bool, str]:
        """Copy PyMon data files to the cloud sync folder.

        Returns (success, message).
        """
        if not self.is_configured:
            return False, "Cloud-Ordner nicht konfiguriert."
        if not self.data_dir:
            return False, "Datenverzeichnis nicht gesetzt."

        src = Path(self.data_dir)
        dst = Path(self.sync_folder) / "PyMon_Backup"
        try:
            dst.mkdir(parents=True, exist_ok=True)

            copied: list[str] = []
            for fname in self._FILES:
                src_file = src / fname
                if src_file.exists():
                    shutil.copy2(src_file, dst / fname)
                    copied.append(fname)

            # Write manifest
            manifest = {
                "exported_at": datetime.now().isoformat(),
                "files": copied,
                "source": str(src),
            }
            (dst / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return True, f"{len(copied)} Dateien exportiert nach:\n{dst}"
        except Exception as e:
            logger.error("Cloud export failed", exc_info=True)
            return False, f"Export fehlgeschlagen:\n{e}"

    def import_from_cloud(self) -> tuple[bool, str]:
        """Restore PyMon data files from the cloud sync folder.

        Returns (success, message).
        """
        if not self.is_configured:
            return False, "Cloud-Ordner nicht konfiguriert."
        if not self.data_dir:
            return False, "Datenverzeichnis nicht gesetzt."

        cloud_dir = Path(self.sync_folder) / "PyMon_Backup"
        if not cloud_dir.is_dir():
            return False, f"No backup found in:\n{cloud_dir}"

        dst = Path(self.data_dir)
        try:
            restored: list[str] = []
            for fname in self._FILES:
                cloud_file = cloud_dir / fname
                if cloud_file.exists():
                    # Backup current file first
                    dst_file = dst / fname
                    if dst_file.exists():
                        bak = dst / f"{fname}.bak"
                        shutil.copy2(dst_file, bak)
                    shutil.copy2(cloud_file, dst_file)
                    restored.append(fname)

            return True, (
                f"{len(restored)} Dateien wiederhergestellt.\n"
                "Please restart PyMon for the changes to take effect."
            )
        except Exception as e:
            logger.error("Cloud import failed", exc_info=True)
            return False, f"Import fehlgeschlagen:\n{e}"

    def get_last_export_info(self) -> str | None:
        """Return info about the last export, or None."""
        if not self.is_configured:
            return None
        manifest = Path(self.sync_folder) / "PyMon_Backup" / "manifest.json"
        if not manifest.exists():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return f"Letzter Export: {data.get('exported_at', '?')}"
        except Exception:
            return None
