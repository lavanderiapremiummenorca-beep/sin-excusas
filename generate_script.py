# -*- coding: utf-8 -*-
"""
Cerebro del canal MOTIVACION ("Sin Excusas").
Gemini ELIGE el tema libre cada dia (dentro del canal). Para que no se repita ni
derive, se le pasa una PISTA rotatoria distinta cada dia (un area/enfoque), ademas
de formato, gancho y cierre (todo por rotacion determinista).
Devuelve el mismo dict que usa generate.py.
"""
import os, sys, json, datetime, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEMINI_MODEL", "").strip()
_MODEL_CANDIDATES = [
    "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash",
    "gemini-2.5-flash-lite", "gemini-2.0-flash-001", "gemini-1.5-flash",
]

CANAL_NOMBRE = "MOTIVACION Y DISCIPLINA"
HASHTAGS_BASE = ("motivacion", "disciplina", "superacion", "mentalidad")
TEMA_GENERICO = "la disciplina"
TITULO_FALLBACK = "3 verdades sobre {base} que nadie te dice"
BG_DEFAULT = "orange"
BROLL_FALLBACK = "lone runner at dawn on an empty city street, backlit, cold breath"
BROLL_EJEMPLOS = ("ej: 'a lone runner climbing empty stadium stairs before sunrise, cold breath, "
                  "backlit', 'a tired man sitting on the edge of his bed at 5am, alarm glowing in "
                  "the dark', 'hands gripping a barbell, chalk dust in a shaft of window light'")
TONO = ("directo, en segunda persona (tu), duro pero que levanta, nunca insultante ni humillante. "
        "Espanol de Espana. Frases cortas que golpean. Termina dando una salida, no hundiendo.")
REGLA_EXTRA = ("- Personas anonimas y de espaldas o a contraluz, nunca caras de gente famosa real.\n"
               "- Nada de promesas de exito garantizado, dinero rapido, dietas ni consejos medicos "
               "o psicologicos. Si el tema roza el animo, habla de habitos y esfuerzo, NO de salud mental.")
MASTER_FALLBACK = "Eres un guionista de Shorts de motivacion y disciplina en espanol de Espana."

# PISTAS: areas/enfoques AMPLIOS (no temas cerrados). Cada dia rota una para
# empujar variedad; Gemini elige el tema y el angulo exactos dentro de esa zona.
PISTAS = [
    ("la disciplina y la constancia frente a la falta de ganas", "athlete training alone in an empty gym at night"),
    ("vencer la pereza y dejar de poner excusas", "man staring at unopened running shoes by the door"),
    ("el miedo, la duda y dar el primer paso", "climber hanging on a cliff edge looking down"),
    ("los pequenos habitos que lo cambian todo", "hands writing in a notebook at a wooden desk, morning light"),
    ("dejar de compararte y soltar las redes", "person scrolling phone in a dark room, blue light on face"),
    ("empezar de cero y las segundas oportunidades", "older man lacing running shoes on a park bench"),
    ("el esfuerzo silencioso, cuando nadie te ve", "swimmer training alone in an empty pool"),
    ("caer y volver a levantarse", "fallen cyclist getting back on the bike on a mountain road"),
    ("el enfoque y ganarle a las distracciones", "phone face down beside an open book, warm lamp"),
    ("el entorno y la gente de la que te rodeas", "two silhouettes walking apart on a foggy road"),
    ("la paciencia y el largo plazo", "small tree growing out of a rock, wide landscape"),
    ("como te hablas a ti mismo", "man looking at his reflection in a cracked mirror"),
    ("decir que no y poner limites", "hand closing a door on a noisy party"),
    ("madrugar y ganar la manana", "runner at dawn on an empty city street, long shadow"),
    ("el precio del exito que nadie ensena", "empty locker room at night, single light on"),
    ("hacer primero lo dificil e incomodo", "person diving into cold water at sunrise"),
    ("la gente que se rie de tus metas", "lone figure walking away from a crowd, long shadow"),
    ("trabajar en silencio y que hablen los resultados", "craftsman working alone in a workshop, sparks"),
]

FORMATOS = [
    "UNA VERDAD INCOMODA: una sola idea dura sobre el tema, desarrollada con tres golpes que van a mas.",
    "LISTA DE 3: tres cosas concretas sobre el tema, de la mas suave a la que mas duele.",
    "HISTORIA REAL: cuenta en treinta segundos el caso de una persona anonima que vivio esto, con giro final.",
    "LO QUE NADIE TE DICE: 3 cosas que nadie cuenta sobre el tema y que cambian como lo ves.",
    "SENALES: 3 senales de que estas fallando en esto, y que hacer con cada una.",
]

