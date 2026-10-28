"""Génère un Reel vertical 1080x1920 aux couleurs de LeCoinRare à partir d'un fichier JSON.

Usage : python3 reel.py spec.json sortie.mp4 [--apercu]

Types de scènes : hook, point, quiz (« Devinez l'espèce »), outro.
Chaque scène peut avoir un fond : "media" (chemin d'une photo ou d'une vidéo, relatif au JSON) ou
"media_query" (recherche en anglais dans Pexels, Pixabay puis Wikimedia Commons, voir medias.py),
avec "media_kind" video|photo, "media_index" pour un autre résultat et "media_source" pour forcer une source.
Sans vidéo trouvée, une photo est utilisée.
Le fond garde un lent zoom et un dégradé pour que le texte reste lisible.
Dans les titres, les mots entre *astérisques* sont surlignés.
À côté du MP4, une couverture JPG est extraite à "cover_ms" (7500 par défaut).
--apercu écrit seulement une image PNG par scène, pour vérifier la mise en page en quelques secondes.
"""
import json, math, os, subprocess, sys
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medias as banques

W, H, FPS = 1080, 1920, 30
VERT = (28, 42, 31)          # #1C2A1F, couleur de marque
VERT_FONCE = (16, 26, 19)
VERT_CLAIR = (58, 92, 66)
CREME = (244, 239, 230)
AMBRE = (232, 180, 74)
ROUGE = (226, 104, 86)
TURQUOISE = (72, 160, 150)
FONT_DIR = "/usr/share/fonts/opentype/inter/"
if not os.path.isdir(FONT_DIR):  # Windows / poste local : polices Inter livrées à côté du script
    FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "")
FONTS = {
    "display": FONT_DIR + "InterDisplay-Bold.otf",
    "black": FONT_DIR + "InterDisplay-Black.otf",
    "bold": FONT_DIR + "Inter-Bold.otf",
    "medium": FONT_DIR + "Inter-Medium.otf",
}
TRANSITION = 0.45  # durée du volet entre deux scènes, en secondes


@lru_cache(maxsize=None)
def font(name, size):
    path = FONTS[name]
    if not os.path.exists(path):
        path = FONTS["display"]
    return ImageFont.truetype(path, size)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp(t)
    return 3 * t * t - 2 * t * t * t


def ease_back(t, s=1.7):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


# ---------------------------------------------------------------- fond animé

def _radial_sprite(size):
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2
    d = np.sqrt((x - c) ** 2 + (y - c) ** 2) / c
    return np.clip(np.exp(-(d ** 2) * 3.2), 0, 1)[..., None]


BLOB = _radial_sprite(1100)
_rng = np.random.default_rng(7)
GRAIN = [(_rng.normal(0, 3.5, (H, W, 1))).astype(np.float32) for _ in range(6)]
_yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
BASE = (np.array(VERT_FONCE, np.float32) * (1 - _yy) + np.array(VERT, np.float32) * _yy) * np.ones((1, W, 1), np.float32)
SHADE = np.clip((_yy - 0.35) / 0.65, 0, 1) ** 1.3  # assombrit le bas d'une photo pour le texte

BLOBS = [  # couleur, intensité, centre, amplitude, vitesse, phase
    (AMBRE, 0.22, (880, 380), (140, 120), 0.35, 0.0),
    (TURQUOISE, 0.20, (180, 1100), (160, 200), 0.28, 1.7),
    (VERT_CLAIR, 0.45, (760, 1650), (200, 120), 0.22, 3.1),
]


def add_blob(canvas, color, alpha, cx, cy):
    s = BLOB.shape[0]
    x0, y0 = int(cx - s / 2), int(cy - s / 2)
    sx0, sy0 = max(0, -x0), max(0, -y0)
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(W, x0 + s), min(H, y0 + s)
    if x1c <= x0c or y1c <= y0c:
        return
    sprite = BLOB[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)]
    canvas[y0c:y1c, x0c:x1c] += sprite * (np.array(color, np.float32) * alpha)


