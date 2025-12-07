import requests
import re
import time
import os

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

# Only these playlists included (jcinema, jtv removed)
SOURCES = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u"
]

WANT_VLC_OPT = True

# --------------------------
# HELPERS
# --------------------------

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        return r.text if r.status_code == 200 else ""
    except:
        return ""


def parse_m3u(content):
    lines = content.strip().splitlines()
    out = []

    current_inf = None
    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            current_inf = line
        elif current_inf and not line.startswith("#"):
            out.append((current_inf, line))
            current_inf = None

    return out


def merge_playlists():
    merged = []
    print("Merge started:", time.ctime())

    for src in SOURCES:
        print("Fetching:", src)
        text = fetch(src)
        if not text:
            print("Failed → skipping")
            continue

        items = parse_m3u(text)
        print(" →", len(items), "streams")

        for extinf, url in items:
            final_url = url.strip()

            # EXTINF
            merged.append(extinf)

            # VLC UA Line (always next line)
            if WANT_VLC_OPT:
                merged.append(f"#EXTVLCOPT:http-user-agent={VLC_USER_AGENT}")

            # Stream URL
            merged.append(final_url)

    return merged


# --------------------------
# MAIN
# --------------------------

def save_output(lines):
    folder = os.path.dirname(OUTPUT_FILE)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for line in lines:
            f.write(line + "\n")


def main():
    merged = merge_playlists()
    save_output(merged)
    print("Done. Total entries:", len(merged))


if __name__ == "__main__":
    main()
