# 🤖 Economía Bot — Shorts automáticos y gratis

Genera y publica un Short de economía al día en YouTube, en automático y sin pagar suscripciones.

- **Voz:** edge-tts (neuronal, gratis) en GitHub Actions · espeak-ng (offline) para pruebas locales
- **Vídeo:** ffmpeg (fondo con movimiento + subtítulos sincronizados + gráfica)
- **Subida:** API de datos de YouTube
- **Programador:** GitHub Actions (cron diario), gratis

## Cómo funciona

1. `generate.py` elige el guion del día del banco (`scripts.json`), crea la voz, los subtítulos y monta el vídeo vertical en `output/`.
2. `upload.py` sube ese vídeo a tu canal de YouTube.
3. El workflow `.github/workflows/daily.yml` hace las dos cosas cada día.

## Puesta en marcha

👉 Sigue la **guía paso a paso** (archivo `GUIA-INSTALACION`) que te explica, todo por navegador:
crear las credenciales de la API de YouTube, conseguir el refresh token, subir esto a GitHub, meter los secrets y lanzar el primer vídeo hoy.

## Probar en local (voz de prueba)

```bash
pip install edge-tts        # o usa espeak: sudo apt install espeak-ng
python make_backgrounds.py  # genera los fondos (ya vienen incluidos)
TTS_ENGINE=espeak python generate.py interes-compuesto
```

## Añadir más temas

Abre `scripts.json` y añade otro bloque con el mismo formato. Cuantos más guiones, menos se repite el contenido (mejor para no ser penalizado por YouTube).

## La IA escribe el guion (opcional pero recomendado)

Si añades el secret `GEMINI_API_KEY` (gratis en Google AI Studio), cada día la IA escribe un
guion nuevo siguiendo `PROMPT-MAESTRO.md` (cumplimiento de normas de YouTube + tácticas de
viralidad). Sin esa clave, el bot usa el banco `scripts.json` y lo rota. Edita
`PROMPT-MAESTRO.md` para cambiar el tono, el nicho o las reglas.

## Secrets (en GitHub → Settings → Secrets → Actions)

Obligatorios (subida a YouTube):
- `YT_CLIENT_ID`
- `YT_CLIENT_SECRET`
- `YT_REFRESH_TOKEN`

Opcionales (mejoran el resultado, se activan solos):
- `GEMINI_API_KEY` — la IA escribe el guion cada día (PROMPT-MAESTRO.md)
- `PEXELS_API_KEY` — fondo de vídeo real en vez del degradado

⚠️ Contenido educativo. Esto no es asesoramiento financiero.
