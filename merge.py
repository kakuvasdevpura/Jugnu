#!/usr/bin/env python3
# merge.py
# Usage: placed in repo root. Writes output/allinone.m3u and output/kaku.m3u and output/merge_log.txt

import os
import sys
import time
import requests

# === CONFIGURE YOUR SOURCE PLAYLISTS HERE ===
SOURCES = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jcinema.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jtv.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u",
    # add more sources here if you want
]

OUTPUT_DIR = "output"
OUT_NAME = "allinone.m3u"   # primary merged file
ALIAS_NAME = "kaku.m3u"     # for backwards compatibility with your repo
LOG_NAME = "merge_log.txt"

HEADERS = {
    # common browser-like header to reduce blocking
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}

TIMEOUT = 20
RETRIES = 2
SLEEP_BETWEEN_RETRIES = 2

def safe_fetch(url):
    last_exc = None
    for attempt in range(1, RETRIES + 2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(SLEEP_BETWEEN_RETRIES)
    raise last_exc

def sanitize_name_from_url(url):
    try:
        return url.split("/")[-1] or url
    except:
        return url

def parse_m3u_lines(text):
    """
    Returns list of lines keeping relative order.
    We'll preserve #EXTINF lines and stream URLs.
    """
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # keep everything but ignore playlist header duplication
        if line.upper() == "#EXTM3U":
            continue
        lines.append(line)
    return lines

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    merged_lines = ["#EXTM3U"]
    seen_urls = set()
    log = []
    total_added = 0

    start_time = time.time()
    log.append(f"Merge started: {time.ctime(start_time)}")
    for idx, src in enumerate(SOURCES, start=1):
        log.append(f"\nFetching source {idx}/{len(SOURCES)}: {src}")
        try:
            r = safe_fetch(src)
            status = getattr(r, "status_code", None)
            log.append(f"HTTP status: {status}")
            if r is None or status != 200:
                log.append(f"Skipped (bad status) {src}")
                continue

            text = r.text
            lines = parse_m3u_lines(text)
            if not lines:
                log.append("No lines found in source.")
                continue

            # Add a group header
            group_name = sanitize_name_from_url(src)
            merged_lines.append(f"#--- Group: {group_name}")

            added_in_source = 0
            i = 0
            # Walk through lines, pair EXTINF + URL where possible
            while i < len(lines):
                line = lines[i]
                if line.startswith("#EXTINF"):
                    # possibly the next non-comment line is the URL
                    url = None
                    extinf = line
                    j = i + 1
                    # find next non-empty non-EXT line (should be url)
                    while j < len(lines) and lines[j].startswith("#"):
                        j += 1
                    if j < len(lines):
                        url = lines[j]
                        i = j + 1
                    else:
                        # no url found, just skip
                        i += 1
                        continue

                    # dedupe by url
                    if url in seen_urls:
                        # already added
                        continue
                    seen_urls.add(url)
                    merged_lines.append(extinf)
                    merged_lines.append(url)
                    added_in_source += 1
                else:
                    # line might be a raw URL (no preceding EXTINF)
                    if not line.startswith("#"):
                        url = line
                        if url in seen_urls:
                            i += 1
                            continue
                        seen_urls.add(url)
                        # add a basic EXTINF placeholder
                        merged_lines.append("#EXTINF:-1,Unknown")
                        merged_lines.append(url)
                        added_in_source += 1
                    i += 1

            total_added += added_in_source
            log.append(f"Added {added_in_source} entries from source.")
        except Exception as e:
            log.append(f"Error fetching {src}: {repr(e)}")

    # Final summary
    elapsed = time.time() - start_time
    log.append(f"\nTotal streams added: {total_added}")
    log.append(f"Elapsed: {elapsed:.1f}s")

    # Write output files
    out_path = os.path.join(OUTPUT_DIR, OUT_NAME)
    alias_path = os.path.join(OUTPUT_DIR, ALIAS_NAME)
    log_path = os.path.join(OUTPUT_DIR, LOG_NAME)

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(merged_lines) + "\n")
        with open(alias_path, "w", encoding="utf-8") as f:
            f.write("\n".join(merged_lines) + "\n")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
        print(f"Wrote {out_path} ({total_added} entries) and {alias_path}")
    except Exception as e:
        print(f"Error writing output files: {repr(e)}")
        # also print log to console
        print("\n".join(log))
        sys.exit(2)

if __name__ == "__main__":
    main()
