#!/usr/bin/env python3
"""
merge.py - Merge sources into output/kaku.m3u and set group-title per source.

Features:
 - Preserves #EXTVLCOPT lines found between EXTINF and the URL.
 - Forces a single http-user-agent for every entry via DEFAULT_USER_AGENT.
 - Dedupes by tvg-id or normalized URL.

Usage:
 - Put one source per line in sources.txt (HTTP(s) or local file paths).
 - Run: python3 merge.py
Outputs:
 - output/kaku.m3u
 - output/merge_log.txt
"""

from pathlib import Path
import re
import os
import sys
from datetime import datetime
from urllib.parse import urlparse, unquote, urljoin, urlunparse, parse_qsl, urlencode

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

# Force this UA on every entry
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 ygx/69.1 Safari/537.36"

TVGID_RE = re.compile(r'tvg-id\s*=\s*"([^\"]*)"', flags=re.IGNORECASE)
GROUP_RE = re.compile(r'group-title\s*=\s*"([^\"]*)"', flags=re.IGNORECASE)
EXTINF_RE = re.compile(r'^\s*#EXTINF', flags=re.IGNORECASE)
EXTVLCOPT_RE = re.compile(r'^\s*#EXTVLCOPT\s*:\s*(.*)$', flags=re.IGNORECASE)
USER_AGENT_OPT_RE = re.compile(r'http-user-agent\s*=\s*(.*)', flags=re.IGNORECASE)

# params considered "auth-like" to drop from URL when normalizing for dedupe
AUTH_QUERY_KEYS = {"token", "auth", "st", "exp", "sig", "signature", "access_token", "expires"}


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
    """
    Returns tuple (text, base_url_or_none).
    base_url_or_none is useful to resolve relative stream URLs.
    """
    if src.lower().startswith(("http://", "https://")):
        try:
            resp = requests.get(src, timeout=25, headers={"User-Agent": "merge.py/1.0 (+https://example)"})
            resp.raise_for_status()
            text = resp.text
            base = resp.url  # final URL after redirects
            return text, base
        except Exception as e:
            print(f"[WARN] Failed to fetch {src}: {e}")
            return None, None
    else:
        p = Path(src)
        if not p.is_absolute():
            p = (ROOT / src).resolve()
        try:
            try:
                txt = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                txt = p.read_text(encoding="utf-8", errors="replace")
            return txt, None
        except Exception as e:
            print(f"[WARN] Failed to read {p}: {e}")
            return None, None


