#!/usr/bin/env python3
"""Upload and publish a new version of Engram Capture to the Chrome Web Store,
without opening the dashboard. Uses the Chrome Web Store API v2.

Only works for an item that already exists. The FIRST submission (listing text,
screenshots, privacy answers) has to go through the dashboard once, by hand. See
STORE_LISTING.md.

    python3 tools/cws_publish.py status            # read-only: what the store has now
    python3 tools/cws_publish.py upload            # build the zip and upload it as a draft
    python3 tools/cws_publish.py publish           # submit the uploaded draft for review
    python3 tools/cws_publish.py release           # upload, then publish

Options: --zip PATH to upload a ready-made zip instead of building one;
--staged to publish as STAGED (after approval you press Publish yourself).

Credentials come from SSM Parameter Store (eu-west-1) and nowhere else. They are
never printed, logged or written to disk:

    /chrome-webstore/client_id                    SecureString  OAuth client id
    /chrome-webstore/client_secret                SecureString  OAuth client secret
    /chrome-webstore/refresh_token                SecureString  refresh token, scope .../auth/chromewebstore
    /chrome-webstore/publisher_id                 String        Dashboard > Publisher > Settings
    /chrome-webstore/engram-capture/item_id       String        the 32-letter extension id

Set CWS_SSM_REGION to read them from another region.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
REGION = os.environ.get("CWS_SSM_REGION", "eu-west-1")
PREFIX = "/chrome-webstore"
API = "https://chromewebstore.googleapis.com"


def ssm_params():
    names = {
        "client_id": f"{PREFIX}/client_id",
        "client_secret": f"{PREFIX}/client_secret",
        "refresh_token": f"{PREFIX}/refresh_token",
        "publisher_id": f"{PREFIX}/publisher_id",
        "item_id": f"{PREFIX}/engram-capture/item_id",
    }
    resp = boto3.client("ssm", region_name=REGION).get_parameters(
        Names=list(names.values()), WithDecryption=True)
    got = {p["Name"]: p["Value"].strip() for p in resp["Parameters"]}
    missing = [n for n in names.values() if n not in got]
    if missing:
        sys.exit(f"missing SSM parameters in {REGION}: {', '.join(missing)} (see STORE_LISTING.md, one-time setup)")
    return {k: got[v] for k, v in names.items()}


def request(method, url, token=None, data=None, content_type=None):
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        # Google's error bodies carry a message and status, never the credentials.
        detail = e.read().decode(errors="replace")[:2000]
        sys.exit(f"{method} {url.split('?')[0]} -> HTTP {e.code}\n{detail}")
    return json.loads(body) if body else {}


def access_token(cfg):
    form = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=form, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", "unknown")
        hint = (" - the refresh token has expired or was revoked; redo step 4 of the one-time setup"
                " (if this happens every 7 days, the OAuth consent screen is still in Testing)"
                if err == "invalid_grant" else "")
        sys.exit(f"could not get an access token: {err}{hint}")


def item_name(cfg):
    return f"publishers/{cfg['publisher_id']}/items/{cfg['item_id']}"


def fetch_status(cfg, token):
    return request("GET", f"{API}/v2/{item_name(cfg)}:fetchStatus", token)


def describe(status):
    lines = [f"item {status.get('itemId')}"]
    for key, label in (("publishedItemRevisionStatus", "published"),
                       ("submittedItemRevisionStatus", "submitted")):
        rev = status.get(key)
        if rev:
            versions = ", ".join(f"{c.get('crxVersion')} @ {c.get('deployPercentage', '?')}%"
                                 for c in rev.get("distributionChannels", []))
            lines.append(f"  {label}: {rev.get('state')}  {versions}")
        else:
            lines.append(f"  {label}: none")
    if status.get("lastAsyncUploadState"):
        lines.append(f"  last upload: {status['lastAsyncUploadState']}")
    if status.get("takenDown") or status.get("warned"):
        lines.append(f"  POLICY: takenDown={status.get('takenDown')} warned={status.get('warned')}")
    return "\n".join(lines)


def build_zip():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "build_zip.py")],
                         check=True, capture_output=True, text=True).stdout
    return Path(out.splitlines()[0])


def upload(cfg, token, zip_path):
    print(f"uploading {zip_path} ...")
    res = request("POST", f"{API}/upload/v2/{item_name(cfg)}:upload", token,
                  data=zip_path.read_bytes(), content_type="application/zip")
    state = res.get("uploadState")
    for _ in range(30):
        if state != "IN_PROGRESS":
            break
        time.sleep(10)
        state = fetch_status(cfg, token).get("lastAsyncUploadState")
    if state != "SUCCEEDED":
        sys.exit(f"upload did not succeed: {state} (a version that is not higher than the store's is the usual cause)")
    print(f"uploaded version {res.get('crxVersion') or '(processed asynchronously)'}")


def publish(cfg, token, staged):
    body = {"publishType": "STAGED_PUBLISH" if staged else "DEFAULT_PUBLISH"}
    res = request("POST", f"{API}/v2/{item_name(cfg)}:publish", token,
                  data=json.dumps(body).encode(), content_type="application/json")
    print(f"submitted: {res.get('state')}")
    for w in (res.get("warningInfo") or {}).get("warnings", []):
        print(f"  warning {w.get('reason')}: {w.get('description')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["status", "upload", "publish", "release"])
    ap.add_argument("--zip", type=Path, help="upload this zip instead of building one")
    ap.add_argument("--staged", action="store_true", help="publish as STAGED; you press Publish after approval")
    args = ap.parse_args()

    cfg = ssm_params()
    token = access_token(cfg)
    if args.action in ("upload", "release"):
        upload(cfg, token, args.zip or build_zip())
    if args.action in ("publish", "release"):
        publish(cfg, token, args.staged)
    print(describe(fetch_status(cfg, token)))


if __name__ == "__main__":
    main()
