#!/usr/bin/env python3
"""
merge.py - Merge sources into output/kaku.m3u and set group-title per source (playlist name).

Behavior:
- Reads sources from sources.txt (one per line).
- For each source (URL or local file), extract a group name from the source filename/path.
- Parse #EXTINF / URL entries, ensure each EXTINF contains group-title="GroupName" (replace if present).
- Deduplicate entries by tvg-id (if present) or by stream URL.
- Write output/kaku.m3u and append a small merge log.
"""

from pathlib import Path
import re
import os
import sys
from datetime import datetime
from urllib.parse import urlparse, unquote

try:
    import requests
except Exception:
    print("Please install requests: pip install requests", file=sys.stderr)
    raise

ROOT = Path(__file__).parent.resolve()
SOURCES_FILE = ROOT / "sources.txt"
OUTPUT_DIR = ROOT / "output"
KAKU_PATH = OUTPUT_DIR / "kaku.m3u"
LOG_PATH = OUTPUT_DIR / "merge_log.txt"

TVGID_RE = re.compile(r'tvg-id="([^"]+)"', flags=re.IGNORECASE)

def load_sources():
    if not SOURCES_FILE.exists():
        return []
    lines = []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            lines.append(s)
    return lines

def fetch_source(src):
    if src.lower().startswith(("http://", "https://")):
        try:
            resp = requests.get(src, timeout=20, headers={"User-Agent":"merge.py/1.0"})
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"[WARN] Failed to fetch {src}: {e}")
            return None
    else:
        p = Path(src)
        if not p.is_absolute():
            p = (ROOT / src).resolve()
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"[WARN] Failed to read {p}: {e}")
            return None

def group_name_from_source(src):
    # derive a friendly name from the URL/file path last segment
    try:
        if src.lower().startswith(("http://", "https://")):
            u = urlparse(src)
            last = unquote(Path(u.path).name or u.netloc)
        else:
            last = Path(src).name
        name = Path(last).stem
        # cleanup
        name = re.sub(r'[_\-]+', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        if not name:
            name = "Playlist"
        return name
    except Exception:
        return "Playlist"

def parse_entries(content):
    """
    Return list of (extinf_line, url_line) parsed from content.
    Only pairs where url_line is present are returned.
    """
    lines = [l.rstrip("\n") for l in content.splitlines()]
    entries = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln.upper().startswith("#EXTINF"):
            extinf = ln
            j = i + 1
            url = None
            # find first non-empty, non-comment line after extinf
            while j < len(lines):
                cand = lines[j].strip()
                if not cand:
                    j += 1
                    continue
                if cand.startswith("#"):
                    j += 1
                    continue
                url = cand
                break
            if url:
                entries.append((extinf, url))
                i = j + 1
            else:
                i += 1
        else:
            i += 1
    return entries

def ensure_group_in_extinf(extinf, group):
    """
    Ensure extinf contains group-title="group". If existing group-title present, replace its value.
    extinf is like: #EXTINF:-1 tvg-id="..." ,Channel
    We will split at first comma to preserve channel name.
    """
    if ',' in extinf:
        header, rest = extinf.split(',', 1)
        header = header.strip()
        rest = rest  # channel display name (keep as-is)
    else:
        header = extinf
        rest = ""

    # if group-title exists, replace value
    if re.search(r'group-title\s*=', header, flags=re.IGNORECASE):
        header = re.sub(r'group-title\s*=\s*"[^"]*"', f'group-title="{group}"', header, flags=re.IGNORECASE)
    else:
        # insert group-title before end of header
        header = header + f' group-title="{group}"'
    if rest:
        return header + ',' + rest
    else:
        return header

def get_tvg_id(extinf):
    m = TVGID_RE.search(extinf)
    if m:
        return m.group(1).strip()
    return None

def write_log(sources, stats, total_entries):
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(f"run_utc: {datetime.utcnow().isoformat()}Z\n")
            lf.write(f"sources_count: {len(sources)}\n")
            lf.write(f"entries_written: {total_entries}\n")
            for s, st in stats.items():
                lf.write(f" - {s} : {st}\n")
            lf.write("-"*40 + "\n")
    except Exception as e:
        print(f"[WARN] Could not write log: {e}")

def main():
    sources = load_sources()
    if not sources:
        print("[ERROR] No sources found in sources.txt")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged = []
    seen = set()
    stats = {}

    for src in sources:
        print(f"[INFO] Processing source: {src}")
        content = fetch_source(src)
        if not content:
            stats[src] = "fetch_failed"
            continue
        grp = group_name_from_source(src)
        entries = parse_entries(content)
        added = 0
        for extinf, url in entries:
            # ensure url is trimmed
            url = url.strip()
            # add/replace group-title
            extinf2 = ensure_group_in_extinf(extinf, grp)
            # dedupe key
            key = get_tvg_id(extinf2) or url
            if key in seen:
                continue
            seen.add(key)
            merged.append((extinf2, url))
            added += 1
        stats[src] = f"ok_added={added}"
        print(f"[INFO] Source {src} -> found {len(entries)} entries, added {added}")

    # write output file
    try:
        with open(KAKU_PATH, "w", encoding="utf-8") as outf:
            outf.write("#EXTM3U\n")
            for extinf, url in merged:
                outf.write(extinf + "\n")
                outf.write(url + "\n")
        print(f"[INFO] Wrote {len(merged)} entries to {KAKU_PATH}")
    except Exception as e:
        print(f"[ERROR] Failed to write {KAKU_PATH}: {e}")
        return 1

    write_log(sources, stats, len(merged))
    return 0

if __name__ == "__main__":
    sys.exit(main())
