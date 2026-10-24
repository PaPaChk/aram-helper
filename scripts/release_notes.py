"""Generate the GitHub Release notes (shown to players, and also displayed by
the app's "new version available" prompt) from the CHANGELOG.md entry for the
version. Only what changed and what was fixed; no technical detail.

    python scripts/release_notes.py 1.0.7 > build/release-notes.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def notes(version: str, changelog: str) -> str:
    m = re.search(rf"(?ms)^## {re.escape(version)}\s*$(.*?)(?=^## |\Z)", changelog)
    body = m.group(1).strip() if m else f"AramHex {version}"
    return body + "\n"  # only what changed; the release page lists the files itself


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.write(notes(argv[0].lstrip("vV"), (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
