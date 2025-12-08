import requests
import re
import time
import os
import json
import tempfile
from pathlib import Path

# --------------------------
# SETTINGS
# --------------------------

OUTPUT_FILE = "output/kaku.m3u"
VLC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 ygx/69.1 Safari/537.36"
)

HEADERS = {
    "User-Agent": VLC_USER_AGENT
}

SOURCES = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u"
]

WANT_VLC_OPT = True

# Path to optional cookies json. If present and has "cookie" value, will replace {{COOKIE}} placeholder in URLs.
COOKIES_JSON = "cookies.json"

# default group title if missing
DEFAULT_GROUP = "Unknown"

# --------------------------
# HELPERS
# --------------------------

def fetch(url, timeout=20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        return r.text if r.status_code == 200 else ""
    except Exception as e:
        print("  fetch error:", e)
        return ""


# parse EXTINF attributes into dict and title
_attr_re = re.compile(r'(\w[\w-]*)="([^"]*)"')
_extinf_re = re.compile(r'^#EXTINF:(-?\d+)\s*(.*?),(.*)$', re.IGNORECASE)

def parse_m3u(content):
    """
    Returns list of tuples: (attrs_dict, raw_attr_str, display_title, stream_url, raw_extinf_line)
    """
    lines = content.splitlines()
    out = []
    current_extinf = None
    raw_extinf_line = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.upper().startswith("#EXTINF"):
            m = _extinf_re.match(line)
            if m:
                duration = m.group(1)
                attr_part = m.group(2).strip()
                title = m.group(3).strip()
                # parse attributes
                attrs = dict(_attr_re.findall(attr_part))
                current_extinf = {
                    "duration": duration,
                    "attrs": attrs,
                    "title": title,
                    "raw_attr_part": attr_part
                }
                raw_extinf_line = line
            else:
                # fallback: keep whole line as raw_extinf
                current_extinf = {"duration": None, "attrs": {}, "title": line, "raw_attr_part": ""}
                raw_extinf_line = line
        elif current_extinf and not line.startswith("#"):
            url = line.strip()
            out.append((current_extinf["attrs"], current_extinf["raw_attr_part"], current_extinf["title"], url, raw_extinf_line))
            current_extinf = None
            raw_extinf_line = None
        else:
            # ignore other comment lines
            continue

    return out


def build_extinf_line(attrs, title, duration="-1"):
    """
    Rebuilds a clean EXTINF line using attrs dict (preserves keys) and title.
    Ensures group-title exists.
    """
    attrs = dict(attrs)  # copy
    if "group-title" not in attrs or not attrs.get("group-title"):
        attrs["group-title"] = DEFAULT_GROUP

    # keep attribute order somewhat stable: prefer known keys order
    preferred_order = ["tvg-id", "tvg-name", "tvg-logo", "group-title"]
    parts = []
    # add preferred order if present
    for k in preferred_order:
        if k in attrs:
            parts.append(f'{k}="{attrs[k]}"')
    # add remaining attributes
    for k, v in attrs.items():
        if k not in preferred_order:
            parts.append(f'{k}="{v}"')

    attr_str = " ".join(parts)
    return f'#EXTINF:{duration} {attr_str},{title}'


def load_cookies_value(path):
    """
    Expects cookies.json to be a JSON object. Tries common keys and returns a string (or None).
    Example: {"cookie": "__hdnea__=st=..."}
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # try some common keys
        for key in ("cookie", "Cookie", "value", "token", "hdnea"):
            if key in data and isinstance(data[key], str) and data[key].strip():
                return data[key].strip()
        # if single string in file
        if isinstance(data, str):
            return data.strip()
    except Exception as e:
        print("Warning: failed to load cookies.json:", e)
    return None


def replace_cookie_placeholder(url, cookie_value):
    """
    Replace placeholder(s) in url with cookie_value.
    Recognizes placeholder {{COOKIE}}.
    If no placeholder but cookie_value present and url contains patterns like __hdnea__= or requires cookie param,
    user needs to include placeholder in source. We will only replace {{COOKIE}} to avoid accidental modification.
    """
    if not cookie_value:
        return url
    if "{{COOKIE}}" in url:
        return url.replace("{{COOKIE}}", cookie_value)
    return url


# --------------------------
# MERGE
# --------------------------

def merge_playlists(cookie_value=None):
    merged = []
    total_streams = 0
    print("Merge started:", time.ctime())

    for idx, src in enumerate(SOURCES, start=1):
        print(f"[{idx}/{len(SOURCES)}] Fetching:", src)
        text = fetch(src)
        if not text:
            print("  Failed → skipping")
            continue

        items = parse_m3u(text)
        print("  →", len(items), "streams")
        total_streams += len(items)

        for attrs, raw_attr_str, title, url, raw_extinf in items:
            final_url = url.strip()
            # Replace cookie placeholder if present
            final_url = replace_cookie_placeholder(final_url, cookie_value)

            # Rebuild EXTINF line, ensure group-title present
            extinf_line = build_extinf_line(attrs, title)

            merged.append(extinf_line)
            if WANT_VLC_OPT:
                merged.append(f"#EXTVLCOPT:http-user-agent={VLC_USER_AGENT}")
            merged.append(final_url)

    return merged, total_streams


# --------------------------
# SAVE (only if changed)
# --------------------------

def save_output_if_changed(lines, path):
    header = "#EXTM3U\n"
    content = header + "\n".join(lines) + "\n"

    # ensure folder
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

    # if file exists and same content, do nothing
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = f.read()
            if old == content:
                print("No changes detected — output not overwritten.")
                return False
        except Exception as e:
            print("Warning reading existing output:", e)

    # write atomically
    fd, tmp_path = tempfile.mkstemp(prefix="tmp_m3u_", dir=folder or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            tf.write(content)
        # move to final path
        Path(tmp_path).replace(path)
        print("Output written to", path)
        return True
    except Exception as e:
        print("Failed to write output:", e)
        # cleanup
        try:
            os.remove(tmp_path)
        except:
            pass
        return False


# --------------------------
# MAIN
# --------------------------

def main():
    cookie_value = load_cookies_value(COOKIES_JSON)
    if cookie_value:
        print("Loaded cookie value from", COOKIES_JSON, "(length:", len(cookie_value), ")")
    else:
        print("No cookies.json or cookie value found — cookie placeholder won't be replaced.")

    merged_lines, total_streams = merge_playlists(cookie_value=cookie_value)
    changed = save_output_if_changed(merged_lines, OUTPUT_FILE)
    print("Done. Streams found:", total_streams, "Lines written:", len(merged_lines), "Changed:", changed)


if __name__ == "__main__":
    main()
