#!/usr/bin/env python3
"""One-time source localization for the TW fork.

Only source strings/docs are converted. Alias and upstream statistics JSON are
left untouched so Simplified Chinese player vocabulary remains searchable.
"""
from pathlib import Path
from opencc import OpenCC

ROOT = Path(__file__).resolve().parent.parent
cc = OpenCC("s2twp")
paths = list(ROOT.glob("lolhex/**/*.py"))
paths += list(ROOT.glob("tests/**/*.py"))
paths += [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "packaging/LolHex.iss"]
paths += list((ROOT / "docs").glob("**/*.md"))
changed = []
for path in paths:
    if not path.is_file():
        continue
    old = path.read_text(encoding="utf-8")
    new = cc.convert(old)
    if new != old:
        path.write_text(new, encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))
print(f"converted {len(changed)} files")
for name in changed:
    print(name)
