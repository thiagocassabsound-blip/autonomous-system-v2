#!/usr/bin/env python3
"""GTA clip maker: find highlight candidates in a local video, then render vertical clips with a hook.

Usage:
  python3 clipper.py find   VIDEO --credit "Streamer name" --source-url URL [--n 8] [--out work/NAME]
  (review work/NAME/candidates.json + frames/, write a hook per candidate)
  python3 clipper.py render work/NAME/candidates.json VIDEO
Needs ffmpeg + numpy. Every clip records source URL and credit in manifest.json.
"""
import argparse, json, re, subprocess, sys, textwrap
from pathlib import Path
import numpy as np

FONT = next((p for p in ["/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                         "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                         "C:/Windows/Fonts/arialbd.ttf"] if Path(p).exists()), "")
SR = 16000

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)

def duration(video):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video]).stdout
    return float(out.decode().strip())

def loudness(video, step=0.5):
    raw = run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = int(SR * step)
    k = len(a) // n
    rms = np.sqrt((a[: k * n].reshape(k, n) ** 2).mean(axis=1) + 1e-10)
    return 20 * np.log10(rms)

def scene_times(video, thr=0.3):
    p = subprocess.run(["ffmpeg", "-i", video, "-vf", f"select='gt(scene,{thr})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", p.stderr)]

def find(a):
    video, step = a.video, 0.5
    out = Path(a.out or f"work/{Path(video).stem}"); (out / "frames").mkdir(parents=True, exist_ok=True)
    total = duration(video)
    db = loudness(video, step)
    z = (db - db.mean()) / (db.std() + 1e-6)
    w = int(3 / step)
    score = np.convolve(z, np.ones(w) / w, mode="same")           # 3 s smoothed loudness (z-score)
    sc = np.zeros_like(score)
    for t in scene_times(video):
        i = int(t / step)
        if i < len(sc): sc[max(0, i - w): i + w] += 0.15           # visual activity bonus
    score = score + np.minimum(sc, 1.5)
    cands, used = [], np.zeros(len(score), bool)
    for i in np.argsort(-score):
        t = i * step
        if used[max(0, i - int(a.gap / step)): i + int(a.gap / step)].any(): continue
        start = max(0.0, min(t - a.lead, total - a.length)); dur = min(a.length, total - start)
        if dur < 6: continue
        cands.append({"id": len(cands) + 1, "start": round(start, 1), "dur": round(dur, 1),
                      "score": round(float(score[i]), 2), "hook": "", "title": ""})
        used[max(0, i - int(a.gap / step)): i + int(a.gap / step)] = True
        if len(cands) >= a.n: break
    for c in cands:   # 3 frames per candidate so the hook can be written from what is on screen
        for j, f in enumerate((0.2, 0.5, 0.8)):
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(c["start"] + c["dur"] * f), "-i", video,
                 "-frames:v", "1", "-vf", "scale=480:-1", str(out / "frames" / f"c{c['id']:02d}_{j}.jpg")])
    json.dump({"video": video, "credit": a.credit, "source_url": a.source_url, "clips": cands},
              open(out / "candidates.json", "w"), indent=2, ensure_ascii=False)
    print(f"{len(cands)} candidates -> {out}/candidates.json (fill in 'hook' and 'title', then run render)")

def render(a):
    cj = Path(a.candidates); data = json.load(open(cj)); out = cj.parent / "clips"; out.mkdir(exist_ok=True)
    manifest = []
    for c in data["clips"]:
        if not c["hook"].strip(): continue
        hook = "\n".join(textwrap.wrap(c["hook"].upper(), 18))
        (out / f"h{c['id']}.txt").write_text(hook, encoding="utf-8")
        (out / f"c{c['id']}.txt").write_text(f"Source: {data['credit']}", encoding="utf-8")
        fp = f"fontfile={FONT}:" if FONT else ""
        vf = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30[bg];"
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v];"
              f"[v]drawtext={fp}textfile={out}/h{c['id']}.txt:fontsize=84:fontcolor=white:borderw=6:bordercolor=black:"
              "line_spacing=12:x=(w-text_w)/2:y=170:enable='lt(t,4)',"
              f"drawtext={fp}textfile={out}/c{c['id']}.txt:fontsize=34:fontcolor=white@0.9:borderw=3:bordercolor=black:"
              "x=(w-text_w)/2:y=h-120[o]")
        dst = out / f"clip{c['id']:02d}.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(c["start"]), "-t", str(c["dur"]), "-i", a.video,
             "-filter_complex", vf, "-map", "[o]", "-map", "0:a?", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)])
        manifest.append({"file": dst.name, "title": c["title"] or c["hook"], "hook": c["hook"],
                         "credit": data["credit"], "source_url": data["source_url"],
                         "source_start": c["start"], "duration": c["dur"]})
    json.dump(manifest, open(out / "manifest.json", "w"), indent=2, ensure_ascii=False)
    print(f"rendered {len(manifest)} clips -> {out}")

if __name__ == "__main__":
    p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
    f = s.add_parser("find"); f.add_argument("video"); f.add_argument("--credit", required=True)
    f.add_argument("--source-url", required=True); f.add_argument("--n", type=int, default=8)
    f.add_argument("--length", type=float, default=25); f.add_argument("--lead", type=float, default=12)
    f.add_argument("--gap", type=float, default=30); f.add_argument("--out"); f.set_defaults(fn=find)
    r = s.add_parser("render"); r.add_argument("candidates"); r.add_argument("video"); r.set_defaults(fn=render)
    a = p.parse_args(); a.fn(a)
