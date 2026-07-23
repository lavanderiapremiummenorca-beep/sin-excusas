# -*- coding: utf-8 -*-
"""
Generador de Shorts de economía (100% gratis, sin servicios de pago).
Flujo: guion -> voz (edge-tts o espeak) -> subtítulos sincronizados ->
fondo con movimiento + gráfica -> vídeo vertical 1080x1920.

TTS_ENGINE=edge  -> voz neuronal (para GitHub Actions, buena calidad)
TTS_ENGINE=espeak-> voz offline (prueba de formato en local)
"""
import os, sys, json, subprocess, asyncio, tempfile, textwrap, math, hashlib
import urllib.request, urllib.parse, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
OUTPUT = os.path.join(BASE, "output")
MUSIC = os.path.join(BASE, "music")
os.makedirs(OUTPUT, exist_ok=True)

TTS_ENGINE = os.environ.get("TTS_ENGINE", "espeak")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-ES-AlvaroNeural")
GAP = 0.07          # (ya no se usa; voz continua)
FONT = "DejaVu Sans"
HANDLE = os.environ.get("CHANNEL_HANDLE", "").strip()  # tu marca en pantalla (vacío = sin marca)

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("CMD FAIL: " + " ".join(cmd[:6]) + "...\n" + r.stderr[-1500:] + "\n")
        raise SystemExit(1)
    return r

def dur_of(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())

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

def synth(text, out_wav):
    if TTS_ENGINE == "edge":
        synth_edge(text, out_wav)
    else:
        synth_espeak(text, out_wav)

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

def cap_word_events(cap, st, en, words_per_line=3):
    """Subtítulos animados: la palabra que se pronuncia se resalta y crece."""
    words = cap.split()
    if not words:
        return []
    weights = [len(w) + 1 for w in words]
    tot = sum(weights)
    dur = max(0.001, en - st)
    slices = []
    cur = st
    for wt in weights:
        wd = dur * wt / tot
        slices.append((cur, cur + wd))
        cur += wd
    evts = []
    for i, (ws, we) in enumerate(slices):
        toks = []
        for j, w in enumerate(words):
            if j > 0 and j % words_per_line == 0:
                toks.append("\\N")
            wtxt = esc(w.upper())
            if j == i:
                # palabra activa: salta (pop con escala) y se resalta en color
                toks.append("{\\c" + HL + "\\fscx86\\fscy86\\t(0,110,\\fscx122\\fscy122)"
                            "\\t(110,220,\\fscx108\\fscy108)}" + wtxt
                            + "{\\c" + WHITE + "\\fscx100\\fscy100}")
            elif j < i:
                # ya dicha: blanca, ligeramente mayor
                toks.append("{\\fscx104\\fscy104}" + wtxt + "{\\fscx100\\fscy100}")
            else:
                # por venir: tenue, para guiar la vista
                toks.append("{\\alpha&H66&}" + wtxt + "{\\alpha&H00&}")
        # unir con espacios pero sin espacio extra tras un salto de línea
        s = ""
        for k, tk in enumerate(toks):
            if tk == "\\N":
                s += "\\N"
            else:
                s += ("" if (k == 0 or toks[k-1] == "\\N") else " ") + tk
        fad = "{\\fad(140,0)}" if i == 0 else ""
        evts.append((ws, we, fad + s))
    return evts

