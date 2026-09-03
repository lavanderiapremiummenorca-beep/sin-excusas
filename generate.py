# -*- coding: utf-8 -*-
"""
Generador de Shorts (100% gratis, sin servicios de pago).
Flujo: guion -> voz (edge-tts o espeak) -> subtítulos sincronizados ->
fondo con movimiento -> vídeo vertical 1080x1920.

TTS_ENGINE=edge  -> voz neuronal (para GitHub Actions, buena calidad)
TTS_ENGINE=espeak-> voz offline (prueba de formato en local)
"""
import os, sys, json, subprocess, asyncio, tempfile, textwrap, math, hashlib
import urllib.request, urllib.parse, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
OUTPUT = os.path.join(BASE, "output")
# Carpeta de música: acepta "music" o "musica" (por si se nombró en español)
MUSIC = os.path.join(BASE, "music")
if not os.path.isdir(MUSIC) and os.path.isdir(os.path.join(BASE, "musica")):
    MUSIC = os.path.join(BASE, "musica")
os.makedirs(OUTPUT, exist_ok=True)

TTS_ENGINE = os.environ.get("TTS_ENGINE", "espeak")

# ---------- Control de CALIDAD: no publicar si el video no sale perfecto ----------
# Si STRICT_QUALITY esta activo (por defecto SI), cuando el video del dia no sale
# bien -sin imagenes reales (pantalla lisa de color), o con la voz de reserva
# gratis en vez de ElevenLabs- este script FALLA a proposito. En GitHub Actions,
# al fallar este paso, el trabajo se para y NO se sube nada a YouTube ni a redes.
# Mejor un dia sin video que un video malo publicado.
# Para permitir videos con fallos en un canal, pon  STRICT_QUALITY: "0"  en su daily.yml.
STRICT_QUALITY = os.environ.get("STRICT_QUALITY", "1").strip().lower() not in (
    "0", "false", "no", "off", "")
_CALIDAD_PROBLEMAS = []

def _calidad_flag(motivo):
    _CALIDAD_PROBLEMAS.append(motivo)
    sys.stderr.write("[calidad] PROBLEMA: " + motivo + "\n")

def _calidad_check(fase=""):
    if STRICT_QUALITY and _CALIDAD_PROBLEMAS:
        msg = ("[calidad] NO se publica el video de hoy porque no salio perfecto:\n  - "
               + "\n  - ".join(_CALIDAD_PROBLEMAS)
               + "\n[calidad] (Para permitir videos con fallos en este canal, pon "
                 'STRICT_QUALITY: "0" en su daily.yml.)')
        sys.stderr.write(msg + "\n")
        print(msg)
        raise SystemExit(1)
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-ES-AlvaroNeural")
GAP = 0.07          # (ya no se usa; voz continua)
FONT = "DejaVu Sans"
HANDLE = os.environ.get("CHANNEL_HANDLE", "").strip()  # tu marca en pantalla (vacío = sin marca)
VOICE_VOL = os.environ.get("VOICE_VOL", "1.0")  # volumen de la voz: 1.0 = normal; 0.8 = más bajo/tranquilo

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("CMD FAIL: " + " ".join(cmd[:6]) + "...\n" + r.stderr[-1500:] + "\n")
        # RuntimeError (no SystemExit) para que quien llama pueda capturarlo y
        # tirar del plan B (p.ej. fondo de reserva) en vez de tumbar todo el proceso.
        raise RuntimeError("ffmpeg/cmd falló: " + " ".join(cmd[:3]))
    return r

def dur_of(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def _valid_video(path, min_dur=0.4):
    """True solo si el archivo existe, tiene stream de vídeo y dura lo suficiente.
    Evita usar clips descargados a medias/corruptos (causa de vídeos sin imagen)."""
    try:
        if not (os.path.exists(path) and os.path.getsize(path) > 10000):
            return False
        r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                            "-show_entries","stream=codec_type","-of","csv=p=0", path],
                           capture_output=True, text=True)
        if "video" not in r.stdout:
            return False
        return dur_of(path) >= min_dur
    except Exception:
        return False

# ---------- TTS ----------
def synth_espeak(text, out_wav):
    tmp = out_wav + ".raw.wav"
    spd = os.environ.get("ESPEAK_SPEED", "150")
    run(["espeak-ng","-v","es","-s",spd,"-p","38","-w",tmp,text])
    run(["ffmpeg","-y","-loglevel","error","-i",tmp,"-ar","44100","-ac","2",out_wav])
    os.remove(tmp)

def synth_edge(text, out_wav):
    import edge_tts
    tmp_mp3 = out_wav + ".mp3"
    async def _go():
        c = edge_tts.Communicate(text, EDGE_VOICE, rate=os.environ.get("EDGE_RATE", "+0%"))
        await c.save(tmp_mp3)
    asyncio.run(_go())
    run(["ffmpeg","-y","-loglevel","error","-i",tmp_mp3,"-ar","44100","-ac","2",out_wav])
    os.remove(tmp_mp3)

def synth_edge_full(text, out_wav):
    """Locución completa de una vez (fluida) + tiempos de cada palabra."""
    import edge_tts
    tmp_mp3 = out_wav + ".mp3"
    words = []
    async def _go():
        c = edge_tts.Communicate(text, EDGE_VOICE, rate=os.environ.get("EDGE_RATE", "+0%"))
        with open(tmp_mp3, "wb") as f:
            async for ch in c.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append((ch["offset"] / 1e7, ch["duration"] / 1e7, ch["text"]))
    asyncio.run(_go())
    run(["ffmpeg","-y","-loglevel","error","-i",tmp_mp3,"-ar","44100","-ac","2",out_wav])
    os.remove(tmp_mp3)
    return words

