#!/usr/bin/env python3
# FINAL merge.py with:
# - jcinema removed
# - jtv removed
# - cleakey auto-detect & auto-append
# - smart dedupe
# - raw clone file
# - GitHub Actions compatible
# - Custom Windows UA (from Manoj)

import os, time, re, sys
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import requests

# ----------------- CONFIG -----------------
SOURCES = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u"
]

OUTPUT_DIR = "output"
OUT_PRIMARY = "allinone.m3u"
OUT_ALIAS = "kaku.m3u"
LOG_FILE = "merge_log.txt"

# VLC cookie support (optional)
WANT_VLC_OPT = False

# Custom User-Agent (Manoj special)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 ygx/69.1 Safari/537.36"
}

TIMEOUT = 20
RETRIES = 2
SLEEP_BETWEEN_RETRIES = 1
# ------------------------------------------

def safe_fetch(url, headers=None, timeout=TIMEOUT):
    last_exc = None
    hdrs = headers or HEADERS
    for attempt in range(1, RETRIES + 2):
        try:
            return requests.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
        except Exception as e:
            last_exc = e
            time.sleep(SLEEP_BETWEEN_RETRIES)
    raise last_exc

def find_cleakey_in_text(text):
    if not text:
        return None
    m = re.search(r'cleakey=([A-Za-z0-9_\-\.%]+)', text, flags=re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'["\']?(?:cleakey|token)["\']?\s*[:=]\s*["\']([A-Za-z0-9_\-\.]+)["\']', text, flags=re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'^\s*(?:cleakey|token)\s*[:=]\s*([A-Za-z0-9_\-\.]+)\s*$', text, flags=re.MULTILINE)
    if m: return m.group(1)
    m = re.search(r'EXT-X-KEY:[^\n]*URI=["\']?([^"\']+)["\']?', text)
    if m:
        mm = re.search(r'([A-Za-z0-9_\-\.]+)', m.group(1))
        if mm: return mm.group(1)
    return None

def append_query_param(url, key, val):
    if not val:
        return url
    try:
        p = urlparse(url)
    except Exception:
        return url
    qs = parse_qs(p.query, keep_blank_values=True)
    if key not in qs:
        qs[key] = [val]
    new_q = urlencode(qs, doseq=True)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, p.fragment))

def extract_tvgid_or_name(extinf):
    if not extinf:
        return None
    m = re.search(r'tvg-id="([^"]+)"', extinf)
    if m:
        return ("id", m.group(1).strip().lower())
    if "," in extinf:
        nm = extinf.split(",", 1)[1].strip()
        if nm:
            return ("name", nm.lower())
    return None

def sanitize_src_name(url):
    try:
        return url.split("/")[-1]
    except:
        return url

def parse_m3u_text_to_lines(t):
    arr = []
    for raw in t.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper() == "#EXTM3U":
            continue
        arr.append(line)
    return arr

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    merged = ["#EXTM3U"]
    raw_clone = ["#EXTM3U"]
    seen_keys = set()

    log = []
    total_added = 0
    start = time.time()
    log.append(f"Merge started: {time.ctime(start)}")

    for idx, src in enumerate(SOURCES, start=1):
        log.append(f"\n[{idx}/{len(SOURCES)}] Fetching: {src}")

        try:
            resp = safe_fetch(src)
        except Exception as e:
            log.append(f"Fetch error: {repr(e)}")
            continue

        status = getattr(resp, "status_code", None)
        text = resp.text if resp else ""
        log.append(f"HTTP {status}")

        raw_clone.append(f"\n#--- SOURCE: {src} ---\n")
        raw_clone.append(text)

        if status != 200 or not text:
            log.append("Empty or bad response, skipping")
            continue

        token = find_cleakey_in_text(text)
        if token:
            log.append(f"Detected cleakey (masked): {token[:4]}...")

        lines = parse_m3u_text_to_lines(text)
        if not lines:
            log.append("No valid m3u lines parsed")
            continue

        merged.append(f"#--- Group: {sanitize_src_name(src)}")

        i = 0
        added = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("#EXTINF"):
                extinf = line
                j = i + 1
                while j < len(lines) and lines[j].startswith("#"):
                    j += 1
                if j < len(lines):
                    url = lines[j]
                    i = j + 1
                else:
                    i += 1
                    continue
            else:
                if not line.startswith("#"):
                    extinf = "#EXTINF:-1,Unknown"
                    url = line
                    i += 1
                else:
                    i += 1
                    continue

            # Smart key (tvg-id → name → url)
            info = extract_tvgid_or_name(extinf)
            if info:
                key = ("id", info[1]) if info[0] == "id" else ("name", info[1])
            else:
                key = ("url", url)

            if key in seen_keys:
                continue
            seen_keys.add(key)

            final_url = append_query_param(url, "cleakey", token) if token else url

            if token and WANT_VLC_OPT:
                merged.append(extinf)
                merged.append(f"#EXTVLCOPT:cookie=cleakey={token}")
                merged.append(final_url)
            else:
                merged.append(extinf)
                merged.append(final_url)

            added += 1
            total_added += 1

        log.append(f"Added {added} entries")

    elapsed = time.time() - start
    log.append(f"\nTotal merged: {total_added}")
    log.append(f"Elapsed: {elapsed:.2f}s")

    try:
        with open(os.path.join(OUTPUT_DIR, OUT_PRIMARY), "w", encoding="utf-8") as f:
            f.write("\n".join(merged) + "\n")

        with open(os.path.join(OUTPUT_DIR, OUT_ALIAS), "w", encoding="utf-8") as f:
            f.write("\n".join(merged) + "\n")

        with open(os.path.join(OUTPUT_DIR, "kaku_raw.m3u"), "w", encoding="utf-8") as f:
            f.write("\n".join(raw_clone) + "\n")

        with open(os.path.join(OUTPUT_DIR, LOG_FILE), "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")

        print("Merge completed successfully")

    except Exception as e:
        print("Write error:", repr(e))
        sys.exit(2)

if __name__ == "__main__":
    main()