class MediaSource:
    """Photo ou vidéo de fond, recadrée en 1080x1920 avec un lent zoom."""

    def __init__(self, path, duration):
        self.path, self.duration = path, duration
        ext = os.path.splitext(path)[1].lower()
        self.is_video = ext in (".mp4", ".mov", ".webm", ".mkv", ".ogv", ".ogg")
        if self.is_video:
            cover = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}"
            self.proc = subprocess.Popen(
                ["ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-i", path, "-t", str(duration + 1),
                 "-vf", cover, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
            self.last = None
        else:
            img = Image.open(path).convert("RGB")
            scale = max(W / img.width, H / img.height) * 1.15
            self.img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)

    def frame(self, local):
        if self.is_video:
            raw = self.proc.stdout.read(W * H * 3)
            if len(raw) == W * H * 3:
                self.last = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
            return self.last.astype(np.float32) if self.last is not None else BASE.copy()
        z = 1.0 + 0.13 * ease_in_out(local)  # Ken Burns
        cw, ch = W * self.img.width / (W * 1.15 * z), H * self.img.height / (H * 1.15 * z)
        cw, ch = min(cw, self.img.width), min(ch, self.img.height)
        x0 = (self.img.width - cw) * (0.35 + 0.3 * local)
        y0 = (self.img.height - ch) * 0.4
        crop = self.img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((W, H), Image.BILINEAR)
        return np.asarray(crop, np.float32)

    def close(self):
        if self.is_video:
            self.proc.kill()


def background(t, media_frame=None):
    if media_frame is not None:
        canvas = media_frame * (1 - 0.75 * SHADE) + np.array(VERT_FONCE, np.float32) * 0.75 * SHADE
        canvas = canvas * 0.82 + BASE * 0.18
        blob_gain = 0.5
    else:
        canvas = BASE.copy()
        blob_gain = 1.0
    for color, alpha, (cx, cy), (ax, ay), speed, phase in BLOBS:
        add_blob(canvas, color, alpha * blob_gain,
                 cx + ax * math.sin(t * speed + phase), cy + ay * math.cos(t * speed * 0.8 + phase))
    canvas += GRAIN[int(t * 8) % len(GRAIN)]
    return Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


# ---------------------------------------------------------------- texte animé

@lru_cache(maxsize=512)
def word_sprite(word, fname, size, color):
    f = font(fname, size)
    l, t, r, b = f.getbbox(word)
    img = Image.new("RGBA", (r - l + 8, int(size * 1.25)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((4 - l, int(size * 0.08)), word, font=f, fill=color)
    return img


def parse_words(text):
    """'Un *mot* surligné' -> [('Un', False), ('mot', True), ('surligné', False)]"""
    out = []
    for raw in text.split():
        hl = raw.startswith("*") or raw.endswith("*") or "*" in raw
        out.append((raw.replace("*", ""), hl))
    return out


def layout(words, fname, size, max_w, space=None):
    f = font(fname, size)
    space = space or f.getlength(" ")
    lines, cur, cur_w = [], [], 0
    for word, hl in words:
        w = f.getlength(word) + (2 * size * 0.16 if hl else 0)  # place pour le surlignage
        if cur and cur_w + space + w > max_w:
            lines.append((cur, cur_w))
            cur, cur_w = [], 0
        cur_w += (space if cur else 0) + w
        cur.append((word, hl, w))
    if cur:
        lines.append((cur, cur_w))
    return lines, space


def paste_scaled(layer, sprite, cx, cy, scale, alpha):
    if alpha <= 0.01 or scale <= 0.05:
        return
    if abs(scale - 1) > 0.01:
        sprite = sprite.resize((max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))), Image.BILINEAR)
    if alpha < 0.99:
        a = sprite.getchannel("A").point(lambda v: int(v * alpha))
        sprite = sprite.copy()
        sprite.putalpha(a)
    layer.alpha_composite(sprite, (int(cx - sprite.width / 2), int(cy - sprite.height / 2)))


def kinetic_text(layer, text, local_t, start, fname, size, color, y, x=None, align="left",
                 max_w=900, stagger=0.07, hl_color=AMBRE, line_gap=1.12):
    """Fait apparaître le texte mot par mot (petit rebond), avec surlignage animé. Renvoie le y de fin."""
    lines, space = layout(parse_words(text), fname, size, max_w)
    d = ImageDraw.Draw(layer)
    i = 0
    x_left = 90 if x is None else x
    for words, line_w in lines:
        lx = (W - line_w) / 2 if align == "center" else x_left
        for word, hl, w in words:
            p = (local_t - start - i * stagger) / 0.38
            if p > 0:
                s = 0.55 + 0.45 * ease_back(p)
                a = ease_out(p * 1.6)
                cx, cy = lx + w / 2, y + size * 0.62 + (1 - ease_out(p)) * 26
                if hl:
                    sweep = ease_out((p - 0.7) / 0.9)
                    if sweep > 0:
                        d.rounded_rectangle([lx, y + size * 0.08, lx + w * sweep, y + size * 1.18],
                                            radius=int(size * 0.18), fill=hl_color + (255,))
                    col = VERT_FONCE if sweep > 0.5 else color
                else:
                    col = color
                paste_scaled(layer, word_sprite(word, fname, size, col), cx, cy, s, a)
            lx += w + space
            i += 1
        y += int(size * line_gap)
    return y


def fade_lines(layer, text, local_t, start, fname, size, color, y, max_w=900, align="left", gap=1.3):
    lines, _ = layout(parse_words(text), fname, size, max_w)
    for k, (words, line_w) in enumerate(lines):
        p = ease_out((local_t - start - k * 0.12) / 0.5)
        if p > 0:
            line = " ".join(wd for wd, _, _ in words)
            spr = word_sprite(line, fname, size, color)
            x = (W - line_w) / 2 if align == "center" else 90
            paste_scaled(layer, spr, x + spr.width / 2, y + size * 0.62 + (1 - p) * 30, 1.0, p)
        y += int(size * gap)
    return y


def pill(layer, text, x, y, p, bg, fg, size=40, align="left"):
    if p <= 0:
        return
    f = font("bold", size)
    w = f.getlength(text)
    pw, ph = w + size * 1.2, size * 1.7
    s = 0.6 + 0.4 * ease_back(p)
    img = Image.new("RGBA", (int(pw) + 4, int(ph) + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, pw, ph], radius=int(ph / 2), fill=bg + (255,))
    d.text((size * 0.6, ph / 2), text, font=f, fill=fg, anchor="lm")
    cx = (W / 2) if align == "center" else x + pw / 2
    paste_scaled(layer, img, cx, y + ph / 2, s, ease_out(p * 1.5))


# ---------------------------------------------------------------- icônes animées

def icon_thermo(d, cx, cy, p, label):
    """Thermomètre qui se remplit, avec la température qui monte."""
    a = int(255 * ease_out(p * 2))
    d.rounded_rectangle([cx - 34, cy - 230, cx + 34, cy + 60], radius=34, outline=CREME + (a,), width=8)
    d.ellipse([cx - 70, cy + 20, cx + 70, cy + 160], outline=CREME + (a,), width=8)
    d.ellipse([cx - 52, cy + 38, cx + 52, cy + 142], fill=ROUGE + (a,))
    level = ease_in_out((p - 0.15) / 0.7)
    top = cy + 50 - level * 260
    d.rounded_rectangle([cx - 18, top, cx + 18, cy + 70], radius=18, fill=ROUGE + (a,))
    for k in range(5):
        yy = cy - 190 + k * 50
        d.line([cx + 50, yy, cx + 80, yy], fill=CREME + (a // 2,), width=5)
    if label:
        num = "".join(ch for ch in label if ch.isdigit())
        if num:
            val = int(int(num) * ease_out((p - 0.15) / 0.7))
            txt = label.replace(num, str(val))
            d.text((cx + 120, cy - 40), txt, font=font("display", 110), fill=AMBRE + (a,), anchor="lm")


def icon_powder(d, cx, cy, p, label, t):
    """Pot qui saupoudre des grains sur un insecte stylisé."""
    a = int(255 * ease_out(p * 2))
    tilt = 0.35 * ease_out(p * 1.5)
    px, py = cx - 120, cy - 170
    pts = [(-55, -70), (55, -70), (70, 80), (-70, 80)]
    rot = [(px + x * math.cos(tilt) - y * math.sin(tilt), py + x * math.sin(tilt) + y * math.cos(tilt)) for x, y in pts]
    d.polygon(rot, fill=CREME + (a,))
    d.text((px, py + 10), "Ca", font=font("display", 56), fill=VERT + (a,), anchor="mm")
    # grains
    for k in range(26):
        ph = (t * 0.9 + k * 0.137) % 1.0
        if p < 0.25:
            continue
        gx = px + 70 + math.sin(k * 12.9) * 30 + ph * 60
        gy = py + 60 + ph * 230
        d.ellipse([gx - 6, gy - 6, gx + 6, gy + 6], fill=CREME + (int(a * (1 - ph)),))
    # grillon stylisé
    bx, by = cx + 40, cy + 120
    d.ellipse([bx - 110, by - 40, bx + 90, by + 40], fill=AMBRE + (a,))
    d.ellipse([bx + 60, by - 34, bx + 130, by + 30], fill=AMBRE + (a,))
    for k in (-1, 1):
        d.line([bx + 120, by - 20, bx + 210, by - 20 + k * 70], fill=AMBRE + (a,), width=6)
    for k in range(3):
        lx = bx - 70 + k * 60
        d.line([lx, by + 30, lx - 30, by + 90], fill=AMBRE + (a,), width=8)
    if label:
        d.text((cx, cy + 260), label, font=font("bold", 54), fill=CREME + (a,), anchor="mm")


def icon_solo(d, cx, cy, p, label):
    """Un cercle validé, deux cercles barrés : il vit seul."""
    a1 = int(255 * ease_out(p * 2))
    a2 = int(255 * ease_out((p - 0.3) * 2))
    r = 110
    lx, rx = cx - 210, cx + 170
    d.ellipse([lx - r, cy - r, lx + r, cy + r], outline=AMBRE + (a1,), width=12)
    chk = ease_out((p - 0.2) / 0.4)
    if chk > 0:
        p1, p2, p3 = (lx - 50, cy + 5), (lx - 12, cy + 45), (lx + 60, cy - 45)
        mid = (p1[0] + (p2[0] - p1[0]) * min(1, chk * 2), p1[1] + (p2[1] - p1[1]) * min(1, chk * 2))
        d.line([p1, mid], fill=AMBRE + (a1,), width=16)
        if chk > 0.5:
            k = (chk - 0.5) * 2
            d.line([p2, (p2[0] + (p3[0] - p2[0]) * k, p2[1] + (p3[1] - p2[1]) * k)], fill=AMBRE + (a1,), width=16)
    for off in (-55, 55):
        d.ellipse([rx + off - 75, cy - 75, rx + off + 75, cy + 75], outline=CREME + (a2,), width=10)
    cross = ease_out((p - 0.5) / 0.35)
    if cross > 0:
        s = 150 * cross
        d.line([rx - s, cy - s, rx + s, cy + s], fill=ROUGE + (a2,), width=18)
        d.line([rx - s, cy + s, rx + s, cy - s], fill=ROUGE + (a2,), width=18)
    if label:
        d.text((cx, cy + 210), label, font=font("bold", 54), fill=CREME + (a1,), anchor="mm")


def draw_icon(layer, scene, local, t):
    kind = scene.get("icon")
    if not kind:
        return
    d = ImageDraw.Draw(layer)
    p = (local * scene["duration"] - 1.0) / 1.6
    if p <= 0:
        return
    cx, cy = W // 2, 1450
    label = scene.get("icon_label", "")
    if kind == "thermo":
        icon_thermo(d, cx - 120, cy, p, label)
    elif kind == "powder":
        icon_powder(d, cx, cy - 40, p, label, t)
    elif kind == "solo":
        icon_solo(d, cx, cy - 40, p, label)


# ---------------------------------------------------------------- scènes

def scene_hook(layer, s, lt):
    pill(layer, s.get("kicker", ""), 90, 560, lt / 0.4, AMBRE, VERT_FONCE, size=42)
    y = kinetic_text(layer, s["title"], lt, 0.35, "black", 132, CREME, 700, max_w=920, stagger=0.09, line_gap=1.08)
    if s.get("subtitle"):
        fade_lines(layer, s["subtitle"], lt, 0.35 + 0.09 * len(s["title"].split()) + 0.2, "medium", 54, CREME, y + 40)


def scene_point(layer, s, lt):
    # numéro géant en contour qui glisse
    p = ease_out(lt / 0.6)
    num = str(s["n"])
    f = font("black", 520)
    spr = Image.new("RGBA", (600, 640), (0, 0, 0, 0))
    ImageDraw.Draw(spr).text((20, -40), num, font=f, fill=(0, 0, 0, 0), stroke_width=6,
                             stroke_fill=(AMBRE if not s.get("warn") else ROUGE) + (150,))
    layer.alpha_composite(spr, (int(W - 560 + (1 - p) * 300), 40))
    pill(layer, s.get("tag", "ERREUR"), 90, 470, (lt - 0.15) / 0.4, ROUGE if s.get("warn") else AMBRE, CREME if s.get("warn") else VERT_FONCE, size=38)
    y = kinetic_text(layer, s["title"], lt, 0.3, "black", 112, CREME, 600, max_w=900, stagger=0.08, line_gap=1.08)
    fade_lines(layer, s["text"], lt, 0.3 + 0.08 * len(s["title"].split()) + 0.25, "medium", 52, CREME, y + 36, max_w=880)


def scene_outro(layer, s, lt):
    # mot-symbole lettre par lettre
    word = "LeCoinRare"
    f = font("black", 150)
    total = f.getlength(word)
    x = (W - total) / 2
    for k, ch in enumerate(word):
        p = (lt - k * 0.045) / 0.4
        w = f.getlength(ch)
        if p > 0:
            col = AMBRE if k >= 6 else CREME
            paste_scaled(layer, word_sprite(ch, "black", 150, col), x + w / 2, 640 + (1 - ease_out(p)) * 50, 0.5 + 0.5 * ease_back(p), ease_out(p * 1.5))
        x += w
    y = kinetic_text(layer, s["title"], lt, 0.6, "display", 76, CREME, 800, align="center", max_w=900, stagger=0.06)
    y = fade_lines(layer, s["text"], lt, 1.1, "bold", 54, AMBRE, y + 30, align="center")
    # bouton qui respire
    p = (lt - 1.5) / 0.5
    if p > 0:
        label = s.get("cta", "Abonnez-vous")
        fb = font("black", 60)
        w = fb.getlength(label)
        bw, bh = w + 170, 130
        img = Image.new("RGBA", (int(bw) + 4, bh + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, bw, bh], radius=bh // 2, fill=AMBRE + (255,))
        d.text((60, bh / 2), label, font=fb, fill=VERT_FONCE, anchor="lm")
        d.text((bw - 70, bh / 2), "→", font=font("black", 64), fill=VERT_FONCE, anchor="mm")
        pulse = 1 + 0.035 * math.sin((lt - 1.5) * 6)
        paste_scaled(layer, img, W / 2, y + 140, (0.6 + 0.4 * ease_back(p)) * pulse, ease_out(p * 1.5))


def quiz_reveal(s):
    return s.get("reveal", s["duration"] * 0.6)


def scene_quiz(layer, s, lt):
    """« Devinez l'espèce » : indices et compte à rebours, puis la réponse (le fond flouté devient net)."""
    reveal = quiz_reveal(s)
    pill(layer, s.get("kicker", "DEVINEZ L'ESPÈCE"), 90, 470, lt / 0.4, AMBRE, VERT_FONCE, size=40)
    if lt < reveal:
        y = kinetic_text(layer, s["title"], lt, 0.3, "black", 92, CREME, 590, max_w=900, stagger=0.07, line_gap=1.08)
        if s.get("text"):
            fade_lines(layer, s["text"], lt, 0.3 + 0.07 * len(s["title"].split()) + 0.2, "medium", 50, AMBRE, y + 36, max_w=880)
        d = ImageDraw.Draw(layer)
        cx, cy, r = W // 2, 1500, 115
        frac = clamp(lt / reveal)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=CREME + (60,), width=14)
        d.arc([cx - r, cy - r, cx + r, cy + r], start=-90, end=-90 + 360 * (1 - frac), fill=AMBRE + (255,), width=14)
        d.text((cx, cy), str(max(1, math.ceil(reveal - lt))), font=font("black", 120), fill=CREME + (255,), anchor="mm")
    else:
        rt = lt - reveal
        pill(layer, "RÉPONSE", 90, 590, rt / 0.35, ROUGE, CREME, size=38)
        y = kinetic_text(layer, s["answer"], rt, 0.15, "black", 124, CREME, 700, max_w=920, stagger=0.08, line_gap=1.06)
        if s.get("answer_text"):
            fade_lines(layer, s["answer_text"], rt, 0.6, "medium", 52, CREME, y + 36, max_w=880)


SCENES = {"hook": scene_hook, "point": scene_point, "quiz": scene_quiz, "outro": scene_outro}


# ---------------------------------------------------------------- habillage

def chrome(layer, scenes, t, total):
    d = ImageDraw.Draw(layer)
    # barre de progression segmentée façon stories
    n, gap, x0, x1, y = len(scenes), 12, 70, W - 70, 74
    seg_w = (x1 - x0 - gap * (n - 1)) / n
    acc = 0
    for k, s in enumerate(scenes):
        sx = x0 + k * (seg_w + gap)
        fill = clamp((t - acc) / s["duration"])
        d.rounded_rectangle([sx, y, sx + seg_w, y + 8], radius=4, fill=CREME + (70,))
        if fill > 0:
            d.rounded_rectangle([sx, y, sx + max(8, seg_w * fill), y + 8], radius=4, fill=CREME + (235,))
        acc += s["duration"]
    # marque
    pulse = 0.5 + 0.5 * math.sin(t * 4)
    d.ellipse([72, 132, 96, 156], fill=AMBRE + (int(160 + 95 * pulse),))
    d.text((112, 144), "LeCoinRare", font=font("bold", 42), fill=CREME + (255,), anchor="lm")


def wipe(layer, t, boundaries):
    """Volet diagonal ambre aux changements de scène."""
    for b in boundaries:
        p = (t - (b - TRANSITION / 2)) / TRANSITION
        if 0 < p < 1:
            d = ImageDraw.Draw(layer)
            span = W + H * 0.6
            lead = -H * 0.6 + span * ease_in_out(p) * 1.6
            tail = lead - span * 0.55
            for x_a, x_b, col in ((tail, lead, AMBRE), (tail - 40, tail + 30, VERT_CLAIR)):
                d.polygon([(x_a, 0), (x_b, 0), (x_b - H * 0.6, H), (x_a - H * 0.6, H)], fill=col + (255,))


def soften(arr, k):
    """Floute fortement une image (réduction puis agrandissement) : k=1 flou total, k=0 net."""
    if k <= 0:
        return arr
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    blurred = np.asarray(img.resize((W // 28, H // 28), Image.BILINEAR).resize((W, H), Image.BILINEAR), np.float32)
    return arr * (1 - k) + blurred * k


def load_medias(scenes, base_dir):
    medias, credits = {}, []
    for i, s in enumerate(scenes):
        path = os.path.join(base_dir, s["media"]) if s.get("media") else None
        if not path and s.get("media_query"):
            kind, idx, src = s.get("media_kind", "video"), s.get("media_index", 0), s.get("media_source")
            path, credit = banques.fetch(s["media_query"], kind, idx, src)
            if not path and kind == "video":
                path, credit = banques.fetch(s["media_query"], "photo", idx, src)
            if path:
                credits.append(credit)
            else:
                print(f"Scène {i + 1} : aucune image trouvée pour « {s['media_query']} », fond animé seul.")
        if path:
            medias[i] = MediaSource(path, s["duration"])
    return medias, credits


def locate(scenes, t):
    acc = 0
    for i, s in enumerate(scenes):
        if t < acc + s["duration"] or i == len(scenes) - 1:
            return i, s, t - acc
        acc += s["duration"]


def render_frame(scenes, medias, bounds, total, t):
    idx, scene, lt = locate(scenes, t)
    local = clamp(lt / scene["duration"])
    media = medias[idx].frame(local) if idx in medias else None
    if media is not None and scene["type"] == "quiz":
        media = soften(media, 1 - ease_out((lt - quiz_reveal(scene)) / 0.5))
    frame = background(t, media)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    SCENES[scene["type"]](layer, scene, lt)
    draw_icon(layer, scene, local, t)
    chrome(layer, scenes, t, total)
    frame.alpha_composite(layer)
    wipe(frame, t, bounds)
    return frame.convert("RGB")


def main(spec_path, out_path, apercu=False):
    spec = json.load(open(spec_path, encoding="utf-8"))
    scenes = spec["scenes"]
    total = sum(s["duration"] for s in scenes)
    bounds, acc = [], 0
    for s in scenes[:-1]:
        acc += s["duration"]
        bounds.append(acc)
    medias, credits = load_medias(scenes, os.path.dirname(os.path.abspath(spec_path)))
    stem = os.path.splitext(out_path)[0]
    try:
        if apercu:
            acc = 0
            for i, s in enumerate(scenes):
                if s["type"] == "quiz":  # la question avant la réponse, puis la réponse affichée
                    render_frame(scenes, medias, bounds, total, acc + quiz_reveal(s) * 0.8).save(f"{stem}-apercu-{i + 1}q.png")
                    t = acc + min(s["duration"] - 0.05, quiz_reveal(s) + 2.2)
                else:
                    t = acc + s["duration"] * 0.75
                render_frame(scenes, medias, bounds, total, t).save(f"{stem}-apercu-{i + 1}.png")
                acc += s["duration"]
            print(f"Aperçus écrits : {stem}-apercu-*.png")
            return
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-f", "lavfi", "-t", str(total), "-i", "anullsrc=r=44100:cl=stereo",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "21", "-maxrate", "10M", "-bufsize", "20M", "-c:a", "aac",
             "-shortest", "-movflags", "+faststart", out_path],
            stdin=subprocess.PIPE)
        for f in range(int(total * FPS)):
            proc.stdin.write(render_frame(scenes, medias, bounds, total, f / FPS).tobytes())
        proc.stdin.close()
        proc.wait()
    finally:
        for m in medias.values():
            m.close()
    # couverture du Reel : même image que celle choisie dans Metricool (videoCoverMilliseconds)
    cover = min(spec.get("cover_ms", 7500) / 1000, total - 0.1)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(cover), "-i", out_path, "-frames:v", "1", "-q:v", "3", stem + ".jpg"], check=True)
    print(f"Reel prêt : {out_path} ({total:.1f} s) + couverture {stem}.jpg")
    if credits:
        print("Crédits images : " + " ; ".join(credits))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0], args[1], apercu="--apercu" in sys.argv)
