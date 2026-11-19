#!/usr/bin/env python3
"""Fetch new gameplay videos from channels listed in channels.txt (one channel/playlist URL per line),
download them, and run `clipper.py find` on each. Skips videos already done (done.txt).
Usage: python3 fetch.py [--per-channel 2] [--min-minutes 10] [--max-minutes 240] [--n 8]
Needs yt-dlp + ffmpeg on PATH. Credit = channel name, source URL = video URL (kept in manifest)."""
import argparse, json, subprocess, sys
from pathlib import Path

p = argparse.ArgumentParser(); p.add_argument("--per-channel", type=int, default=2)
p.add_argument("--min-minutes", type=int, default=10); p.add_argument("--max-minutes", type=int, default=240)
p.add_argument("--n", type=int, default=8); a = p.parse_args()
done = Path("done.txt"); seen = set(done.read_text().split()) if done.exists() else set()
Path("videos").mkdir(exist_ok=True)
for ch in [l.strip() for l in open("channels.txt") if l.strip() and not l.startswith("#")]:
    flt = f"duration>{a.min_minutes*60} & duration<{a.max_minutes*60} & title~=(?i)gta"
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", "15", "--match-filter", flt,
                        "--print", "%(id)s\t%(uploader)s\t%(webpage_url)s", ch], capture_output=True, text=True)
    new = [l.split("\t") for l in r.stdout.splitlines() if l.split("\t")[0] not in seen][: a.per_channel]
    for vid, who, url in new:
        f = f"videos/{vid}.mp4"
        subprocess.run(["yt-dlp", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "-o", f, url], check=True)
        subprocess.run([sys.executable, "clipper.py", "find", f, "--credit", who, "--source-url", url, "--n", str(a.n)], check=True)
        done.open("a").write(vid + "\n")
        print(f"READY: work/{vid}/candidates.json  ({who})")
