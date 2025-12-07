import requests

sources = [
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jcinema.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/jtv.m3u",
    "https://raw.githubusercontent.com/alex8875/m3u/refs/heads/main/z5.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyChannelsPlaylist/refs/heads/main/sony.m3u",
    "https://raw.githubusercontent.com/abid58b/SonyLivPlayList/refs/heads/main/sonyliv.m3u",
    "https://raw.githubusercontent.com/abid58b/FanCodePlaylist/refs/heads/main/fancode.m3u"
]

output = "#EXTM3U\n"

for url in sources:
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            data = r.text
            for line in data.splitlines():
                if line.strip() != "":
                    output += line + "\n"
    except Exception as e:
        print("Error fetching:", url, e)

with open("output/kaku.m3u", "w", encoding="utf-8") as f:
    f.write(output)

print("Merged playlist saved to output/kaku.m3u")
