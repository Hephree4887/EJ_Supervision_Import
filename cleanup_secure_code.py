"""Utility to remove obsolete secure modules."""

from __future__ import annotations

import shutil
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FILES = [
    "01_JusticeDB_Import_Secure.py",
    "02_OperationsDB_Import_Secure.py",
    "03_FinancialDB_Import_Secure.py",
    "etl/secure_base_importer.py",
    "migrate_to_secure_system.py",
    "utils/sql_security.py",
]

DIRS = ["hooks"]


def cleanup(backup_dir: str = "migration_backup/secure_removed") -> None:
    backup = Path(backup_dir)
    backup.mkdir(parents=True, exist_ok=True)

    for name in FILES:
        path = Path(name)
        if path.exists():
            dest = backup / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), dest)
            logger.info("Moved %s to %s", path, dest)

    for d in DIRS:
        path = Path(d)
        if path.exists():
            dest = backup / path.name
            shutil.move(str(path), dest)
            logger.info("Moved %s to %s", path, dest)


if __name__ == "__main__":
    cleanup()