def synth_eleven_full(text, out_wav):
    """Locucion premium con ElevenLabs + tiempos por palabra (endpoint
    with-timestamps). Devuelve lista [(inicio_s, duracion_s, palabra), ...],
    EXACTAMENTE el mismo formato que synth_edge_full, para que los subtitulos
    palabra por palabra sigan sincronizados sin tocar el resto del codigo."""
    import base64
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice = os.environ.get("ELEVEN_VOICE_ID", "").strip()
    if not key:
        raise RuntimeError("falta ELEVENLABS_API_KEY")
    if not voice:
        raise RuntimeError("falta ELEVEN_VOICE_ID")
    model = os.environ.get("ELEVEN_MODEL", "eleven_flash_v2_5")
    fmt = os.environ.get("ELEVEN_FORMAT", "mp3_44100_128")
    payload = {"text": text, "model_id": model}
    lang = os.environ.get("ELEVEN_LANG", "").strip()      # opcional: "es" fuerza idioma
    if lang:
        payload["language_code"] = lang
    url = ("https://api.elevenlabs.io/v1/text-to-speech/"
           + voice + "/with-timestamps?output_format=" + fmt)
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"xi-api-key": key,
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    b64 = data.get("audio_base64") or data.get("audio")
    if not b64:
        raise RuntimeError("respuesta de ElevenLabs sin audio")
    tmp_mp3 = out_wav + ".mp3"
    with open(tmp_mp3, "wb") as f:
        f.write(base64.b64decode(b64))
    run(["ffmpeg","-y","-loglevel","error","-i",tmp_mp3,"-ar","44100","-ac","2",out_wav])
    os.remove(tmp_mp3)
    # Reconstruye tiempos por PALABRA a partir del alineado por CARACTER
    al = data.get("alignment") or data.get("normalized_alignment") or {}
    chars = al.get("characters") or []
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    words = []
    cur = ""; w_start = None; w_end = 0.0
    for i, ch in enumerate(chars):
        st = starts[i] if i < len(starts) else w_end
        en = ends[i] if i < len(ends) else st
        if ch.isspace():
            if cur:
                s0 = w_start if w_start is not None else 0.0
                words.append((s0, max(0.01, w_end - s0), cur)); cur = ""; w_start = None
        else:
            if w_start is None:
                w_start = st
            cur += ch; w_end = en
    if cur:
        s0 = w_start if w_start is not None else 0.0
        words.append((s0, max(0.01, w_end - s0), cur))
    return words

def synth_full(text, out_wav):
    """Locucion completa de una vez + tiempos de palabra. Usa ElevenLabs si
    esta configurado (TTS_ENGINE=eleven y hay API key) y CAE a edge-tts si algo
    falla, para no perder nunca el video del dia."""
    if TTS_ENGINE == "eleven":
        if not os.environ.get("ELEVENLABS_API_KEY"):
            _calidad_flag("falta la clave ELEVENLABS_API_KEY: la voz saldria con la de "
                          "reserva (gratis), no con ElevenLabs")
        else:
            try:
                w = synth_eleven_full(text, out_wav)
                sys.stderr.write("[tts] voz: ElevenLabs (" +
                                 os.environ.get("ELEVEN_MODEL", "eleven_flash_v2_5") + ")\n")
                return w
            except Exception as e:
                _calidad_flag("la voz de ElevenLabs fallo (%s): se usaria la voz de "
                              "reserva (gratis)" % e)
    return synth_edge_full(text, out_wav)

def synth(text, out_wav):
    # 'eleven' usa la locucion premium en build_audio; si por lo que sea se llega
    # aqui (reparto frase a frase), usamos edge (existe en el runner), NUNCA espeak.
    if TTS_ENGINE in ("edge", "eleven"):
        synth_edge(text, out_wav)
    else:
        synth_espeak(text, out_wav)

# Texto para la locución: une las frases con una pausa MÁS CORTA (coma en vez
# de punto y seguido) para que el narrador vaya más fluido entre frases.
def _tts_join(lines):
    parts = []
    for l in lines:
        v = (l.get("voice", "") or "").strip()
        if not v:
            continue
        if v.endswith("."):
            v = v[:-1]          # quita solo el punto final -> pausa más corta
        parts.append(v)
    return ", ".join(parts)

# ---------- Subtítulos ASS ----------
def ass_time(t):
    cs = int(round(t*100))
    h = cs//360000; cs -= h*360000
    m = cs//6000;   cs -= m*6000
    s = cs//100;    cs -= s*100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def esc(t):
    return t.replace("\\","\\\\").replace("{","(").replace("}",")")

HL = "&H0037B6FF&"   # amarillo/ámbar para la palabra activa (BBGGRR)
WHITE = "&H00FFFFFF&"

def cap_word_events(cap, st, en, chunk=1):
    """Una palabra a la vez, centrada y quieta, sincronizada con la voz.
    Limpio y sin parpadeos: cada palabra aparece cuando se dice y la
    sustituye la siguiente (nada de recolocar ni animaciones que saltan)."""
    words = cap.split()
    if not words:
        return []
    weights = [len(w) + 1 for w in words]
    tot = sum(weights)
    dur = max(0.001, en - st)
    tspan = []
    cur = st
    for wt in weights:
        wd = dur * wt / tot
        tspan.append((cur, cur + wd))
        cur += wd
    evts = []
    for wi, w in enumerate(words):
        ws = tspan[wi][0]
        we = tspan[wi + 1][0] if wi + 1 < len(words) else en
        evts.append((ws, we, "{\\fad(70,0)}" + esc(w.upper())))
    return evts

def build_ass(events, path, handle=None, total=0.0):
    # events: list of (start, end, caption_text, hidden)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT},104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,1,0,1,8,4,2,120,120,540,1
Style: Brand,{FONT},42,&H50FFFFFF,&H50FFFFFF,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,8,40,40,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    if handle and total > 0:
        lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Brand,,0,0,0,,{esc(handle)}")
    for (st, en, cap, hidden) in events:
        if hidden or not cap.strip():
            continue
        for (ws, we, txt) in cap_word_events(cap, st, en):
            lines.append(f"Dialogue: 0,{ass_time(ws)},{ass_time(we)},Main,,0,0,0,,{txt}")
    with open(path,"w",encoding="utf-8") as f:
        f.write("\n".join(lines))

