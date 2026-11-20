#!/usr/bin/env python3
"""Make English captions (.srt) for each clip in candidates.json, to be burned in by `clipper.py render`.
Usage: python3 captions.py work/NAME/candidates.json VIDEO     (pip install faster-whisper; downloads model on first run)"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
from faster_whisper import WhisperModel

cj, video = Path(sys.argv[1]), os.path.abspath(sys.argv[2])
data = json.load(open(cj)); out = cj.parent / "clips"; out.mkdir(exist_ok=True)
model = WhisperModel("small", device="cpu", compute_type="int8")
ts = lambda t: f"{int(t//3600):02d}:{int(t%3600//60):02d}:{int(t%60):02d},{int(t%1*1000):03d}"
for c in data["clips"]:
    if not c["hook"].strip(): continue          # only clips that will be rendered
    with tempfile.TemporaryDirectory() as d:
        wav = f"{d}/a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(c["start"]), "-t", str(c["dur"]), "-i", video,
                        "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        segs, _ = model.transcribe(wav, language="en", word_timestamps=True)
        words = [w for s in segs for w in s.words]
    lines, i = [], 0
    while i < len(words):                      # 3 words per caption, fast-cut style
        g = words[i:i + 3]
        lines.append(f"{len(lines)+1}\n{ts(g[0].start)} --> {ts(g[-1].end)}\n{' '.join(w.word.strip() for w in g).upper()}\n")
        i += 3
    (out / f"clip{c['id']:02d}.srt").write_text("\n".join(lines), encoding="utf-8")
    print(f"clip {c['id']}: {len(lines)} captions")
