# -*- coding: utf-8 -*-
"""Fondos verticales premium: halo radial + bokeh + destello + grano. Sin red."""
import os, math, random
from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920
OUT = os.path.join(os.path.dirname(__file__), "assets")
os.makedirs(OUT, exist_ok=True)

# (nombre, color base oscuro, color del halo, color del bokeh)
THEMES = {
    "blue":   ((10, 14, 22),  (30, 70, 130),  (90, 150, 235)),
    "green":  ((9, 20, 16),   (24, 96, 74),   (70, 210, 150)),
    "purple": ((16, 12, 24),  (74, 52, 130),  (150, 120, 235)),
    "orange": ((22, 14, 9),   (150, 80, 30),  (240, 160, 80)),
    "teal":   ((8, 18, 20),   (26, 92, 96),   (70, 200, 205)),
    "red":    ((22, 11, 12),  (140, 40, 44),  (235, 90, 95)),
}

def radial(base, glow):
    img = Image.new("RGB", (W, H), base)
    px = img.load()
    cx, cy = W * 0.5, H * 0.34
    maxd = math.hypot(W, H) * 0.55
    for y in range(H):
        for x in range(0, W, 2):
            d = math.hypot(x - cx, y - cy) / maxd
            t = max(0.0, 1.0 - d); t *= t
            r = int(base[0] + (glow[0]-base[0])*t)
            g = int(base[1] + (glow[1]-base[1])*t)
            b = int(base[2] + (glow[2]-base[2])*t)
            px[x, y] = (r, g, b)
            if x+1 < W: px[x+1, y] = (r, g, b)
    return img.filter(ImageFilter.GaussianBlur(6))

def add_bokeh(img, color, seed):
    rnd = random.Random(seed)
    layer = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    for _ in range(14):
        r = rnd.randint(40, 150)
        x = rnd.randint(-40, W+40); y = rnd.randint(int(H*0.15), H+40)
        a = rnd.randint(10, 34)
        d.ellipse([x-r, y-r, x+r, y+r], fill=(color[0], color[1], color[2], a))
    layer = layer.filter(ImageFilter.GaussianBlur(28))
    base = img.convert("RGBA")
    base.alpha_composite(layer)
    return base.convert("RGB")

def add_streak(img, color):
    layer = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    d.polygon([(W*0.55,-50),(W*0.75,-50),(W*0.30,H+50),(W*0.10,H+50)],
              fill=(color[0], color[1], color[2], 16))
    layer = layer.filter(ImageFilter.GaussianBlur(70))
    base = img.convert("RGBA"); base.alpha_composite(layer)
    return base.convert("RGB")

def vignette(img):
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W*0.35,-H*0.2, W*1.35, H*1.2], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(180))
    return Image.composite(img, Image.new("RGB",(W,H),(0,0,0)), vig)

def add_grain(img, seed):
    rnd = random.Random(seed+7)
    noise = Image.new("L", (W//2, H//2))
    noise.putdata([rnd.randint(0,255) for _ in range((W//2)*(H//2))])
    noise = noise.resize((W,H)).filter(ImageFilter.GaussianBlur(0.5))
    grain = Image.merge("RGBA", (noise,noise,noise, Image.new("L",(W,H),10)))
    base = img.convert("RGBA"); base.alpha_composite(grain)
    return base.convert("RGB")

def make(name, base, glow, bok, i):
    img = radial(base, glow)
    img = add_streak(img, bok)
    img = add_bokeh(img, bok, seed=i*13+1)
    img = vignette(img)
    img = add_grain(img, seed=i*13+1)
    path = os.path.join(OUT, f"bg_{name}.jpg")
    img.save(path, quality=88)
    print("saved", path)

if __name__ == "__main__":
    for i,(name,(base,glow,bok)) in enumerate(THEMES.items()):
        make(name, base, glow, bok, i)