def group_name_from_source(src):
    try:
        if src.lower().startswith(("http://", "https://")):
            u = urlparse(src)
            last = unquote(Path(u.path).name or u.netloc)
        else:
            last = Path(src).name
        name = Path(last).stem
        name = re.sub(r'[_\-]+', ' ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        if not name:
            name = "Playlist"
        return name
    except Exception:
        return "Playlist"


def parse_entries(content):
    """
    Return list of (extinf_line_or_None, options_list, url_line) parsed from content.
    options_list: list of strings (the full #EXTVLCOPT:... lines) found between EXTINF and the URL
    If a URL appears without a preceding EXTINF, extinf will be None and options_list may be empty.
    """
    lines = [l.rstrip("\n") for l in content.splitlines()]
    entries = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue
        if ln.startswith("#"):
            if EXTINF_RE.match(ln):
                extinf = ln
                options = []
                # find next non-empty line that is not a comment (or collect EXTVLCOPT comments)
                j = i + 1
                url = None
                while j < len(lines):
                    cand = lines[j].rstrip("\n")
                    cand_stripped = cand.strip()
                    if not cand_stripped:
                        j += 1
                        continue
                    # collect EXTVLCOPT lines (they might include http-user-agent)
                    mopt = EXTVLCOPT_RE.match(cand_stripped)
                    if mopt:
                        options.append(cand_stripped)
                        j += 1
                        continue
                    if cand_stripped.startswith("#"):
                        j += 1
                        continue
                    url = cand_stripped
                    break
                if url:
                    entries.append((extinf, options, url))
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1
        else:
            entries.append((None, [], ln))
            i += 1
    return entries


def ensure_group_in_extinf(extinf, group):
    """
    Ensure an extinf line contains group-title="group".
    If extinf is None, create a generic EXTINF.
    """
    if extinf is None:
        return f'#EXTINF:-1 group-title="{group}",'
    if ',' in extinf:
        header, rest = extinf.split(',', 1)
        header = header.strip()
        rest = rest
    else:
        header = extinf.strip()
        rest = ""
    if GROUP_RE.search(header):
        header = GROUP_RE.sub(lambda m: f'group-title="{group}"', header)
    else:
        header = header + f' group-title="{group}"'
    if rest != "":
        return header + ',' + rest
    else:
        return header


def get_tvg_id(extinf):
    if not extinf:
        return None
    m = TVGID_RE.search(extinf)
    if m:
        val = m.group(1).strip()
        return val if val else None
    return None


def normalize_url_for_dedupe(url, base=None):
    url = url.strip()
    if base and not urlparse(url).scheme:
        url = urljoin(base, url)
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    q = parse_qsl(parsed.query, keep_blank_values=True)
    q_filtered = [(k, v) for (k, v) in q if k.lower() not in AUTH_QUERY_KEYS]
    q_filtered.sort()
    query = urlencode(q_filtered, doseq=True)
    path = parsed.path or ""
    path = re.sub(r'/+', '/', path)
    new = urlunparse((scheme, netloc, path, "", query, ""))
    if new.endswith('/') and len(new) > 1:
        new = new.rstrip('/')
    return new


def make_user_agent_option(options, override_ua=None):
    """
    Given list of existing EXT options (strings like '#EXTVLCOPT:http-user-agent=...'),
    return a list where the http-user-agent is replaced/added according to override_ua.
    If override_ua is None, return options unchanged.
    """
    if override_ua is None:
        return options[:]
    ua_line = f'#EXTVLCOPT:http-user-agent={override_ua}'
    out = []
    replaced = False
    for opt in options:
        m = EXTVLCOPT_RE.match(opt)
        if m:
            content = m.group(1)
            if USER_AGENT_OPT_RE.search(content):
                out.append(ua_line)
                replaced = True
                continue
        out.append(opt)
    if not replaced:
        out.insert(0, ua_line)
    return out


def write_log(sources, stats, total_entries):
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(f"run_utc: {datetime.utcnow().isoformat()}Z\n")
            lf.write(f"run_local: {datetime.now().isoformat()}\n")
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
        content, base = fetch_source(src)
        if content is None:
            stats[src] = "fetch_failed"
            continue
        grp = group_name_from_source(src)
        entries = parse_entries(content)
        added = 0
        total_found = len(entries)
        for extinf, options, url in entries:
            url = url.strip()
            if not url:
                continue
            norm_url_for_key = normalize_url_for_dedupe(url, base=base)
            extinf2 = ensure_group_in_extinf(extinf, grp)
            tvgid = get_tvg_id(extinf2)
            key = tvgid if tvgid else norm_url_for_key
            if key in seen:
                continue
            seen.add(key)
            opts_final = make_user_agent_option(options, override_ua=DEFAULT_USER_AGENT)
            if extinf is None:
                display = Path(urlparse(urljoin(base or "", url)).path).stem or ""
                display = re.sub(r'[_\-]+', ' ', display).strip()
                if display:
                    extinf2 = extinf2.rstrip(',') + f'{display}'
            merged.append((extinf2, opts_final, url))
            added += 1
        stats[src] = f"ok_found={total_found}_added={added}"
        print(f"[INFO] Source {src} -> found {total_found} entries, added {added}")

    try:
        with open(KAKU_PATH, "w", encoding="utf-8") as outf:
            outf.write("#EXTM3U\n")
            for extinf, opts, url in merged:
                outf.write(extinf + "\n")
                for o in opts:
                    outf.write(o + "\n")
                outf.write(url + "\n")
        print(f"[INFO] Wrote {len(merged)} entries to {KAKU_PATH}")
    except Exception as e:
        print(f"[ERROR] Failed to write {KAKU_PATH}: {e}")
        return 1

    write_log(sources, stats, len(merged))
    print("[INFO] Merge complete. Log appended to", LOG_PATH)
    return 0

if __name__ == "__main__":
    sys.exit(main())
