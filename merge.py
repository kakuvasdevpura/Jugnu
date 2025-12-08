#!/usr/bin/env python3
"""
merge.py

Generate only output/kaku.m3u by merging multiple m3u sources (http or local),
deduplicating entries by tvg-id or stream URL, and writing a small merge_log.txt.

Usage:
  - Put source URLs or file paths (one per line) in `sources.txt` at repo root.
  - Or place .m3u files under `input/` (or `output/`), they will be auto-discovered.
  - Run: python merge.py
"""

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except Exception:
    print("requests module not found. Install with: pip install requests", file=sys.stderr)
    raise

ROOT = Path(__file__).parent.resolve()
OUTPUT_DIR = ROOT / "output"
KAKU_PATH = OUTPUT_DIR / "kaku.m3u"
LOG_PATH = OUTPUT_DIR / "merge_log.txt"
SOURCES_FILE = ROOT / "sources.txt"

USER_AGENT = "Mozilla/5.0 (compatible; merge.py/1.0)"
REQUEST_TIMEOUT = 15  # seconds

EXTINF_RE = re.compile(r'^#EXTINF:.*', flags=re.IGNORECASE)
TVGID_RE = re.compile(r'tvg-id="([^"]+)"', flags=re.IGNORECASE)
# Some playlists use 'tvg-name' or no tvg-id; we primarily use tvg-id, else URL

def read_sources():
    sources = []
    if SOURCES_FILE.exists():
        with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                sources.append(s)
    else:
        # Auto-scan input/ and output/ for .m3u files (except target kaku.m3u)
        for d in ("input", "output"):
            dirp = ROOT / d
            if dirp.exists() and dirp.is_dir():
                for p in sorted(dirp.glob("*.m3u")):
                    # skip the target file if present
                    if p.resolve() == KAKU_PATH.resolve():
                        continue
                    sources.append(str(p))
    return sources

def fetch_source(src):
    """Return string content of source or None on failure"""
    if src.lower().startswith(("http://", "https://")):
        try:
            resp = requests.get(src, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            content = resp.text
            return content
        except Exception as e:
            print(f"[WARN] Failed to fetch URL {src}: {e}", file=sys.stderr)
            return None
    else:
        # local file
        p = Path(src)
        if not p.is_absolute():
            p = (ROOT / src).resolve()
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            print(f"[WARN] Failed to read file {p}: {e}", file=sys.stderr)
            return None

def parse_m3u(content):
    """
    Parse m3u content into list of (extinf_line, url_line) pairs.
    Will also handle entries where EXTINF may be followed by multiple comment lines.
    """
    lines = [ln.rstrip('\n') for ln in content.splitlines()]
    entries = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith('#EXTINF'):
            extinf = ln
            # capture following comment lines until we hit a non-comment url
            j = i + 1
            url = None
            # skip blank/comment lines except the actual stream url which usually doesn't start with '#'
            while j < len(lines):
                cand = lines[j].strip()
                if not cand:
                    j += 1
                    continue
                if cand.startswith('#'):
                    # Preserve additional metadata comments (rare), but try to find url below
                    # For simplicity, we treat the first non-# line as url
                    j += 1
                    continue
                # first non-comment non-empty line -> url
                url = cand
                break
            if url:
                entries.append((extinf, url))
                i = j + 1
            else:
                # malformed entry; skip ahead
                i += 1
        else:
            i += 1
    return entries

def get_tvg_id(extinf):
    m = TVGID_RE.search(extinf)
    if m:
        return m.group(1).strip()
    return None

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    sources = read_sources()
    start = datetime.utcnow()
    merged_entries = []
    seen_keys = set()
    source_stats = {}

    if not sources:
        print("[INFO] No sources found (no sources.txt and no m3u in input/ or output/). Exiting.")
        write_log(start, 0, 0, {})
        return

    for src in sources:
        content = fetch_source(src)
        if content is None:
            source_stats[src] = "fetch_failed"
            continue
        entries = parse_m3u(content)
        added = 0
        for extinf, url in entries:
            key = get_tvg_id(extinf) or url.strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged_entries.append((extinf, url.strip()))
            added += 1
        source_stats[src] = f"ok_added={added}"
        print(f"[INFO] Source {src} -> entries found {len(entries)}, added {added}")

    # write output/kaku.m3u
    header = "#EXTM3U"
    try:
        with open(KAKU_PATH, 'w', encoding='utf-8') as out:
            out.write(header + '\n')
            for extinf, url in merged_entries:
                out.write(extinf + '\n')
                out.write(url + '\n')
        print(f"[INFO] Wrote {len(merged_entries)} entries to {KAKU_PATH}")
    except Exception as e:
        print(f"[ERROR] Failed to write {KAKU_PATH}: {e}", file=sys.stderr)
        write_log(start, 0, 0, source_stats)
        raise

    # write merge log
    write_log(start, len(merged_entries), len(sources), source_stats)

def write_log(start_dt, total_entries, total_sources, source_stats):
    lines = []
    now = datetime.utcnow()
    lines.append(f"merge_time_utc: {now.isoformat()}Z")
    lines.append(f"run_started_utc: {start_dt.isoformat()}Z")
    lines.append(f"total_sources: {total_sources}")
    lines.append(f"total_entries_written: {total_entries}")
    lines.append("")
    lines.append("source_status:")
    for src, st in source_stats.items():
        lines.append(f" - {src} : {st}")
    lines.append("")
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as lf:
            lf.write("\n".join(lines) + "\n" + ("-"*40) + "\n")
        print(f"[INFO] Appended merge log to {LOG_PATH}")
    except Exception as e:
        print(f"[WARN] Could not write log: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
