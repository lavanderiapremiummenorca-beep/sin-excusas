# -*- coding: utf-8 -*-
"""
Sube el ultimo video generado a una carpeta de Google Drive, para que
Repurpose lo detecte y lo publique en TikTok + Instagram.
Credenciales de Drive por variables de entorno:
  GDRIVE_CLIENT_ID / GDRIVE_CLIENT_SECRET  (si no estan, usa YT_CLIENT_ID / YT_CLIENT_SECRET)
  GDRIVE_REFRESH_TOKEN   (token con scope drive)
  GDRIVE_FOLDER_ID       (carpeta destino en Drive)
Si falta algo, no hace nada (no rompe el flujo).
"""
import os

def main():
    client_id = os.environ.get("GDRIVE_CLIENT_ID") or os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET") or os.environ.get("YT_CLIENT_SECRET")
    refresh = os.environ.get("GDRIVE_REFRESH_TOKEN")
    folder = os.environ.get("GDRIVE_FOLDER_ID")
    if not (client_id and client_secret and refresh and folder):
        print("[drive] faltan datos de Drive (cliente/token/carpeta); me salto la subida a Drive.")
        return

    BASE = os.path.dirname(os.path.abspath(__file__))
    OUTPUT = os.path.join(BASE, "output")
    latest = os.path.join(OUTPUT, "_latest.txt")
    if not os.path.exists(latest):
        print("[drive] no hay output/_latest.txt; nada que subir.")
        return
    vid_id = open(latest, encoding="utf-8").read().strip()
    path = os.path.join(OUTPUT, f"{vid_id}.mp4")
    if not os.path.exists(path):
        print(f"[drive] no existe {path}; nada que subir.")
        return

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None, refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    drv = build("drive", "v3", credentials=creds)
    meta = {"name": f"{vid_id}.mp4", "parents": [folder]}
    media = MediaFileUpload(path, mimetype="video/mp4", resumable=True)
    f = drv.files().create(body=meta, media_body=media,
                           supportsAllDrives=True, fields="id").execute()
    print(f"[drive] subido a Drive OK (id={f.get('id')})")

if __name__ == "__main__":
    main()
