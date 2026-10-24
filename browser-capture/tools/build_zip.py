#!/usr/bin/env python3
"""Build the Chrome Web Store upload zip: browser-capture/dist/engram-capture-<version>.zip

Only the files the extension actually runs are packed: the manifest, every file it
references (scripts, options page, icons) and whatever those pages load. Docs,
store assets, tools and the privacy page stay out. Fails if a referenced file is
missing, so a broken package is caught here and not by the reviewer.

    python3 tools/build_zip.py
"""
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def referenced_files(manifest):
    files = {"manifest.json"}
    files.add(manifest["background"]["service_worker"])
    for cs in manifest.get("content_scripts", []):
        files.update(cs.get("js", []))
        files.update(cs.get("css", []))
    files.update(manifest.get("icons", {}).values())
    files.update(manifest.get("action", {}).get("default_icon", {}).values())
    for page in (manifest.get("options_page"), manifest.get("action", {}).get("default_popup")):
        if page:
            files.add(page)
            # Local scripts/styles the page loads (remote ones are not allowed in MV3).
            html = (ROOT / page).read_text()
            for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
                if "://" in ref:
                    sys.exit(f"{page} loads a remote resource ({ref}); MV3 forbids remote code")
                files.add(ref)
    return sorted(files)


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    version = manifest["version"]
    files = referenced_files(manifest)
    missing = [f for f in files if not (ROOT / f).is_file()]
    if missing:
        sys.exit(f"missing files referenced by the manifest: {missing}")

    out = ROOT / "dist" / f"engram-capture-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(ROOT / f, f)
    print(out)
    for f in files:
        print("  ", f)


if __name__ == "__main__":
    main()
