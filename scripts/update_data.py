"""Copy the newest statistics from the data repository into
lolhex/data/bundled/ (shipped inside the installer and the portable build).

    python scripts/update_data.py                           # download the latest from GitHub
    python scripts/update_data.py --from ../aramhex-data    # use a local clone

Set the GITHUB_TOKEN environment variable when authentication is required.
Every file is checked against the SHA-256 in latest.json; bundled/ is left
untouched if a check fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lolhex.data.public import RAW_BASE, Dataset, check_manifest  # noqa: E402

BUNDLED = ROOT / "lolhex" / "data" / "bundled"
# The TW translation catalog shares bundled/ with the upstream statistics;
# updating the statistics must not delete it.
FORK_LOCAL_FILES = ("tw-catalog.json",)


def _get(url: str) -> bytes:
    import requests
    headers = {"User-Agent": "aramhex-build"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.content


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Update the bundled statistics")
    ap.add_argument("--from", dest="src", type=Path, help="local aramhex-data directory (omit to download from GitHub)")
    args = ap.parse_args(argv)
    if args.src:
        manifest = json.loads((args.src / "latest.json").read_text(encoding="utf-8"))
        read = lambda name: (args.src / manifest["path"] / name).read_bytes()  # noqa: E731
    else:
        manifest = json.loads(_get(f"{RAW_BASE}/latest.json"))
        read = lambda name: _get(f"{RAW_BASE}/{manifest['path']}/{name}")  # noqa: E731
    check_manifest(manifest)
    preserved = {name: (BUNDLED / name).read_bytes() for name in FORK_LOCAL_FILES
                 if (BUNDLED / name).is_file()}
    tmp = BUNDLED.with_name("bundled.new")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for name, f in manifest["files"].items():
            body = read(name)
            if hashlib.sha256(body).hexdigest() != f["sha256"]:
                raise SystemExit(f"{name}: SHA-256 does not match the manifest")
            (tmp / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp / name).write_bytes(body)
        (tmp / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                         encoding="utf-8")
        ds = Dataset(tmp, "bundled")
        shutil.rmtree(BUNDLED, ignore_errors=True)
        tmp.rename(BUNDLED)
        for name, body in preserved.items():
            (BUNDLED / name).write_bytes(body)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Bundled data updated: patch {ds.patch}, sample through {ds.snapshot_at}, "
          f"{len(manifest['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
