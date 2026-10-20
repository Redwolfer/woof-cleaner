"""Where bundled resources and user data live, both from source and as a PyInstaller .exe."""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    RESOURCES = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    EXE_DIR = Path(sys.executable).resolve().parent
    USER_DIR = Path(os.environ.get("LOCALAPPDATA", str(EXE_DIR))) / "WoofCleaner"
else:
    RESOURCES = Path(__file__).resolve().parent.parent
    EXE_DIR = RESOURCES
    USER_DIR = RESOURCES

# A rules.ini placed next to the .exe overrides the bundled one, so users can add rules without rebuilding.
DEFAULT_RULES = EXE_DIR / "rules.ini" if (FROZEN and (EXE_DIR / "rules.ini").exists()) else RESOURCES / "data" / "rules.ini"
BACKUP_DIR = USER_DIR / "backups"
ICON = RESOURCES / "assets" / "woof.ico"
