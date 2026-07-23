# -*- coding: utf-8 -*-
"""
(OPCIONAL) Consigue tu YT_REFRESH_TOKEN desde tu ordenador.
Alternativa al método por navegador (OAuth Playground) explicado en la guía.

Uso:
  1) pip install google-auth-oauthlib
  2) Descarga el JSON de credenciales OAuth (tipo "Aplicación de escritorio")
     desde Google Cloud y guárdalo como client_secret.json junto a este archivo.
  3) python get_token.py
  4) Se abrirá el navegador, autorizas tu cuenta, y te imprime el refresh token.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    print("\n==== COPIA ESTO EN TUS SECRETS DE GITHUB ====")
    print("YT_CLIENT_ID     =", creds.client_id)
    print("YT_CLIENT_SECRET =", creds.client_secret)
    print("YT_REFRESH_TOKEN =", creds.refresh_token)

if __name__ == "__main__":
    main()
