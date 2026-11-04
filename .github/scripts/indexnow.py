#!/usr/bin/env python3
"""Submit this site's sitemap URLs to IndexNow.

The key file is docs/<key>.txt and is published at the project-site root
https://open-speaker-llm.github.io/xiaomi_ai_llm/<key>.txt
(keyLocation). Until GitHub Pages is serving that file, this script exits 0
and does not call the API.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOST = "open-speaker-llm.github.io"
SITE = f"https://{HOST}/xiaomi_ai_llm"
ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SITEMAP = DOCS / "sitemap.xml"
API = "https://api.indexnow.org/indexnow"


def key_file():
    found = [
        path
        for path in DOCS.glob("*.txt")
        if re.fullmatch(r"[0-9a-fA-F]{8,128}", path.stem)
    ]
    if len(found) != 1:
        sys.exit(f"expected one IndexNow key file in docs/, found {len(found)}")
    path = found[0]
    key = path.read_text(encoding="utf-8").strip()
    if key != path.stem:
        sys.exit(f"{path.name} contents must equal its filename")
    return key, path.name


def sitemap_urls():
    text = SITEMAP.read_text(encoding="utf-8")
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
    if not urls:
        sys.exit("sitemap.xml has no <loc> entries")
    for url in urls:
        if not url.startswith(SITE + "/") and url != SITE + "/":
            sys.exit(f"sitemap URL is outside the project site: {url}")
    return urls


def fetch(url, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read()


def main():
    dry_run = "--dry-run" in sys.argv
    key, filename = key_file()
    urls = sitemap_urls()
    key_location = f"{SITE}/{filename}"
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    try:
        status, body = fetch(key_location)
    except Exception as exc:
        print(f"IndexNow skipped: key URL is not reachable yet ({exc}).")
        print("Enable GitHub Pages from branch main, folder /docs, then push again.")
        return
    if status != 200 or body.decode("utf-8", errors="replace").strip() != key:
        print(f"IndexNow skipped: {key_location} did not return the key (HTTP {status}).")
        return

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "xiaomi-ai-llm-indexnow",
    }
    try:
        status, body = fetch(API, data=data, headers=headers, method="POST")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        sys.exit(f"IndexNow HTTP {exc.code}: {detail}")
    if status not in (200, 202):
        sys.exit(f"IndexNow HTTP {status}: {body[:500]!r}")
    print(f"IndexNow accepted {len(urls)} URL(s) with HTTP {status}.")


if __name__ == "__main__":
    main()
