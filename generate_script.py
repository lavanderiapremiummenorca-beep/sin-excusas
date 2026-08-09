# -*- coding: utf-8 -*-
"""
Escribe el guion del día con IA (Gemini) siguiendo PROMPT-MAESTRO.md.
Se activa solo si existe GEMINI_API_KEY. Si falla algo, devuelve None
y el sistema usa el banco de guiones (scripts.json) como reserva.
Devuelve un dict con el mismo formato que usa generate.py.
"""
import os, sys, json, datetime, random, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEMINI_MODEL", "").strip()  # vacio = autodetectar modelo valido
# Candidatos por si ListModels no responde (de mas nuevo a mas compatible).
_MODEL_CANDIDATES = [
    "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash",
    "gemini-2.5-flash-lite", "gemini-2.0-flash-001", "gemini-1.5-flash",
]
BGS = ["blue", "green", "orange", "purple", "teal", "red"]

# Temas y formatos que rotan por día para no repetir (anti "contenido inauténtico")
TEMAS = [
    "disciplina frente a motivación", "por qué madrugar te da ventaja",
    "el fracaso como parte del camino", "dejar de esperar el momento perfecto",
    "salir de la zona de confort", "mejorar un 1% cada día",
    "nadie va a venir a salvarte", "dejar de compararse con los demás",
    "el dolor de la disciplina vs el del arrepentimiento", "creer en ti mismo",
    "la constancia por encima del talento", "cómo vencer la pereza",
    "el poder de los pequeños hábitos", "dejar de procrastinar",
    "enfocarte en lo que sí controlas", "la paciencia y el largo plazo",
    "rodearte de gente que suma", "convertir el miedo en combustible",
    "hacer hoy lo que otros no quieren", "levantarte una vez más que las que caes",
]
FORMATOS = [
    "mito vs realidad", "un dato sorprendente con ejemplo numérico",
    "el error común que casi todos cometen", "top 3 rápido",
    "esto no te lo cuentan", "comparativa antes vs después",
    "una pregunta que pica la curiosidad y su respuesta",
]

SCHEMA_INSTRUCCION = """
Devuelve ÚNICAMENTE un JSON válido (sin texto alrededor) con esta forma exacta:
{
  "title": "título honesto y con gancho, máx 90 caracteres, puede llevar 1 emoji y #shorts",
  "description": "1-2 frases potentes + CTA. Añade al final estos hashtags: #motivacion #disciplina #mentalidad #exito #superacion",
  "hashtags": ["Shorts", "economia", "...", "..."],  // 3 a 5, sin '#', el primero SIEMPRE 'Shorts'
  "bg": "uno de: blue, green, orange, purple, teal, red",
  "broll": "2-4 palabras EN INGLÉS para buscar metraje de archivo (ej: 'money coins saving')",
  "ai_disclosure": false,  // true solo si el contenido simula algo real que pueda confundir
  "lines": [
    {"voice": "frase corta que se narra (con números en palabras: 'cien euros', no '100')",
     "cap": "subtítulo MUY corto en pantalla (2-4 palabras, puede llevar cifras: '100€')"}
  ]
}
Reglas del guion:
- Entre 10 y 13 líneas. Cada 'voice' es una frase corta y natural (el vídeo debe durar 20-40 s).
- La PRIMERA línea es el gancho: sin saludos ni intro, engancha en el primer segundo.
- La ÚLTIMA línea es el CTA: invita a seguir ("Sígueme para tu dosis diaria") o a comentar.
- 'cap' nunca lleva emojis (la fuente no los dibuja). 'voice' escribe los números con letras.
- Español, cercano, directo y con GARRA (tono motivacional que impacte y active). Frases cortas y potentes.
"""

def _pick(lst):
    y = datetime.date.today().timetuple().tm_yday
    return lst[y % len(lst)]