# ---------- Fondo con vídeos reales (Pexels o carpeta local) ----------
def _pexels_clips(query, n, workdir):
    """Descarga hasta n vídeos verticales de Pexels. Lista de rutas o []."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return []
    try:
        url = ("https://api.pexels.com/videos/search?"
               + urllib.parse.urlencode({"query": query, "orientation": "portrait",
                                         "per_page": 20, "size": "medium"}))
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        vids = data.get("videos", [])
        out = []
        for j, vid in enumerate(vids[:n]):
            files = [f for f in vid.get("video_files", [])
                     if (f.get("height") or 0) >= (f.get("width") or 0)] or vid.get("video_files", [])
            if not files:
                continue
            files.sort(key=lambda f: (0 if (f.get("width") or 0) >= 1080 else 1, -(f.get("width") or 0)))
            dst = os.path.join(workdir, f"src_{j}.mp4")
            try:
                with urllib.request.urlopen(files[0]["link"], timeout=20) as r, open(dst, "wb") as f:
                    f.write(r.read())
                if _valid_video(dst):
                    out.append(dst)
            except Exception:
                pass
        if out:
            print(f"[bg] {len(out)} clips de Pexels para: {query}")
        return out
    except Exception as e:
        sys.stderr.write(f"[bg] Pexels falló ({e}); uso degradado.\n")
        return []

def _pixabay_clips(query, n, workdir):
    """Descarga hasta n vídeos de Pixabay (alternativa a Pexels). Lista o []."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query:
        return []
    try:
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
            {"key": key, "q": query, "per_page": max(3, min(n * 2, 20)), "safesearch": "true"})
        req = urllib.request.Request(url, headers={"User-Agent": "canal-bot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        hits = data.get("hits", [])
        # prioriza clips verticales (menos recorte/estirado) para más nitidez
        hits = sorted(hits, key=lambda h: (h.get("width", 1) / max(1, h.get("height", 1))))
        out = []
        for j, h in enumerate(hits[:n]):
            v = h.get("videos", {})
            f = v.get("large") or v.get("medium") or v.get("small") or v.get("tiny")
            if not f or not f.get("url"):
                continue
            dst = os.path.join(workdir, f"src_{j}.mp4")
            try:
                rq = urllib.request.Request(f["url"], headers={"User-Agent": "canal-bot/1.0"})
                with urllib.request.urlopen(rq, timeout=20) as r, open(dst, "wb") as fo:
                    fo.write(r.read())
                if _valid_video(dst):
                    out.append(dst)
            except Exception:
                pass
        if out:
            print(f"[bg] {len(out)} clips de Pixabay para: {query}")
        return out
    except Exception as e:
        sys.stderr.write(f"[bg] Pixabay falló ({e})\n")
        return []

def _clips_for_query(q, n, workdir):
    # prioriza Pixabay si hay clave; si no, Pexels
    if os.environ.get("PIXABAY_API_KEY"):
        cs = _pixabay_clips(q, n, workdir)
        if cs:
            return cs
    return _pexels_clips(q, n, workdir)

def _gather_clips(script, workdir):
    ldir = os.environ.get("LOCAL_BROLL_DIR")
    if ldir and os.path.isdir(ldir):
        return [os.path.join(ldir, f) for f in sorted(os.listdir(ldir))
                if f.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".m4v"))]
    return _clips_for_query(script.get("broll"), 4, workdir)

def _norm_clip(src, dur, out):
    # recorte a vertical + push-in suave (zoom que da movimiento y "punch" en cada corte)
    # supersampling (1440 -> 1080) + zoom más suave + enfoque = fondo más nítido
    vf = ("scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,"
          "zoompan=z='min(1.02+0.0009*in,1.10)':d=1:"
          "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
          "unsharp=5:5:0.7:5:5:0.0,setsar=1")
    run(["ffmpeg","-y","-loglevel","error","-stream_loop","-1","-t",f"{dur:.2f}","-i",src,
         "-vf",vf,"-an","-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p", out])

def _groups(nlines, n):
    """Reparte n líneas en n grupos contiguos lo más iguales posible."""
    n = max(1, min(n, nlines))
    base, extra, idx, gs = nlines // n, nlines % n, 0, []
    for k in range(n):
        cnt = base + (1 if k < extra else 0)
        gs.append(list(range(idx, idx + cnt)))
        idx += cnt
    return [g for g in gs if g]

