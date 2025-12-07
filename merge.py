# merge.py
# Debug-friendly merge script for GitHub Actions
import requests, time, traceback, os

sources = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jcinema.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jtv.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AutoMergeBot/1.0)",
    "Accept": "*/*"
}

os.makedirs("output", exist_ok=True)
log_lines = []
merged_lines = ["#EXTM3U"]

def log(s):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{ts} - {s}"
    print(entry)
    log_lines.append(entry)

for idx, url in enumerate(sources, start=1):
    try:
        log(f"Fetching ({idx}/{len(sources)}) {url}")
        r = requests.get(url, headers=HEADERS, timeout=20)
        status = r.status_code
        log(f"Status: {status} (len={len(r.text) if r.status_code==200 else 'N/A'})")
        if r.status_code == 200:
            data = r.text
            added = 0
            for line in data.splitlines():
                line = line.rstrip()
                if line != "":
                    merged_lines.append(line)
                    added += 1
            log(f"Added {added} non-empty lines from source #{idx}")
        else:
            log(f"Non-200 response for {url}: {status}")
    except Exception as e:
        log(f"Error fetching {url}: {e}")
        log(traceback.format_exc())

# If nothing was added besides header, write a helpful note
if len(merged_lines) <= 1:
    merged_lines.append("# NOTE: No channels merged. Check action logs (output/merge_log.txt) for fetch errors.")
    log("No channels merged; wrote note to output file.")

# Write merged output
out_path = "output/kaku.m3u"
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(merged_lines))
log(f"Wrote merged playlist to {out_path} (lines={len(merged_lines)})")

# Write debug log
log_path = "output/merge_log.txt"
with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))
log(f"Wrote debug log to {log_path}")

# Exit
print("Done.")