def _list_models(key):
    """Pregunta a Google que modelos existen de verdad para esta clave."""
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?key={key}&pageSize=200")
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode())
        out = []
        for m in data.get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append(m.get("name", "").replace("models/", ""))
        return out
    except Exception:
        return []

def _model_order(key):
    """Orden a probar: modelo forzado por env -> candidatos -> los reales
    de la cuenta (priorizando 'flash')."""
    order = []
    if MODEL:
        order.append(MODEL)
    for m in _MODEL_CANDIDATES:
        if m not in order:
            order.append(m)
    disc = _list_models(key)
    for m in disc:
        if "flash" in m and m not in order:
            order.append(m)
    for m in disc:
        if m not in order:
            order.append(m)
    return order

def _post_generate(model, prompt, key):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.95, "responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["candidates"][0]["content"]["parts"][0]["text"]

def _call_gemini(prompt, key):
    """Prueba varios modelos y usa el primero que responda (sobrevive a que
    Google jubile un modelo). Solo falla si NINGUNO funciona."""
    last = None
    for model in _model_order(key):
        try:
            txt = _post_generate(model, prompt, key)
            sys.stderr.write(f"[ai] modelo usado: {model}\n")
            return txt
        except Exception as e:
            last = e
    raise RuntimeError(f"ningun modelo Gemini respondio: {last}")

def _validate(s):
    assert isinstance(s.get("lines"), list) and 6 <= len(s["lines"]) <= 16, "líneas fuera de rango"
    for ln in s["lines"]:
        assert ln.get("voice"), "línea sin voz"
        ln.setdefault("cap", "")
    s.setdefault("bg", "blue")
    if s["bg"] not in BGS:
        s["bg"] = "blue"
    hs = [h.lstrip("#") for h in s.get("hashtags", []) if h.strip()]
    if not hs or hs[0].lower() != "shorts":
        hs = ["Shorts"] + [h for h in hs if h.lower() != "shorts"]
    s["hashtags"] = hs[:5]
    assert s.get("title"), "sin título"
    s.setdefault("description", "⚠️ Contenido educativo, no es asesoramiento financiero.")
    s["id"] = "ia-" + datetime.date.today().isoformat()
    s.pop("chart", None)
    return s

def generate():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        master = open(os.path.join(BASE, "PROMPT-MAESTRO.md"), encoding="utf-8").read()
    except Exception:
        master = "Eres un productor experto de YouTube Shorts de economía en español."
    formato = random.choice(FORMATOS)
    hoy = datetime.date.today().isoformat()
    # Usamos TEMAS solo como "lo obvio a EVITAR", para empujar novedad
    evitar = ", ".join(random.sample(TEMAS, min(6, len(TEMAS)))) if TEMAS else ""
    prompt = (master
              + f"\n\n---\nTAREA DE HOY ({hoy}):\n"
              + "ELIGE TU MISMO un tema NUEVO, especifico y original dentro de la tematica "
                "de ESTE canal (segun las instrucciones de arriba). Sorprendeme con un angulo "
                "fresco y concreto; evita los topicos mas manidos y ya vistos.\n"
              + (f"Para forzar variedad, HOY NO trates sobre estos (elige algo distinto): {evitar}.\n" if evitar else "")
              + f"Desarrollalo con este enfoque/formato: {formato}.\n"
              + "Debe ser un tema DISTINTO cada dia; se original.\n"
              + "Cumple TODAS las reglas de arriba (cumplimiento primero, luego viralidad).\n"
              + SCHEMA_INSTRUCCION)
    try:
        raw = _call_gemini(prompt, key)
        s = json.loads(raw)
        s = _validate(s)
        return s
    except Exception as e:
        sys.stderr.write(f"[ai] no se pudo generar con IA ({e}); se usará el banco.\n")
        return None

if __name__ == "__main__":
    import json as _j
    s = generate()
    print(_j.dumps(s, ensure_ascii=False, indent=2) if s else "None (sin GEMINI_API_KEY o error)")
