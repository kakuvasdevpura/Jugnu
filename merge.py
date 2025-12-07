#!/usr/bin/env python3
# merge.py - auto-merge with cleakey/token auto-detect & append
# Place at repo root. Writes: output/kaku.m3u , output/allinone.m3u , output/merge_log.txt

import os, time, re, sys
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import requests

# ----------------- CONFIG -----------------
SOURCES = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jcinema.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jtv.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u"
]

OUTPUT_DIR = "output"
OUT_PRIMARY = "allinone.m3u"
OUT_ALIAS = "kaku.m3u"
LOG_FILE = "merge_log.txt"

# If True, add #EXTVLCOPT:cookie=cleakey=... lines (useful for VLC-type players)
WANT_VLC_OPT = False

# HTTP settings
HEADERS = {"User-Agent": "AutoMergeBot/1.0"}
TIMEOUT = 20
RETRIES = 2
SLEEP_BETWEEN_RETRIES = 1
# ------------------------------------------

def safe_fetch(url, headers=None, timeout=TIMEOUT):
    last_exc = None
    hdrs = headers or HEADERS
    for attempt in range(1, RETRIES+2):
        try:
            r = requests.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
            return r
        except Exception as e:
            last_exc = e
            time.sleep(SLEEP_BETWEEN_RETRIES)
    raise last_exc

def find_cleakey_in_text(text):
    if not text:
        return None
    # 1) query param style cleakey=...
    m = re.search(r'cleakey=([A-Za-z0-9_\-\.%]+)', text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # 2) JSON style: "cleakey":"..." or "token":"..."
    m = re.search(r'["\']?(?:cleakey|token|key)["\']?\s*[:=]\s*["\']([A-Za-z0-9_\-\.]+)["\']', text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # 3) plain line: cleakey = abc
    m = re.search(r'^\s*(?:cleakey|token)\s*[:=]\s*([A-Za-z0-9_\-\.]+)\s*$', text, flags=re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1)
    # 4) EXT-X-KEY:URI="..."
    m = re.search(r'EXT-X-KEY:[^\n]*URI=["\']?([^"\']+)["\']?', text, flags=re.IGNORECASE)
    if m:
        # extract simple token
        t = m.group(1)
        mm = re.search(r'([A-Za-z0-9_\-\.]+)', t)
        if mm:
            return mm.group(1)
    return None

def append_query_param(url, key, val):
    if not val:
        return url
    try:
        p = urlparse(url)
    except Exception:
        return url
    qs = parse_qs(p.query, keep_blank_values=True)
    if key in qs and qs[key]:
        return url
    qs[key] = [val]
    new_q = urlencode(qs, doseq=True)
    new_parts = (p.scheme, p.netloc, p.path, p.params, new_q, p.fragment)
    return urlunparse(new_parts)

def extract_tvgid_or_name(extinf):
    # try tvg-id first
    if not extinf:
        return None
    m = re.search(r'tvg-id="([^"]+)"', extinf)
    if m and m.group(1).strip():
        return ("id", m.group(1).strip().lower())
    # fallback name after comma
    if ',' in extinf:
        nm = extinf.split(',',1)[1].strip()
        if nm:
            return ("name", nm.lower())
    return None

def sanitize_src_name(url):
    try:
        return url.split("/")[-1] or url
    except:
        return url

def parse_m3u_text_to_lines(text):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # skip header duplicates
        if line.upper() == "#EXTM3U":
            continue
        lines.append(line)
    return lines

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    merged = ["#EXTM3U"]
    raw_concat = ["#EXTM3U"]
    seen_keys = set()  # smart dedupe key set (tuple)
    log = []
    total_added = 0
    start = time.time()
    log.append(f"Merge started: {time.ctime(start)}")

    for idx, src in enumerate(SOURCES, start=1):
        log.append(f"\n[{idx}/{len(SOURCES)}] Fetching: {src}")
        try:
            resp = safe_fetch(src)
        except Exception as e:
            log.append(f"Fetch error for {src}: {repr(e)}")
            continue
        status = getattr(resp, "status_code", None)
        log.append(f"HTTP status: {status}")
        body = resp.text if resp is not None else ""
        # raw concat block (as-is)
        raw_concat.append(f"\n#--- SOURCE: {src} ---\n")
        raw_concat.append(body if body else f"# (empty or failed for {src})\n")

        if status != 200 or not body:
            log.append(f"Skipping parse: bad status or empty body for {src}")
            continue

        # try detect cleakey/token in source body
        token = find_cleakey_in_text(body)
        if token:
            log.append(f"Detected token/cleakey (masked): {token[:4]}...")

        lines = parse_m3u_text_to_lines(body)
        if not lines:
            log.append("No m3u entries parsed (maybe HTML or blocked).")
            continue

        # group header in merged output
        merged.append(f"#--- Group: {sanitize_src_name(src)}")

        i = 0
        added_from_source = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("#EXTINF"):
                extinf = line
                # next non-comment line expected as URL
                j = i + 1
                while j < len(lines) and lines[j].startswith("#"):
                    j += 1
                if j < len(lines):
                    url = lines[j]
                    i = j + 1
                else:
                    i += 1
                    continue
                # create dedupe key (tvg-id -> url -> name)
                tk = extract_tvgid_or_name(extinf)
                if tk:
                    key = ("tvg", tk[1]) if tk[0]=="id" else ("name", tk[1])
                else:
                    key = ("url", url)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                # apply token if found: prefer query param append
                final_url = url
                if token:
                    final_url = append_query_param(final_url, "cleakey", token)

                # optionally add VLC cookie line
                if token and WANT_VLC_OPT:
                    merged.append(extinf)
                    merged.append(f"#EXTVLCOPT:cookie=cleakey={token}")
                    merged.append(final_url)
                else:
                    merged.append(extinf)
                    merged.append(final_url)

                added_from_source += 1
                total_added += 1
            else:
                # line might be direct url without EXTINF
                if not line.startswith("#"):
                    url = line
                    key = ("url", url)
                    if key in seen_keys:
                        i += 1
                        continue
                    seen_keys.add(key)
                    final_url = url
                    if token:
                        final_url = append_query_param(final_url, "cleakey", token)
                    merged.append("#EXTINF:-1,Unknown")
                    merged.append(final_url)
                    added_from_source += 1
                    total_added += 1
                i += 1

        log.append(f"Added {added_from_source} entries from source.")

    elapsed = time.time() - start
    log.append(f"\nTotal streams added: {total_added}")
    log.append(f"Elapsed: {elapsed:.1f}s")

    # write outputs
    out_primary = os.path.join(OUTPUT_DIR, OUT_PRIMARY)
    out_alias = os.path.join(OUTPUT_DIR, OUT_ALIAS)
    log_path = os.path.join(OUTPUT_DIR, LOG_FILE)
    raw_path = os.path.join(OUTPUT_DIR, "kaku_raw.m3u")

    try:
        with open(out_primary, "w", encoding="utf-8") as f:
            f.write("\n".join(merged) + "\n")
        with open(out_alias, "w", encoding="utf-8") as f:
            f.write("\n".join(merged) + "\n")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write("\n".join(raw_concat) + "\n")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
        print(f"Wrote {out_primary}, {out_alias}, {raw_path}")
    except Exception as e:
        print("Write error:", repr(e))
        print("\n".join(log))
        sys.exit(2)

if __name__ == "__main__":
    main()