GANCHOS = [
    "abre acusando en segunda persona con una escena concreta del dia a dia del espectador, y remata con un bucle tipo 'y eso no es lo peor'",
    "abre con una frase corta y demoledora que le de la vuelta a lo que todo el mundo cree sobre el tema",
    "abre con una imagen concreta (alguien haciendo algo a una hora imposible) como si lo estuvieras viendo ahora mismo",
    "abre con una pregunta incomoda que el espectador se ha hecho alguna vez y no quiere responder",
    "abre con una comparacion cruda entre lo que dice que quiere y lo que hace de verdad",
]

CTAS = [
    "Etiqueta a quien necesita oír esto hoy.",
    "Comenta EMPIEZO si vas a hacerlo hoy mismo.",
    "¿Cuál de las tres te ha dolido más? Te leo.",
    "Guárdate esto y vuelve a verlo cuando quieras rendirte.",
    "Sígueme, que mañana va otro empujón.",
]

POWER = ("verdad", "nadie te dice", "no vas a creer", "brutal", "deja de", "empieza",
         "cambia", "jamas", "error", "senales", "duro", "incomoda", "secreto",
         "por eso", "hasta que")

BGS = ["blue", "green", "orange", "purple", "teal", "red"]


def _run_seed():
    try:
        return int(os.environ.get("GITHUB_RUN_NUMBER", "0"))
    except ValueError:
        return 0

def _daykey():
    return datetime.date.today().toordinal() + _run_seed()

def _rot(lst, stride):
    return lst[(_daykey() * stride) % len(lst)]


def _list_models(key):
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?key={key}&pageSize=200")
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "").replace("models/", "") for m in data.get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    except Exception:
        return []

def _model_order(key):
    order = []
    if MODEL:
        order.append(MODEL)
    for m in _MODEL_CANDIDATES:
        if m not in order:
            order.append(m)
    disc = _list_models(key)
    # Prioriza Gemini 'flash', luego otros Gemini, luego el resto.
    # Los 'gemma' (no dan JSON fiable) van al final.
    for m in disc:
        if "gemini" in m and "flash" in m and m not in order:
            order.append(m)
    for m in disc:
        if "gemini" in m and m not in order:
            order.append(m)
    for m in disc:
        if "gemma" not in m and m not in order:
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
        "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["candidates"][0]["content"]["parts"][0]["text"]

def _extract_json(txt):
    """Saca un JSON valido aunque el modelo lo envuelva en ```json ... ``` o texto."""
    if not txt:
        return None
    t = txt.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1 and j > i:
        t = t[i:j + 1]
    try:
        return json.loads(t)
    except Exception:
        return None

def _gen_json(prompt, key):
    """Prueba modelos hasta obtener un JSON valido. Salta los que fallen o
    devuelvan basura (p.ej. gemma con respuesta vacia). None si ninguno lo da."""
    last = None
    for model in _model_order(key):
        try:
            txt = _post_generate(model, prompt, key)
        except Exception as e:
            last = e
            continue
        obj = _extract_json(txt)
        if isinstance(obj, dict) and obj.get("lines"):
            sys.stderr.write(f"[ai] modelo usado: {model}\n")
            return obj
        sys.stderr.write(f"[ai] {model} no dio JSON valido; pruebo otro.\n")
    if last:
        sys.stderr.write(f"[ai] ultimo error: {last}\n")
    return None


# Red de seguridad: si el modelo escribe sin enes ni tildes, se restauran las
# palabras mas comunes (el subtitulo salia como "MANANA" en vez de "MANANA" con ene).
_ORTO = {
    "manana": "mañana", "ano": "año", "anos": "años", "nino": "niño", "ninos": "niños",
    "nina": "niña", "ninas": "niñas", "senor": "señor", "senora": "señora",
    "espanol": "español", "espanola": "española", "Espana": "España", "espana": "España",
    "pequeno": "pequeño", "pequena": "pequeña", "sueno": "sueño", "suenos": "sueños",
    "bano": "baño", "banos": "baños", "compania": "compañía", "montana": "montaña",
    "manana,": "mañana,", "ensenar": "enseñar", "ensena": "enseña", "diseno": "diseño",
    "extrano": "extraño", "dano": "daño", "danos": "daños", "puno": "puño",
    "canon": "cañón", "otono": "otoño", "sueno.": "sueño.", "duena": "dueña",
    "dueno": "dueño", "acompanar": "acompañar", "manana.": "mañana.",
}