def build_ass(events, path, handle=None, total=0.0):
    # events: list of (start, end, caption_text, hidden)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT},80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,6,3,2,80,80,720,1
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
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
        vids = data.get("videos", [])
        out = []
        for j, vid in enumerate(vids[:n]):
            files = [f for f in vid.get("video_files", [])
                     if (f.get("height") or 0) >= (f.get("width") or 0)] or vid.get("video_files", [])
            if not files:
                continue
            files.sort(key=lambda f: abs((f.get("width") or 1080) - 1080))
            dst = os.path.join(workdir, f"src_{j}.mp4")
            try:
                with urllib.request.urlopen(files[0]["link"], timeout=60) as r, open(dst, "wb") as f:
                    f.write(r.read())
                if os.path.getsize(dst) > 10000:
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
        req = urllib.request.Request(url, headers={"User-Agent": "economia-bot/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
        hits = data.get("hits", [])
        out = []
        for j, h in enumerate(hits[:n]):
            v = h.get("videos", {})
            f = v.get("medium") or v.get("large") or v.get("small") or v.get("tiny")
            if not f or not f.get("url"):
                continue
            dst = os.path.join(workdir, f"src_{j}.mp4")
            try:
                rq = urllib.request.Request(f["url"], headers={"User-Agent": "economia-bot/1.0"})
                with urllib.request.urlopen(rq, timeout=60) as r, open(dst, "wb") as fo:
                    fo.write(r.read())
                if os.path.getsize(dst) > 10000:
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
    return _clips_for_query(script.get("broll"), 8, workdir)

def _norm_clip(src, dur, out):
    # recorte a vertical + push-in suave (zoom que da movimiento y "punch" en cada corte)
    vf = ("scale=1188:2112:force_original_aspect_ratio=increase,crop=1188:2112,"
          "zoompan=z='min(1.02+0.0011*in,1.16)':d=1:"
          "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,setsar=1")
    run(["ffmpeg","-y","-loglevel","error","-stream_loop","-1","-t",f"{dur:.2f}","-i",src,
         "-vf",vf,"-an","-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p", out])

def _groups(nlines, n):
    """Reparte n líneas en n grupos contiguos lo más iguales posible."""
    n = max(1, min(n, nlines))
    base, extra, idx, gs = nlines // n, nlines % n, 0, []
    for k in range(n):
        cnt = base + (1 if k < extra else 0)
        gs.append(list(range(idx, idx + cnt)))
        idx += cnt
    return [g for g in gs if g]

def build_background(script, total, workdir, spans):
    """Fondo dinámico: un clip real por IDEA, con push-in. None si no hay clips."""
    # fuentes: si el guion trae broll_list (una consulta por idea), un clip por consulta
    srcs = []
    blist = script.get("broll_list")
    if blist and not os.environ.get("LOCAL_BROLL_DIR") and (
            os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY")):
        for q in blist:
            cs = _clips_for_query(q, 1, workdir)
            if cs:
                srcs.append(cs[0])
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
            if os.path.getsize(out) > 5000:
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
        run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",lst,"-c","copy", bgv])
        return bgv
    except Exception as e:
        sys.stderr.write(f"[bg] concat falló ({e})\n")
        return None

# ---------- Audio (frase a frase, sin silencios = sincronía EXACTA y fluida) ----------
def build_audio(lines, workdir):
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
    return full, spans, total

# ---------- Render ----------
def build_video(script, out_path, workdir):
    lines = script["lines"]
    full_wav, spans, total = build_audio(lines, workdir)

    # Subtítulos CONTINUOS: cada uno se muestra hasta que empieza el siguiente
    # (sin huecos en negro entre frases -> transición fluida).
    events = []
    for i, ln in enumerate(lines):
        start = spans[i][0]
        end = spans[i + 1][0] if i + 1 < len(lines) else total
        events.append((start, end, ln.get("cap", ""), bool(ln.get("hide_caption"))))
    ass = os.path.join(workdir, "caps.ass")
    build_ass(events, ass, HANDLE, total)

    # Fondo dinámico (varios vídeos) o degradado de reserva
    bgv = build_background(script, total, workdir, spans)
    grad = os.path.join(ASSETS, f"bg_{script.get('bg','blue')}.jpg")
    if not os.path.exists(grad):
        grad = os.path.join(ASSETS, "bg_blue.jpg")

    chart = script.get("chart")
    chart_path = os.path.join(ASSETS, chart) if chart else None
    has_chart = chart_path and os.path.exists(chart_path)

    music_file = None
    if os.path.isdir(MUSIC):
        for fn in sorted(os.listdir(MUSIC)):
            if fn.lower().endswith((".mp3",".m4a",".wav",".ogg")):
                music_file = os.path.join(MUSIC, fn); break

    ass_esc = ass.replace("\\","/").replace(":","\\:")
    if bgv:
        inputs = ["-i", bgv]
        base_vf = ("eq=brightness=-0.05:saturation=1.12,"
                   "drawbox=0:0:1080:1920:color=black@0.40:t=fill,"
                   f"subtitles='{ass_esc}',setsar=1")
    else:
        inputs = ["-loop","1","-i", grad]
        base_vf = (f"scale=1188:2112,zoompan=z='min(1.0+0.00045*in,1.12)':d=1:"
                   f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
                   f"subtitles='{ass_esc}',setsar=1")
    if has_chart:
        inputs += ["-loop","1","-i",chart_path]
    inputs += ["-i", full_wav]
    if music_file:
        inputs += ["-stream_loop","-1","-i",music_file]

    fc = f"[0:v]{base_vf}[base];"
    if has_chart:
        cl = script.get("chart_lines")
        if cl:
            i0 = max(0, min(int(cl[0]), len(events)-1))
            i1 = max(0, min(int(cl[1]), len(events)-1))
            cs, ce = events[i0][0], events[i1][1]
        else:
            c = script.get("chart_window",[0,total]); cs, ce = float(c[0]), float(c[1])
        fc += (f"[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
               f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,format=rgba,"
               f"fade=in:st={cs:.2f}:d=0.4:alpha=1,fade=out:st={max(cs,ce-0.4):.2f}:d=0.4:alpha=1[cv];"
               f"[base][cv]overlay=0:0:enable='between(t,{cs:.2f},{ce:.2f})'[v]")
    else:
        fc += "[base]null[v]"

    ai_voice = 2 if has_chart else 1
    if music_file:
        ai_mus = ai_voice + 1
        fc += (f";[{ai_voice}:a]volume=1.0[vo];[{ai_mus}:a]volume=0.10[mu];"
               f"[vo][mu]amix=inputs=2:duration=first:dropout_transition=0[a]")
        amap = "[a]"
    else:
        amap = f"{ai_voice}:a"

    cmd = ["ffmpeg","-y","-loglevel","error"] + inputs + [
        "-filter_complex",fc,"-map","[v]","-map",amap,
        "-t",f"{total:.2f}","-r","30",
        "-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-movflags","+faststart", out_path]
    run(cmd)
    return total

def pick_script(scripts, arg=None):
    if arg:
        for s in scripts:
            if s["id"] == arg:
                return s
    # un guion distinto cada día Y en cada ejecución (usa el nº de ejecución de GitHub)
    import datetime
    yday = datetime.date.today().timetuple().tm_yday
    run = int(os.environ.get("GITHUB_RUN_NUMBER", "0") or "0")
    return scripts[(yday + run) % len(scripts)]

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
    meta = {
        "video": out,
        "title": s["title"],
        "description": s["description"].rstrip() + "\n\n" + " ".join("#"+h for h in s.get("hashtags",[])),
        "tags": s.get("hashtags",[]),
    }
    with open(os.path.join(OUTPUT, f"{s['id']}.json"),"w",encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTPUT, "_latest.txt"),"w",encoding="utf-8") as f:
        f.write(s["id"])
    print(f"[generate] listo: {out}  ({total:.1f}s)")

if __name__ == "__main__":
    main()
