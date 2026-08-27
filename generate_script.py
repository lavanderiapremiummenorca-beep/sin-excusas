# -*- coding: utf-8 -*-
"""
Escribe el guion del dia con IA (Gemini) siguiendo PROMPT-MAESTRO.md.
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
# TEMAS internos que rotan por dia (se usan como "a evitar hoy" para forzar variedad)
TEMAS = [
    "la disciplina", "el miedo a empezar", "la constancia", "dejar de procrastinar",
    "abrazar la incomodidad", "dejar de compararte", "empezar de nuevo", "la paciencia",
    "aprender del fracaso", "el poder de los habitos", "el enfoque y las distracciones",
    "la resiliencia", "hacerlo aunque no tengas ganas", "la responsabilidad personal",
    "los pequenos pasos", "dejar de buscar excusas", "la confianza en uno mismo",
]
# ESTILOS que se intercalan cada dia (un golpe con alma, no una frase de calendario)
FORMATOS = [
    "el monologo de disciplina que remueve por dentro",
    "la verdad incomoda que necesitas oir hoy",
    "el reencuadre estoico de un problema comun",
    "el empujon para actuar HOY, ahora mismo",
    "una carta corta a tu yo del futuro",
    "el error mental que te esta frenando (y como verlo)",
]

SCHEMA_INSTRUCCION = """
Devuelve UNICAMENTE un JSON valido (sin texto alrededor) con esta forma exacta:
{
  "title": "titulo directo y con fuerza, max 90 caracteres, puede llevar 1 emoji y #shorts",
  "description": "1-2 frases con fuerza que inviten a actuar. Puedes cerrar con una pregunta.",
  "hashtags": ["Shorts", "motivacion", "disciplina", "mentalidad"],  // 3 a 5, sin '#', el primero SIEMPRE 'Shorts'
  "bg": "uno de: blue, purple, teal, orange (tonos epicos)",
  "broll": "2-4 palabras EN INGLES de escena epica (ej: 'sunrise mountain run')",
  "broll_list": ["3 o 4 escenas epicas EN INGLES, en orden (ej: 'runner sunrise silhouette', 'stormy ocean cliff', 'city lights night focus')"],
  "ai_disclosure": false,
  "lines": [
    {"voice": "frase corta y potente (numeros en palabras)",
     "cap": "subtitulo MUY corto en pantalla (2-4 palabras)"}
  ]
}
Reglas del guion (formato 'Lo que necesitas oir hoy'):
- Entre 7 y 10 lineas. Es un monologo breve con fuerza y una idea clara (el video dura 30-45 s).
- NO ES UNA LISTA DE FRASES: es UN mensaje con hilo, que remueve. Nada de "5 frases motivadoras".
- SANO, NO TOXICO: motiva a la accion y la disciplina de forma constructiva. PROHIBIDO glorificar no dormir, el sufrimiento extremo, castigarse o compararse de forma destructiva.
- APERTURA (linea 1, VARIADA cada dia, nunca identica a la de ayer): interpela directo. Ej: 'Para. Escucha esto.'
- CIERRE (ultima linea, VARIADO cada dia): un remate-lema que empuje a actuar. Ej: 'Hoy. No manana. Hoy.'
- Segunda persona, presente, con fuerza pero con respeto. 'cap' sin emojis. 'voice' numeros en letras.
- Espanol de Espana. Nada de consejo medico ni psicologico como verdad absoluta.
"""
def _run_seed():
    try:
        return int(os.environ.get("GITHUB_RUN_NUMBER", "0"))
    except ValueError:
        return 0

def _pick(lst, salt=0):
    y = datetime.date.today().timetuple().tm_yday
    return lst[(y + _run_seed() + salt) % len(lst)]

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
    assert isinstance(s.get("lines"), list) and 6 <= len(s["lines"]) <= 16, "lineas fuera de rango"
    for ln in s["lines"]:
        assert ln.get("voice"), "linea sin voz"
        ln.setdefault("cap", "")
    s.setdefault("bg", "blue")
    if s["bg"] not in BGS:
        s["bg"] = "blue"
    hs = [h.lstrip("#") for h in s.get("hashtags", []) if h.strip()]
    if not hs or hs[0].lower() != "shorts":
        hs = ["Shorts"] + [h for h in hs if h.lower() != "shorts"]
    s["hashtags"] = hs[:5]
    assert s.get("title"), "sin titulo"
    s.setdefault("description", "El empujon que necesitabas hoy. Y ahora, a por ello.")
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
        master = "Eres un narrador motivacional de YouTube Shorts en espanol, con una voz potente y una filosofia de disciplina sana y constructiva."
    formato = random.choice(FORMATOS)
    hoy = datetime.date.today().isoformat()
    # Usamos TEMAS solo como "lo obvio a EVITAR", para empujar novedad
    evitar = ", ".join(random.sample(TEMAS, min(6, len(TEMAS)))) if TEMAS else ""
    seed = _run_seed()
    prompt = (master
              + f"\n\n---\nTAREA DE HOY ({hoy}):\n"
              + "ESCRIBE un mensaje motivador breve y con fuerza para hoy, con UNA idea clara "
                "que remueva. Elige tu mismo el angulo; que sea sano y constructivo.\n"
              + (f"Para forzar variedad, HOY evita estos temas (elige otro): {evitar}.\n" if evitar else "")
              + f"Dale este ESTILO de hoy: {formato}.\n"
              + "Apertura y cierre VARIADOS (nunca los de ayer); titulo y descripcion UNICOS de hoy. Que HOY se note claramente distinto a cualquier dia anterior. Es UN monologo con hilo, NO una lista de frases.\n"
              + SCHEMA_INSTRUCCION)
    try:
        raw = _call_gemini(prompt, key)
        s = json.loads(raw)
        s = _validate(s)
        return s
    except Exception as e:
        sys.stderr.write(f"[ai] no se pudo generar con IA ({e}); se usara el banco.\n")
        return None

if __name__ == "__main__":
    import json as _j
    s = generate()
    print(_j.dumps(s, ensure_ascii=False, indent=2) if s else "None (sin GEMINI_API_KEY o error)")