def _fix_orto(txt):
    if not isinstance(txt, str) or not txt:
        return txt
    out = []
    for w in txt.split(" "):
        low = w.lower()
        rep = _ORTO.get(low) or _ORTO.get(w)
        if rep:
            if w[:1].isupper():
                rep = rep[:1].upper() + rep[1:]
            out.append(rep)
        else:
            out.append(w)
    return " ".join(out)


def _validate(s, tema="", cta="", broll_en=""):
    assert isinstance(s.get("lines"), list) and 4 <= len(s["lines"]) <= 12, "lineas fuera de rango"
    for ln in s["lines"]:
        assert ln.get("voice"), "linea sin voz"
        ln.setdefault("cap", "")
        ln["voice"] = _fix_orto(ln["voice"])
        ln["cap"] = _fix_orto(ln["cap"])
    s.setdefault("bg", BG_DEFAULT)
    if s["bg"] not in BGS:
        s["bg"] = BG_DEFAULT
    hs = [h.lstrip("#") for h in s.get("hashtags", []) if h.strip()]
    if not hs or hs[0].lower() != "shorts":
        hs = ["Shorts"] + [h for h in hs if h.lower() != "shorts"]
    s["hashtags"] = (hs + list(HASHTAGS_BASE))[:6]

    # TITULO: obliga a que lleve un numero o una palabra potente
    t = _fix_orto((s.get("title") or "").strip())
    low = t.lower()
    tiene_num = any(c.isdigit() for c in t) or any(w in low for w in
        ("tres", "cuatro", "cinco", "dos"))
    tiene_power = any(p in low for p in POWER)
    if not t or not (tiene_num or tiene_power):
        base = (tema or TEMA_GENERICO).strip()
        t = TITULO_FALLBACK.format(base=base)
    if "#short" not in low:
        t = t + " #shorts"
    s["title"] = t

    # CTA obligatorio como ultima linea (cebo de comentarios)
    if cta:
        last = (s["lines"][-1].get("voice", "") or "").lower()
        if "coment" not in last and "abajo" not in last and "sigue" not in last and "guarda" not in last:
            s["lines"].append({"voice": cta, "cap": "comenta abajo"})

    if not (s.get("description") or "").strip():
        s["description"] = (t.replace(" #shorts", "") + ". " + (cta or "")).strip()
    s["description"] = _fix_orto(s["description"]).rstrip()

    # BROLL como pista de imagen
    bl = s.get("broll_list")
    if not isinstance(bl, list) or not bl:
        bl = [broll_en] if broll_en else []
    bl = [b.strip() for b in bl if isinstance(b, str) and b.strip()][:12]
    if bl:
        s["broll_list"] = bl
        s["broll"] = bl[0]
    elif broll_en:
        s["broll_list"] = [broll_en]; s["broll"] = broll_en

    try:
        s["video_idx"] = int(s.get("video_idx", -1))
    except (TypeError, ValueError):
        s["video_idx"] = -1
    s["ai_disclosure"] = False
    s["id"] = "ia-" + datetime.date.today().isoformat()
    s.pop("chart", None)
    return s


