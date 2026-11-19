#!/usr/bin/env python3
"""Upload rendered clips (manifest.json) to YouTube. Description always carries source credit + link.
Setup: pip install google-api-python-client google-auth-oauthlib ; put OAuth client file at client_secret.json
Usage: python3 upload.py work/NAME/clips [--public] [--publish-at 2026-11-21T12:00:00Z]
Default privacy is private (unaudited API projects are forced private anyway)."""
import argparse, json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

p = argparse.ArgumentParser(); p.add_argument("clips_dir"); p.add_argument("--public", action="store_true")
p.add_argument("--publish-at"); a = p.parse_args()
creds = InstalledAppFlow.from_client_secrets_file("client_secret.json",
        ["https://www.googleapis.com/auth/youtube.upload"]).run_local_server(port=0)
yt = build("youtube", "v3", credentials=creds)
d = Path(a.clips_dir)
for m in json.load(open(d / "manifest.json")):
    body = {"snippet": {"title": m["title"][:95] + " #shorts #gta6",
                        "description": f"{m['hook']}\n\nCredit: {m['credit']}\nOriginal: {m['source_url']}\n\n#GTA6 #GTAVI #shorts",
                        "tags": ["GTA 6", "GTA VI", "gta6 gameplay", "shorts"], "categoryId": "20"},
            "status": {"privacyStatus": "public" if a.public and not a.publish_at else "private",
                       "selfDeclaredMadeForKids": False}}
    if a.publish_at:
        body["status"]["privacyStatus"] = "private"; body["status"]["publishAt"] = a.publish_at
    r = yt.videos().insert(part="snippet,status", body=body,
                           media_body=MediaFileUpload(str(d / m["file"]), resumable=True)).execute()
    print("uploaded", m["file"], "->", r["id"])
