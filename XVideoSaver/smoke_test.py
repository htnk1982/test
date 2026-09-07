#!/usr/bin/env python3
import json
import re
import sys
import urllib.request

TWEET_ID = sys.argv[1] if len(sys.argv) > 1 else "2096554012937973979"
TOKENS = ("x", "0", "a")
RES = re.compile(r"/(\d{2,5})x(\d{2,5})/")
UA = "Mozilla/5.0 (Linux; Android) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36"


def walk(node, out):
    if isinstance(node, dict):
        variants = node.get("variants")
        if isinstance(variants, list):
            for i, v in enumerate(variants):
                if not isinstance(v, dict):
                    continue
                mime = v.get("content_type") or v.get("type") or ""
                url = v.get("url") or v.get("src") or ""
                if not isinstance(url, str):
                    continue
                if mime.lower() == "video/mp4" or ".mp4" in url.lower():
                    if url.startswith("https://") and "twimg.com" in url:
                        bitrate = int(v.get("bitrate") or 0)
                        m = RES.search(url)
                        area = int(m.group(1)) * int(m.group(2)) if m else 0
                        out.append((bitrate, area, i, url))
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, out)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                walk(value, out)


def fetch_metadata(token):
    url = (
        "https://cdn.syndication.twimg.com/tweet-result?id="
        + TWEET_ID
        + "&lang=ja&token="
        + token
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://platform.twitter.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def probe_video(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "video/mp4,*/*",
            "Range": "bytes=0-1023",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        status = getattr(response, "status", response.getcode())
        ctype = response.headers.get("Content-Type", "")
        first = response.read(32)
        if status not in (200, 206):
            raise RuntimeError(f"video HTTP {status}")
        if not first:
            raise RuntimeError("video response was empty")
        return status, ctype


last_error = None
for token in TOKENS:
    try:
        data = fetch_metadata(token)
        candidates = []
        walk(data, candidates)
        if candidates:
            best = max(candidates, key=lambda x: (x[0], x[1], x[2]))
            video_status, video_type = probe_video(best[3])
            # Intentionally do not print the signed media URL.
            print(
                f"PASS tweet={TWEET_ID} token={token} mp4_candidates={len(candidates)} "
                f"best_bitrate={best[0]} best_resolution_area={best[1]} "
                f"video_http={video_status} content_type={video_type}"
            )
            sys.exit(0)
    except Exception as exc:
        last_error = exc

print(f"FAIL tweet={TWEET_ID}: no downloadable public MP4; last_error={last_error}", file=sys.stderr)
sys.exit(1)