def _schema(broll_en, formato, gancho, cta, pista):
    hs = '", "'.join(["Shorts"] + list(HASHTAGS_BASE))
    return f"""
Devuelve UNICAMENTE un JSON valido (sin texto alrededor) con esta forma exacta:
{{
  "title": "titulo IMPACTANTE con un NUMERO y/o una palabra potente. Sobre el tema de HOY. Max 80 caracteres, 1 emoji opcional, incluye #shorts.",
  "description": "1-2 frases con gancho + hashtags. Termina invitando a comentar.",
  "hashtags": ["{hs}"],
  "bg": "uno de: orange, red, purple, teal",
  "broll": "{broll_en}",
  "broll_list": ["una ESCENA para RECREAR con IA por CADA linea, EN INGLES, concreta, con ACCION, lugar y luz ({BROLL_EJEMPLOS}). En el MISMO orden que 'lines'. UNA escena por CADA linea (mismo numero de escenas que de lineas), y cada escena debe mostrar EXACTAMENTE lo que se narra en esa linea. Describe una imagen VIVA, como un plano de cine."],
  "ai_disclosure": false,
  "video_idx": "indice 0-based de la ESCENA de broll_list que MAS ganaria con MOVIMIENTO de video real (la mas dinamica). Devuelve -1 si ninguna lo necesita. Como MUCHO una.",
  "lines": [
    {{"voice": "frase que se narra (numeros en palabras)", "cap": "subtitulo corto en pantalla (2-4 palabras)"}}
  ]
}}
GUION DE HOY (canal de {CANAL_NOMBRE}, formato viral, DISTINTO a cualquier dia anterior):
- ELIGE TU EL TEMA DE HOY: libre, dentro del canal de {CANAL_NOMBRE}. Concreto y con gancho. Que sea DISTINTO a lo mas tipico y a lo de dias anteriores; NO te repitas ni tires siempre por lo mismo.
- PISTA PARA VARIAR HOY (orientate hacia esta zona para no caer siempre en lo mismo, pero TU decides el tema y el enfoque exactos, y puedes afinar dentro de ella): {pista}.
- FORMATO DE HOY: {formato}
- LINEA 1 = GANCHO (primer segundo). Tecnica de hoy: {gancho}. PROHIBIDO usar frases-comodin genericas ("el noventa por ciento no sabe esto", "prepara la cabeza", "esto te va a explotar la mente", "agarrate"): NO enganchan, suenan a bot. El gancho debe ser CONCRETO, especifico y util, sacado de lo MAS fuerte del tema de hoy, y ABRIR UN BUCLE (promete algo aun mejor que todavia no cuentas). Nada de empezar con "En [tema]...".
- Luego el contenido, cada parte concreta y VERAZ (nada inventado). De menos a mas: lo mejor al final.
- Encadena con TENSION ("pero lo siguiente es mejor", "y aun hay mas"), NO con "primero, segundo, tercero" a secas.
- ORTOGRAFIA: espanol de Espana IMPECABLE, con TILDES y con la letra ENE (mañana, año, España, sueño, pequeño). NUNCA sustituyas la ñ por n. Cuidado con articulos y concordancia. Frases cortas y en presente.
- ULTIMA LINEA = CIERRE que invita a participar: algo tipo "{cta}".
- Entre 5 y 8 lineas en total. Frases cortas y con energia (ritmo de Short, 30-45 s).
- Tono: {TONO}
- 'cap' sin emojis. 'voice' escribe los numeros con letras.
- SEGURIDAD (obligatorio): las escenas deben ser APTAS PARA YOUTUBE Y PUBLICIDAD. Con fuerza, pero SIN sangre, heridas, cuerpos mutilados, desnudos ni violencia explicita. Nada de caras de personas reales famosas.
{REGLA_EXTRA}
- CRITICO: cada escena de 'broll_list' debe MOSTRAR EXACTAMENTE lo que se narra en esa parte, EN EL MISMO ORDEN. NADA generico ni palabras sueltas: escena de cine con accion + lugar + luz, EN INGLES.
"""


def generate():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        master = open(os.path.join(BASE, "PROMPT-MAESTRO.md"), encoding="utf-8").read()
    except Exception:
        master = MASTER_FALLBACK

    pista, broll_en = _rot(PISTAS, 1)
    tema = ""  # el tema lo ELIGE Gemini; 'pista' solo orienta para no repetir
    formato = _rot(FORMATOS, 3)
    gancho = _rot(GANCHOS, 5)
    cta = _rot(CTAS, 7)
    hoy = datetime.date.today().isoformat()

    prompt = (master
              + f"\n\n---\nTAREA DE HOY ({hoy}):\n"
              + f"Crea un Short de {CANAL_NOMBRE} con el formato viral de abajo. ELIGE tu el tema (libre, del canal, sin repetir), "
                "y sigue EXACTAMENTE el formato, el gancho y el cierre que se te asignan. Todo debe ser VERAZ.\n"
              + _schema(broll_en, formato, gancho, cta, pista))
    try:
        s = _gen_json(prompt, key)
        if not s:
            raise RuntimeError("ningun modelo dio JSON valido")
        s = _validate(s, tema=tema, cta=cta, broll_en=broll_en)
        return s
    except Exception as e:
        sys.stderr.write(f"[ai] no se pudo generar con IA ({e}); se usara el banco.\n")
        return None


if __name__ == "__main__":
    import json as _j
    s = generate()
    print(_j.dumps(s, ensure_ascii=False, indent=2) if s else "None (sin GEMINI_API_KEY o error)")