def _falai_clip(prompt, workdir, idx):
    """Genera UN clip cinematografico con IA (Kling via fal.ai). Devuelve la ruta
    del mp4 o None. Si falla por lo que sea, devuelve None y el motor usa stock."""
    key = os.environ.get("FAL_KEY", "").strip()
    if not key or not prompt:
        return None
    import time
    model = os.environ.get("FAL_MODEL", "fal-ai/kling-video/v2.5-turbo/pro/text-to-video")
    dur = os.environ.get("FAL_DURATION", "5")
    # --- Formula cinematografica (realismo por imperfeccion, estilo Mirko):
    # la ESCENA la pone el guion; aqui anadimos plano/lente/luz/grado/grano/camara.
    grade = os.environ.get("FAL_STYLE",
        "warm and slightly desaturated cozy tones, gentle contrast")
    look = os.environ.get("FAL_LOOK",
        "cinematic film still, shot on anamorphic lens, shallow depth of field, "
        "soft volumetric haze, natural directional lighting, subtle handheld camera motion, "
        "fine 35mm film grain, photorealistic with natural imperfections")
    full = f"{prompt}. {look}, {grade}. no text, no captions, no watermark"
    neg = os.environ.get("FAL_NEG",
        "cartoon, 3d render, cgi, plastic skin, waxy, over-smooth, oversaturated, "
        "flat lighting, low quality, blurry, distorted, deformed, text, watermark, logo")
    try:
        body = json.dumps({"prompt": full, "duration": str(dur), "aspect_ratio": "9:16",
                           "negative_prompt": neg}).encode()
        req = urllib.request.Request("https://queue.fal.run/" + model, data=body,
              headers={"Authorization": "Key " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            sub = json.loads(r.read().decode())
        status_url = sub.get("status_url"); response_url = sub.get("response_url")
        if not status_url or not response_url:
            return None
        for _ in range(70):                      # espera hasta ~6 min
            rq = urllib.request.Request(status_url, headers={"Authorization": "Key " + key})
            with urllib.request.urlopen(rq, timeout=30) as r:
                st = json.loads(r.read().decode())
            s = st.get("status")
            if s == "COMPLETED":
                break
            if s in ("FAILED", "ERROR", "CANCELED"):
                sys.stderr.write(f"[bg] fal.ai estado {s}; uso stock.\n"); return None
            time.sleep(5)
        else:
            sys.stderr.write("[bg] fal.ai tardo demasiado; uso stock.\n"); return None
        rq = urllib.request.Request(response_url, headers={"Authorization": "Key " + key})
        with urllib.request.urlopen(rq, timeout=60) as r:
            res = json.loads(r.read().decode())
        vid = ((res.get("video") or {}).get("url")
               or (res.get("output") or {}).get("url")
               or (res.get("videos", [{}])[0].get("url") if res.get("videos") else None))
        if not vid:
            return None
        dst = os.path.join(workdir, f"ai_{idx}.mp4")
        rq2 = urllib.request.Request(vid, headers={"User-Agent": "canal-bot/1.0"})
        with urllib.request.urlopen(rq2, timeout=180) as r, open(dst, "wb") as f:
            f.write(r.read())
        if _valid_video(dst):
            print(f"[bg] clip IA (Kling) para: {prompt[:40]}")
            return dst
        return None
    except Exception as e:
        sys.stderr.write(f"[bg] fal.ai fallo ({e}); uso stock.\n")
        return None

def _wiki_photo(query, dst):
    """Imagen REAL de archivo desde Wikimedia Commons (gratis, sin clave). True/False."""
    if not query:
        return False
    try:
        api = "https://commons.wikimedia.org/w/api.php"
        params = {"action": "query", "format": "json", "generator": "search",
                  "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": "8",
                  "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": "1280"}
        url = api + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "canal-bot/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        for p in (data.get("query", {}).get("pages", {}) or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            u = ii.get("thumburl") or ii.get("url"); mime = ii.get("mime", "")
            if u and mime.startswith("image") and ("jpeg" in mime or "png" in mime):
                rq = urllib.request.Request(u, headers={"User-Agent": "canal-bot/1.0"})
                with urllib.request.urlopen(rq, timeout=25) as rr, open(dst, "wb") as f:
                    f.write(rr.read())
                if os.path.getsize(dst) > 8000:
                    return u
    except Exception as e:
        sys.stderr.write(f"[foto] wiki fallo ({e})\n")
    return False

def _pexels_photo(query, dst):
    """Foto de stock desde Pexels (usa PEXELS_API_KEY, ya configurada)."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return False
    try:
        url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
            {"query": query, "orientation": "portrait", "per_page": 6})
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        for ph in data.get("photos", []):
            src = ph.get("src") or {}
            u = src.get("large2x") or src.get("large") or src.get("original")
            if u:
                rq = urllib.request.Request(u, headers={"User-Agent": "canal-bot/1.0"})
                with urllib.request.urlopen(rq, timeout=25) as rr, open(dst, "wb") as f:
                    f.write(rr.read())
                if os.path.getsize(dst) > 8000:
                    return u
    except Exception as e:
        sys.stderr.write(f"[foto] pexels fallo ({e})\n")
    return False

def _falai_image(prompt, dst, idx=0):
    """Genera UNA imagen cinematografica con IA (fal.ai, p.ej. Flux). ~15x mas
    barata que un clip de video (~$0.03). Aplica la formula de realismo de Mirko
    (plano/lente/luz/grano/color). Devuelve True/False."""
    key = os.environ.get("FAL_KEY", "").strip()
    if not key or not prompt:
        return False
    import time
    model = os.environ.get("FAL_IMG_MODEL", "fal-ai/flux/dev")
    grade = os.environ.get("FAL_STYLE", "warm cinematic tones, gentle contrast")
    look = os.environ.get("FAL_LOOK",
        "cinematic film still, shot on anamorphic lens, shallow depth of field, "
        "soft volumetric haze, natural directional lighting, fine 35mm film grain, "
        "photorealistic with natural imperfections")
    full = f"{prompt}. {look}, {grade}. no text, no captions, no watermark"
    try:
        w = int(os.environ.get("FAL_IMG_W", "1024"))
        h = int(os.environ.get("FAL_IMG_H", "1792"))
        neg = os.environ.get("FAL_IMG_NEG",
            "deformed, distorted faces, extra limbs, extra fingers, mutated hands, "
            "bad anatomy, disfigured, ugly, low quality, blurry, crowd of faces, "
            "cartoon, 3d render, cgi, plastic, watermark, text, "
            "gore, blood, bloody, wound, injury, graphic violence, torture, corpse, "
            "dead body, mutilation, nudity, naked, nsfw, disturbing, scary horror")
        body = json.dumps({"prompt": full, "num_images": 1,
                           "image_size": {"width": w, "height": h},
                           "negative_prompt": neg,
                           "enable_safety_checker": True}).encode()
        req = urllib.request.Request("https://queue.fal.run/" + model, data=body,
              headers={"Authorization": "Key " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            sub = json.loads(r.read().decode())
        status_url = sub.get("status_url"); response_url = sub.get("response_url")
        if not status_url or not response_url:
            return False
        for _ in range(40):                     # imagenes: rapido
            rq = urllib.request.Request(status_url, headers={"Authorization": "Key " + key})
            with urllib.request.urlopen(rq, timeout=30) as r:
                st = json.loads(r.read().decode())
            s = st.get("status")
            if s == "COMPLETED":
                break
            if s in ("FAILED", "ERROR", "CANCELED"):
                sys.stderr.write(f"[img] fal.ai estado {s}\n"); return False
            time.sleep(3)
        else:
            return False
        rq = urllib.request.Request(response_url, headers={"Authorization": "Key " + key})
        with urllib.request.urlopen(rq, timeout=60) as r:
            res = json.loads(r.read().decode())
        imgs = res.get("images") or []
        url = (imgs[0].get("url") if imgs and isinstance(imgs[0], dict) else None) \
              or ((res.get("image") or {}).get("url"))
        if not url:
            return False
        rq2 = urllib.request.Request(url, headers={"User-Agent": "canal-bot/1.0"})
        with urllib.request.urlopen(rq2, timeout=90) as r, open(dst, "wb") as f:
            f.write(r.read())
        if os.path.getsize(dst) > 8000:
            print(f"[img] imagen IA para: {prompt[:44]}")
            return url          # devuelve la URL publica (para imagen->video)
        return False
    except Exception as e:
        sys.stderr.write(f"[img] fal.ai imagen fallo ({e})\n")
        return False

def _photo_sources(queries, workdir):
    """Una imagen por escena. Prioridad: IA (fal.ai) -> Wikimedia -> Pexels.
    Devuelve lista de (ruta_local, url_publica_o_None). La URL sirve para
    animar la imagen (imagen->video) sin volver a subirla."""
    out = []
    for i, q in enumerate(queries):
        dst = os.path.join(workdir, f"img_{i}.jpg")
        u = _falai_image(q, dst, i) or _wiki_photo(q, dst) or _pexels_photo(q, dst)
        if u:
            out.append((dst, u if isinstance(u, str) else None))
    return out

def _norm_to_vertical(src, dur, out):
    """Normaliza cualquier clip a 1080x1920 30fps con la duracion pedida
    (repite en bucle si el clip es mas corto)."""
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "fps=30,setsar=1")
    run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1",
         "-t", f"{dur:.2f}", "-i", src, "-vf", vf, "-an", "-c:v", "libx264",
         "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", out])

def _falai_img2video(image_url, prompt, workdir, idx=0):
    """Anima una IMAGEN ya generada (imagen->video) con un modelo BARATO de fal.ai.
    Mucho mas barato que texto->video. Modelo configurable con FAL_I2V_MODEL.
    Devuelve la ruta del mp4 crudo o None (si falla, el motor usa Ken Burns)."""
    key = os.environ.get("FAL_KEY", "").strip()
    if not key or not image_url:
        return None
    import time
    model = os.environ.get("FAL_I2V_MODEL", "fal-ai/kling-video/v1.6/standard/image-to-video")
    dur = os.environ.get("FAL_I2V_DURATION", "5")
    motion = os.environ.get("FAL_I2V_PROMPT",
        "subtle cinematic camera movement, slow push-in, gentle parallax, "
        "natural motion, film look")
    full = (prompt + ". " + motion) if prompt else motion
    payload = {"image_url": image_url, "prompt": full, "duration": str(dur)}
    try:
        req = urllib.request.Request("https://queue.fal.run/" + model,
              data=json.dumps(payload).encode(),
              headers={"Authorization": "Key " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            sub = json.loads(r.read().decode())
        status_url = sub.get("status_url"); response_url = sub.get("response_url")
        if not status_url or not response_url:
            sys.stderr.write("[i2v] sin status_url; uso zoom.\n"); return None
        for _ in range(80):                      # hasta ~6-7 min
            rq = urllib.request.Request(status_url, headers={"Authorization": "Key " + key})
            with urllib.request.urlopen(rq, timeout=30) as r:
                st = json.loads(r.read().decode())
            sname = st.get("status")
            if sname == "COMPLETED":
                break
            if sname in ("FAILED", "ERROR", "CANCELED"):
                sys.stderr.write(f"[i2v] estado {sname} ({model}); uso zoom.\n"); return None
            time.sleep(5)
        else:
            sys.stderr.write("[i2v] tardo demasiado; uso zoom.\n"); return None
        rq = urllib.request.Request(response_url, headers={"Authorization": "Key " + key})
        with urllib.request.urlopen(rq, timeout=60) as r:
            res = json.loads(r.read().decode())
        vid = ((res.get("video") or {}).get("url")
               or (res.get("output") or {}).get("url")
               or (res.get("videos", [{}])[0].get("url") if res.get("videos") else None))
        if not vid:
            sys.stderr.write(f"[i2v] respuesta sin video ({model}); uso zoom.\n"); return None
        dst = os.path.join(workdir, f"i2v_{idx}.mp4")
        rq2 = urllib.request.Request(vid, headers={"User-Agent": "canal-bot/1.0"})
        with urllib.request.urlopen(rq2, timeout=180) as r, open(dst, "wb") as f:
            f.write(r.read())
        if _valid_video(dst, 0.3):
            print(f"[i2v] imagen->video OK ({model}) idx {idx}")
            return dst
        return None
    except Exception as e:
        sys.stderr.write(f"[i2v] fallo ({e}); uso zoom.\n")
        return None

def _kenburns_clip(img, dur, out, idx=0):
    """Imagen fija -> clip 1080x1920 con movimiento Ken Burns (zoom lento).
    d=1 (un frame de salida por frame de entrada) + input a 30fps -> el clip dura
    EXACTAMENTE 'dur'. (Con d=frames se disparaba a 40s+ y solo salia la 1a imagen.)"""
    F = max(1, int(round(dur * 30)))
    step = 0.14 / F            # zoom total ~14% a lo largo del clip (lento y constante)
    amp = 0.18                 # deriva respecto al CENTRO (baja = NO se va del personaje)
    # El encuadre se mantiene CENTRADO en el sujeto: push-in/pull-back suave con una
    # deriva minima (no cruza la imagen de lado a lado). Supersampling 2x (2160x3840
    # -> 1080x1920) para que el movimiento salga sedoso, sin tembleque.
    if idx % 2 == 0:
        z = f"min(1.05+{step:.6f}*on,1.22)"                         # se ACERCA (push-in)
        px = f"(iw-iw/zoom)/2+(iw-iw/zoom)*{amp}*(on/{F}-0.5)"      # leve deriva ->
    else:
        z = f"max(1.22-{step:.6f}*on,1.05)"                         # se ALEJA (pull-back)
        px = f"(iw-iw/zoom)/2-(iw-iw/zoom)*{amp}*(on/{F}-0.5)"      # leve deriva <-
    py = "(ih-ih/zoom)/2"                                           # vertical centrado
    vf = ("scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
          f"zoompan=z='{z}':d=1:s=1080x1920:fps=30:x='{px}':y='{py}',"
          "eq=brightness=-0.02:contrast=1.05:saturation=1.06,setsar=1")
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30",
         "-t", f"{dur:.2f}", "-i", img, "-vf", vf, "-an", "-c:v", "libx264",
         "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", out])

def _build_photo_bg(script, total, workdir, spans):
    """Fondo a base de FOTOS reales (modo 'photos', ideal para Historia).
    Una foto por grupo de lineas, con Ken Burns. None si no consigue imagenes."""
    queries = [q for q in (script.get("broll_list") or [script.get("broll")]) if q]
    if not queries:
        return None
    nlines = len(spans)
    # UNA imagen por linea (cambia con cada cambio de tema de la voz), hasta las que haya
    n = max(1, min(len(queries), nlines))
    groups = _groups(nlines, n)
    n = len(groups)
    imgs = _photo_sources(queries[:n], workdir)
    if not imgs:
        return None
    aivideo = os.environ.get("VISUAL_MODE", "video").strip().lower() == "aivideo"
    # HERO opcional: la IA marca 1 escena (video_idx) que se anima como VIDEO aunque
    # el modo sea 'photos'. Tope AI_HERO_CLIPS (por defecto 1) para no disparar coste.
    try:
        hero_max = int(os.environ.get("AI_HERO_CLIPS", "1"))
    except ValueError:
        hero_max = 1
    try:
        video_idx = int(script.get("video_idx", -1))
    except (TypeError, ValueError):
        video_idx = -1
    hero_done = 0
    segs = []
    for k, g in enumerate(groups):
        if k >= len(imgs):
            break
        img_path, img_url = imgs[k]
        start = spans[g[0]][0]
        end = total if k == len(groups) - 1 else spans[groups[k + 1][0]][0]
        dur = max(0.9, end - start)
        out = os.path.join(workdir, f"ph_{k}.mp4")
        want_video = aivideo or (k == video_idx and hero_done < hero_max)
        try:
            done = False
            if want_video and img_url:          # imagen->video (movimiento real)
                prompt_k = queries[k] if k < len(queries) else ""
                raw = _falai_img2video(img_url, prompt_k, workdir, k)
                if raw:
                    _norm_to_vertical(raw, dur + 0.1, out)
                    done = _valid_video(out, 0.3)
                    if done and not aivideo:
                        hero_done += 1
            if not done:                        # plan B: zoom centrado sobre la imagen
                _kenburns_clip(img_path, dur + 0.1, out, k)
            if _valid_video(out, 0.3):
                segs.append(out)
        except Exception as e:
            sys.stderr.write(f"[bg-foto] segmento {k} fallo ({e})\n")
    if not segs:
        return None
    lst = os.path.join(workdir, "phlist.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    bgv = os.path.join(workdir, "bg.mp4")
    try:
        # RE-CODIFICAR (no '-c copy'): al pegar clips de zoompan, la copia rapida
        # solo conservaba el primero y congelaba el resto. Recodificando entran TODOS.
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-r", "30", "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", "-pix_fmt", "yuv420p", bgv])
    except Exception as e:
        sys.stderr.write(f"[bg-foto] concat fallo ({e})\n")
        return None
    if not _valid_video(bgv, 1.0):
        return None
    print(f"[bg] modo FOTOS: {len(segs)} imagenes reales")
    return bgv


def build_background(script, total, workdir, spans):
    """Fondo dinámico: un clip por IDEA, con push-in. Usa metraje IA (Kling) para los
    primeros AI_CLIPS 'hero' si hay FAL_KEY, y stock para el resto. None si no hay clips."""
    if os.environ.get("VISUAL_MODE", "video").strip().lower() in ("photos", "aivideo"):
        pb = _build_photo_bg(script, total, workdir, spans)
        if pb:
            return pb
        # En modo FOTOS NO caemos a stock: si no hay imagenes de IA, devolvemos None
        # para que salte el freno de calidad y NO se publique un video con fondo generico.
        return None
    srcs = []
    blist = script.get("broll_list")
    try:
        ai_max = int(os.environ.get("AI_CLIPS", "0"))
    except ValueError:
        ai_max = 0
    have_stock = bool(os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY"))
    have_ai = bool(os.environ.get("FAL_KEY"))
    ai_done = 0
    if blist and not os.environ.get("LOCAL_BROLL_DIR") and (have_stock or have_ai):
        for i, q in enumerate(blist):
            clip = None
            if have_ai and ai_done < ai_max:
                clip = _falai_clip(q, workdir, i)
                if clip:
                    ai_done += 1
            if not clip and have_stock:
                cs = _clips_for_query(q, 1, workdir)
                if cs:
                    clip = cs[0]
            if clip:
                srcs.append(clip)
    if not srcs:
        srcs = _gather_clips(script, workdir)
    if not srcs:
        return None

    nlines = len(spans)
    n = max(1, min(len(srcs), int(round(total / 4.0)) or 1, nlines))
    srcs = srcs[:n]
    groups = _groups(nlines, n)
    n = len(groups)
    srcs = srcs[:n]

    segs = []
    for k, g in enumerate(groups):
        if k >= len(srcs):
            break
        start = spans[g[0]][0]
        end = total if k == len(groups) - 1 else spans[groups[k + 1][0]][0]
        dur = max(0.8, end - start)
        out = os.path.join(workdir, f"bgseg_{k}.mp4")
        try:
            _norm_clip(srcs[k], dur + 0.1, out)
            if _valid_video(out, 0.3):
                segs.append(out)
        except Exception as e:
            sys.stderr.write(f"[bg] clip {k} no sirvió ({e})\n")
    if not segs:
        return None
    lst = os.path.join(workdir, "bglist.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    bgv = os.path.join(workdir, "bg.mp4")
    try:
        run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",lst,
             "-r","30","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p", bgv])
    except Exception as e:
        sys.stderr.write(f"[bg] concat falló ({e})\n")
        return None
    # Verificación final: si el fondo montado no es un vídeo válido, usar degradado.
    if not _valid_video(bgv, 1.0):
        sys.stderr.write("[bg] bg.mp4 no válido; uso degradado.\n")
        return None
    return bgv

# ---------- Audio ----------
def build_audio(lines, workdir):
    # edge/eleven: una sola locución continua (fluida) + tiempos de palabra reales
    if TTS_ENGINE in ("edge", "eleven"):
        try:
            return _audio_oneshot(lines, workdir)
        except Exception as e:
            sys.stderr.write(f"[tts] one-shot falló ({e}); voy frase a frase.\n")
    return _audio_perline(lines, workdir)

def _audio_oneshot(lines, workdir):
    full = os.path.join(workdir, "full.wav")
    text = _tts_join(lines)
    words = synth_full(text, full)
    total = dur_of(full)
    if total <= 0:
        raise RuntimeError("audio vacío")
    counts = [max(1, len(l.get("voice", "").split())) for l in lines]

    # Camino A: hay tiempos de palabra suficientes -> spans precisos por línea.
    if words and len(words) >= sum(counts) * 0.6:
        spans = []; idx = 0
        for c in counts:
            seg = words[idx:idx + c]; idx += c
            if seg:
                spans.append((seg[0][0], seg[-1][0] + seg[-1][1]))
            else:
                last = words[-1]; spans.append((last[0] + last[1], last[0] + last[1]))
        spans[-1] = (spans[-1][0], total)
        return full, spans, total, words

    # Camino B: faltan tiempos de palabra -> reparto proporcional (voz continua).
    sys.stderr.write("[tts] one-shot sin tiempos de palabra; reparto proporcional (voz continua igualmente).\n")
    weights = [max(1, len(l.get("voice", "").strip())) for l in lines]
    wsum = sum(weights)
    spans = []; t = 0.0
    for w in weights:
        d = total * (w / wsum)
        spans.append((t, t + d)); t += d
    spans[-1] = (spans[-1][0], total)
    return full, spans, total, None

def _audio_perline(lines, workdir):
    parts = []; spans = []; t = 0.0
    for i, ln in enumerate(lines):
        w = os.path.join(workdir, f"seg{i:02d}.wav")
        synth(ln.get("voice", "").strip() or " ", w)
        d = dur_of(w)
        spans.append((t, t + d)); t += d
        parts.append(w)
    lst = os.path.join(workdir, "alist.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    full = os.path.join(workdir, "full.wav")
    run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",lst,"-c","copy",full])
    total = dur_of(full)
    return full, spans, total, None

# ---------- Render ----------
def build_video(script, out_path, workdir):
    lines = script["lines"]
    full_wav, spans, total, word_times = build_audio(lines, workdir)
    _calidad_check("audio")  # aborta si la voz cayo a la de reserva

    # Subtítulos VERBATIM y SINCRONIZADOS AL 100%: cada palabra aparece justo
    # cuando se pronuncia, usando los tiempos reales de la voz (edge-tts).
    disp = [w for ln in lines for w in (ln.get("voice", "") or "").split()]
    events = []
    if word_times and disp and len(word_times) >= max(1, int(len(disp) * 0.8)):
        m = min(len(disp), len(word_times))
        onsets = [word_times[k][0] for k in range(m)]
        if m < len(disp):                       # raro: faltan tiempos al final
            t0 = onsets[-1] if onsets else 0.0
            step = max(0.05, (total - t0) / (len(disp) - m + 1))
            for j in range(len(disp) - m):
                onsets.append(t0 + step * (j + 1))
        for k in range(len(disp)):
            ws = onsets[k]
            we = onsets[k + 1] if (k + 1 < len(disp)) else total
            if we <= ws:
                we = ws + 0.05
            events.append((ws, we, disp[k], False))
    else:
        # reserva: reparto por línea (si no hubo tiempos de palabra)
        for i, ln in enumerate(lines):
            start = spans[i][0]
            end = spans[i + 1][0] if i + 1 < len(lines) else total
            txt = (ln.get("voice", "") or ln.get("cap", "")).strip()
            events.append((start, end, txt, False))
    ass = os.path.join(workdir, "caps.ass")
    build_ass(events, ass, HANDLE, total)

    # Fondo dinámico (varios vídeos) o degradado de reserva
    bgv = build_background(script, total, workdir, spans)
    if not bgv and os.environ.get("VISUAL_MODE", "video").strip().lower() in ("photos", "aivideo"):
        _calidad_flag("no se consiguieron imagenes: el fondo iba a ser una pantalla lisa de color")
    _calidad_check("fondo")  # aborta si no hay imagenes reales
    grad = os.path.join(ASSETS, f"bg_{script.get('bg','blue')}.jpg")
    if not os.path.exists(grad):
        grad = os.path.join(ASSETS, "bg_blue.jpg")

    chart = script.get("chart")
    chart_path = os.path.join(ASSETS, chart) if chart else None
    has_chart = chart_path and os.path.exists(chart_path)

    music_file = None
    if os.path.isdir(MUSIC):
        tracks = sorted(os.path.join(MUSIC, fn) for fn in os.listdir(MUSIC)
                        if fn.lower().endswith((".mp3", ".m4a", ".wav", ".ogg")))
        if tracks:
            import datetime
            yday = datetime.date.today().timetuple().tm_yday
            music_file = tracks[yday % len(tracks)]   # rota 1 por día (recorre todas)

    # ---- COLA FINAL: la última frase respira y la música se apaga con suavidad ----
    TAIL = 0.9
    final_dur = total + TAIL
    vfade = f"fade=t=out:st={max(0.0, final_dur-0.6):.2f}:d=0.6"

    ass_esc = ass.replace("\\","/").replace(":","\\:")
    if bgv:
        inputs = ["-i", bgv]
        # tpad: congela el último fotograma durante la cola (el fondo nunca se queda corto)
        base_vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                   "eq=brightness=0.04:saturation=1.18:contrast=1.06,"
                   "vignette=PI/6,"
                   "drawbox=0:0:1080:1920:color=black@0.12:t=fill,"
                   f"tpad=stop_mode=clone:stop_duration={TAIL+1.0:.2f},"
                   f"subtitles='{ass_esc}',{vfade},setsar=1")
    else:
        inputs = ["-loop","1","-i", grad]
        base_vf = (f"scale=1188:2112,zoompan=z='min(1.0+0.00045*in,1.12)':d=1:"
                   f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
                   f"subtitles='{ass_esc}',{vfade},setsar=1")
    if has_chart:
        inputs += ["-loop","1","-i",chart_path]
    inputs += ["-i", full_wav]
    if music_file:
        inputs += ["-stream_loop","-1","-i",music_file]

    fc = f"[0:v]{base_vf}[base];"
    if has_chart:
        cl = script.get("chart_lines")
        if cl:
            # chart_lines son índices de LÍNEA -> usar spans (por línea), no events
            # (que ahora van por palabra). Así la gráfica sale en el momento correcto.
            i0 = max(0, min(int(cl[0]), len(spans)-1))
            i1 = max(0, min(int(cl[1]), len(spans)-1))
            cs, ce = spans[i0][0], spans[i1][1]
        else:
            c = script.get("chart_window",[0,total]); cs, ce = float(c[0]), float(c[1])
        fc += (f"[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
               f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,format=rgba,"
               f"fade=in:st={cs:.2f}:d=0.4:alpha=1,fade=out:st={max(cs,ce-0.4):.2f}:d=0.4:alpha=1[cv];"
               f"[base][cv]overlay=0:0:enable='between(t,{cs:.2f},{ce:.2f})'[v]")
    else:
        fc += "[base]null[v]"

    ai_voice = 2 if has_chart else 1
    # La voz se alarga con silencio hasta final_dur; la música (en bucle) rellena
    # la cola y TODO se funde suavemente al final (nada de corte en seco).
    if music_file:
        ai_mus = ai_voice + 1
        fc += (f";[{ai_voice}:a]loudnorm=I=-16:TP=-1.5:LRA=11,volume={VOICE_VOL},apad=whole_dur={final_dur:.2f}[vo];"
               f"[{ai_mus}:a]volume=0.09[mu];"
               f"[vo][mu]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
               f"afade=t=out:st={total:.2f}:d={TAIL:.2f}[a]")
        amap = "[a]"
    else:
        fc += (f";[{ai_voice}:a]loudnorm=I=-16:TP=-1.5:LRA=11,volume={VOICE_VOL},apad=whole_dur={final_dur:.2f},"
               f"afade=t=out:st={total:.2f}:d={TAIL:.2f}[a]")
        amap = "[a]"

    cmd = ["ffmpeg","-y","-loglevel","error"] + inputs + [
        "-filter_complex",fc,"-map","[v]","-map",amap,
        "-t",f"{final_dur:.2f}","-r","30",
        "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-movflags","+faststart", out_path]
    run(cmd)
    return final_dur

def pick_script(scripts, arg=None):
    if arg:
        for s in scripts:
            if s["id"] == arg:
                return s
    import datetime
    yday = datetime.date.today().timetuple().tm_yday
    # avanza de 1 en 1 por día -> recorre TODO el banco sin repetir durante
    # 'len' días (antes sumaba GITHUB_RUN_NUMBER y saltaba de 2 en 2, así que
    # solo usaba la mitad del banco y repetía cada pocos días).
    return scripts[yday % len(scripts)]

def main():
    with open(os.path.join(BASE,"scripts.json"),encoding="utf-8") as f:
        scripts = json.load(f)
    arg = sys.argv[1] if len(sys.argv)>1 else None
    s = None
    if not arg and os.environ.get("GEMINI_API_KEY"):
        try:
            import generate_script
            s = generate_script.generate()
            if s:
                print("[generate] guion escrito por IA (Gemini)")
        except Exception as e:
            sys.stderr.write(f"[ai] error IA ({e}); uso banco.\n")
    if not s:
        s = pick_script(scripts, arg)
    print(f"[generate] guion: {s['id']}  voz: {TTS_ENGINE}")
    out = os.path.join(OUTPUT, f"{s['id']}.mp4")
    with tempfile.TemporaryDirectory() as wd:
        total = build_video(s, out, wd)
    # Asegura #Shorts (ayuda a que YouTube lo clasifique como Short)
    tags = [h.lstrip("#") for h in s.get("hashtags", [])]
    if not any(t.lower() == "shorts" for t in tags):
        tags = ["Shorts"] + tags
    meta = {
        "video": out,
        "title": s["title"],
        "description": s["description"].rstrip() + "\n\n" + " ".join("#"+t for t in tags),
        "tags": tags,
    }
    with open(os.path.join(OUTPUT, f"{s['id']}.json"),"w",encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTPUT, "_latest.txt"),"w",encoding="utf-8") as f:
        f.write(s["id"])
    print(f"[generate] listo: {out}  ({total:.1f}s)")

if __name__ == "__main__":
    main()
