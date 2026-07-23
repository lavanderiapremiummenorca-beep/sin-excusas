# -*- coding: utf-8 -*-
"""
Sube a YouTube el último vídeo generado, usando la API de datos de YouTube.
Credenciales por variables de entorno (secrets de GitHub):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Opcionales:
  YT_PRIVACY  = public | unlisted | private   (por defecto: public)
  YT_CATEGORY = id de categoría               (por defecto: 27 = Educación)
"""
import os, sys, json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE, "output")

def load_meta():
    latest = os.path.join(OUTPUT, "_latest.txt")
    if not os.path.exists(latest):
        sys.exit("No hay vídeo generado (falta output/_latest.txt).")
    vid_id = open(latest, encoding="utf-8").read().strip()
    meta_path = os.path.join(OUTPUT, f"{vid_id}.json")
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)

def main():
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k):
            sys.exit(f"Falta el secret {k}.")

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    yt = build("youtube", "v3", credentials=creds)

    meta = load_meta()
    video_file = meta["video"]
    if not os.path.exists(video_file):
        sys.exit(f"No existe el archivo de vídeo: {video_file}")

    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"][:4900],
            "tags": meta.get("tags", [])[:15],
            "categoryId": os.environ.get("YT_CATEGORY", "27"),
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"[upload] subiendo: {meta['title']}")
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
    vid = resp.get("id")
    print(f"[upload] OK -> https://youtube.com/watch?v={vid}")

if __name__ == "__main__":
    main()
