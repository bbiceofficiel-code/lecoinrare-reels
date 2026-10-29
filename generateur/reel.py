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
Voix off française gratuite (Piper, hors ligne) : "voix": "siwis" (féminine) ou "tom" (masculine) à la racine.
Chaque scène lit son texte affiché, ou son champ "narration" ("narration_reponse" pour la réponse d'un quiz) ;
les scènes s'allongent toutes seules pour que la voix ne soit jamais coupée.
--apercu écrit seulement une image PNG par scène, pour vérifier la mise en page en quelques secondes.
"""
import json, math, os, re, subprocess, sys
from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medias as banques

import charte
from charte import font, marque

W, H, FPS = 1080, 1920, 30
# couleurs du site lecoinrare.com (voir charte.py)
VERT = charte.CARTE            # bas du dégradé de fond (presque noir, comme le site)
VERT_FONCE = charte.FOND       # haut du dégradé, texte sur les pastilles dorées
VERT_CLAIR = charte.VERT       # halos, volets
CREME = charte.BLANC           # texte
AMBRE = charte.OR              # surlignage, accents
ROUGE = charte.ROUGE           # erreurs
TURQUOISE = charte.VERT_VIF
TRANSITION = 0.45  # durée du volet entre deux scènes, en secondes


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


LOW = 4  # les halos sont flous : calculés en 270x480 puis agrandis (rendu identique, 4 à 5 fois plus rapide)
BLOB = _radial_sprite(1100 // LOW)
_rng = np.random.default_rng(7)
GRAIN = [(_rng.normal(0, 3.5, (H, W, 1))).astype(np.float32) for _ in range(6)]
_yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
BASE = (np.array(VERT_FONCE, np.float32) * (1 - _yy) + np.array(VERT, np.float32) * _yy) * np.ones((1, W, 1), np.float32)
SHADE = np.clip((_yy - 0.35) / 0.65, 0, 1) ** 1.3  # assombrit le bas d'une photo pour le texte
SHADE_HAUT = np.clip((0.16 - _yy) / 0.16, 0, 1) ** 1.2  # et le haut, pour le logo
_SH = np.maximum(0.75 * SHADE, 0.7 * SHADE_HAUT)
MEDIA_KEEP = (1 - _SH) * 0.82  # fond photo = photo * MEDIA_KEEP + MEDIA_ADD (assombrissements précalculés)
MEDIA_ADD = np.array(VERT_FONCE, np.float32) * _SH * 0.82 + BASE * 0.18
# versions 8 bits pour les additions rapides de Pillow (le grain est décalé de +16, retiré à l'addition)
BASE_IMG = Image.fromarray(np.clip(BASE, 0, 255).astype(np.uint8), "RGB")
GRAIN_IMG = [Image.fromarray(np.clip(g[..., 0] + 16, 0, 255).astype(np.uint8), "L").convert("RGB") for g in GRAIN]

BLOBS = [  # couleur, intensité, centre, amplitude, vitesse, phase
    (AMBRE, 0.13, (880, 380), (140, 120), 0.35, 0.0),
    (TURQUOISE, 0.14, (180, 1100), (160, 200), 0.28, 1.7),
    (VERT_CLAIR, 0.30, (760, 1650), (200, 120), 0.22, 3.1),
]


def add_blob(canvas, color, alpha, cx, cy):
    """Ajoute un halo sur le canevas basse résolution (H/LOW x W/LOW) ; cx, cy en pixels pleine résolution."""
    s, (h, w) = BLOB.shape[0], canvas.shape[:2]
    x0, y0 = int(cx / LOW - s / 2), int(cy / LOW - s / 2)
    sx0, sy0 = max(0, -x0), max(0, -y0)
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(w, x0 + s), min(h, y0 + s)
    if x1c <= x0c or y1c <= y0c:
        return
    sprite = BLOB[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)]
    canvas[y0c:y1c, x0c:x1c] += sprite * (np.array(color, np.float32) * alpha)


class MediaSource:
    """Photo ou vidéo de fond, recadrée en 1080x1920 avec un lent zoom."""

    def __init__(self, path, duration, focus=None):
        """focus = [x, y] entre 0 et 1 : où se trouve l'animal sur la photo (le recadrage vertical le garde au centre)."""
        self.path, self.duration = path, duration
        self.focus = focus
        ext = os.path.splitext(path)[1].lower()
        self.is_video = ext in (".mp4", ".mov", ".webm", ".mkv", ".ogv", ".ogg")
        if self.is_video:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                   capture_output=True, text=True).stdout.strip()
            self.media_len = float(probe) if probe else 0.0
            self.proc, self.next, self.last = None, None, None
        else:
            img = Image.open(path).convert("RGB")
            scale = max(W / img.width, H / img.height) * 1.15
            self.img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)

    def _open(self, idx):
        """(Re)lit la vidéo à partir de l'image idx : les images peuvent être rendues par morceaux, en parallèle."""
        self.close()
        start = (idx / FPS) % self.media_len if self.media_len else 0
        cover = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}"
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", self.path,
             "-t", str(self.duration + 1), "-vf", cover, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.next = idx

    def frame(self, local):
        if self.is_video:
            idx = int(round(local * self.duration * FPS))
            if self.next is not None and idx == self.next - 1 and self.last is not None:
                return self.last.astype(np.float32)  # même image (arrondi)
            if self.next is None or not 0 <= idx - self.next <= 3:
                self._open(idx)
            for _ in range(idx - self.next):  # petit saut : on lit et on jette
                self.proc.stdout.read(W * H * 3)
            raw = self.proc.stdout.read(W * H * 3)
            self.next = idx + 1
            if len(raw) == W * H * 3:
                self.last = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
            return self.last.astype(np.float32) if self.last is not None else BASE.copy()
        z = 1.0 + 0.13 * ease_in_out(local)  # Ken Burns
        cw, ch = W * self.img.width / (W * 1.15 * z), H * self.img.height / (H * 1.15 * z)
        cw, ch = min(cw, self.img.width), min(ch, self.img.height)
        if self.focus:  # léger travelling autour du sujet
            fx, fy = self.focus
            x0 = (self.img.width - cw) * min(1, max(0, fx - 0.08 + 0.16 * local))
            y0 = (self.img.height - ch) * min(1, max(0, fy))
        else:
            x0 = (self.img.width - cw) * (0.35 + 0.3 * local)
            y0 = (self.img.height - ch) * 0.4
        crop = self.img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((W, H), Image.BILINEAR)
        return np.asarray(crop, np.float32)

    def close(self):
        if self.is_video and self.proc:
            self.proc.kill()
            self.proc = None


def background(t, media_frame=None):
    if media_frame is not None:
        img = Image.fromarray(np.clip(media_frame * MEDIA_KEEP + MEDIA_ADD, 0, 255).astype(np.uint8), "RGB")
        blob_gain = 0.5
    else:
        img = BASE_IMG
        blob_gain = 1.0
    halos = np.zeros((H // LOW, W // LOW, 3), np.float32)
    for color, alpha, (cx, cy), (ax, ay), speed, phase in BLOBS:
        add_blob(halos, color, alpha * blob_gain,
                 cx + ax * math.sin(t * speed + phase), cy + ay * math.cos(t * speed * 0.8 + phase))
    halos = Image.fromarray(np.clip(halos, 0, 255).astype(np.uint8), "RGB").resize((W, H), Image.BILINEAR)
    img = ImageChops.add(img, halos)
    img = ImageChops.add(img, GRAIN_IMG[int(t * 8) % len(GRAIN_IMG)], 1.0, -16)
    return img.convert("RGBA")


# ---------------------------------------------------------------- texte animé

@lru_cache(maxsize=512)
def word_sprite(word, fname, size, color):
    f = font(fname, size)
    l, t, r, b = f.getbbox(word)
    img = Image.new("RGBA", (r - l + 8, int(size * 1.25)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((4 - l, int(size * 0.08)), word, font=f, fill=color)
    return img


def parse_words(text):
    """'Un *mot* et *plusieurs mots* surlignés' -> [('Un', False), ('mot', True), ('et', False), ('plusieurs', True), ('mots', True), ...]"""
    out, inside = [], False
    for raw in text.split():
        start, end = raw.startswith("*"), raw.rstrip(".,;:!?…»").endswith("*")
        out.append((raw.replace("*", ""), inside or "*" in raw))
        if start and not end:
            inside = True
        elif end:
            inside = False
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
        m = re.search(r"\d+", label)  # seul le premier nombre défile (« 32-35 °C » : le 32 monte, le 35 reste)
        txt = label
        if m:
            val = int(int(m.group()) * ease_out((p - 0.15) / 0.7))
            txt = label[:m.start()] + str(val) + label[m.end():]
        size = 110 if len(label) <= 6 else 84
        d.text((cx + 120, cy - 40), txt, font=font("display", size), fill=AMBRE + (a,), anchor="lm")


def icon_sun(d, cx, cy, p, label, t):
    """Soleil dont les rayons s'allument et tournent lentement : lumière, UVB."""
    a = int(255 * ease_out(p * 2))
    r = 95
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMBRE + (a,))
    n_on = int(12 * ease_out((p - 0.1) / 0.6))
    for k in range(n_on):
        ang = k * math.pi / 6 + t * 0.4
        r1, r2 = r + 30, r + 30 + 70 * (0.85 + 0.15 * math.sin(t * 3 + k))
        d.line([cx + r1 * math.cos(ang), cy + r1 * math.sin(ang), cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)],
               fill=AMBRE + (a,), width=14)
    d.text((cx, cy), "UV", font=font("display", 64), fill=VERT + (a,), anchor="mm")
    if label:
        d.text((cx, cy + 260), label, font=font("bold", 54), fill=CREME + (a,), anchor="mm")


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
    elif kind == "sun":
        icon_sun(d, cx, cy - 80, p, label, t)


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
    # le caméléon du site apparaît, puis le nom lettre par lettre (« Rare » en vert, comme sur le site)
    p = lt / 0.45
    if p > 0:
        paste_scaled(layer, charte.logo(300), W / 2, 400, 0.4 + 0.6 * ease_back(p), ease_out(p * 1.5))
    word = "LeCoinRare"
    f = font("bold", 128)
    x = (W - f.getlength(word)) / 2
    for k, ch in enumerate(word):
        p = (lt - 0.2 - k * 0.045) / 0.4
        w = f.getlength(ch)
        if p > 0:
            col = charte.VERT_RARE if k >= 6 else CREME
            paste_scaled(layer, word_sprite(ch, "bold", 128, col), x + w / 2, 660 + (1 - ease_out(p)) * 50, 0.5 + 0.5 * ease_back(p), ease_out(p * 1.5))
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
    marque(layer, 70, 148, size=40)  # logo du site + nom


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


# ---------------------------------------------------------------- voix off (Piper : gratuit, hors ligne)

VOIX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voix")
DICTION = [  # ce que la voix doit dire à la place de ce qui est écrit
    ("lecoinrare.com", "Le Coin Rare"), ("@lecoinrare", "le coin rare"), ("LeCoinRare", "Le Coin Rare"),
    (" °C", " degrés"), ("°C", " degrés"), ("n°", "numéro "), ("NAC", "nac"), ("UVI", "indice u-vé"), ("indice UV", "indice u-vé"), ("UVB", "u-vé-bé"),
    ("&", "et"), ("D3", "D trois"), ("pH", "pé-hache"),("quiz", "kouiz"), ("Quiz", "Kouiz"),  # sinon elle dit « kizz »
]


def diction(text):
    t = text.replace("*", "")
    for a, b in DICTION:
        t = t.replace(a, b)
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"\s*\.\s*\.", ".", t).strip(" .") + "."


def narrations(s):
    """Ce que la voix lit dans une scène : champ "narration" (et "narration_reponse" pour un quiz), sinon le texte affiché."""
    if s["type"] == "quiz":
        return [s.get("narration", f'{s["title"]} {s.get("text", "")}'),
                s.get("narration_reponse", f'{s["answer"]}. {s.get("answer_text", "")}')]
    if s.get("narration"):
        return [s["narration"]]
    if s["type"] == "hook":
        return [f'{s["title"]}. {s.get("subtitle", "")}']
    if s["type"] == "point":
        n = f'Erreur numéro {s["n"]}' if s.get("tag", "ERREUR") == "ERREUR" else f'Numéro {s["n"]}'
        return [f'{n} : {s["title"]}. {s["text"]}']
    return [f'{s["title"]}. {s.get("text", "")}. {s.get("cta", "Abonnez-vous")} !']


def synth(voice, text):
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        try:
            from piper import SynthesisConfig
            voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=0.9))  # un peu plus vif, rythme Reel
        except ImportError:
            voice.synthesize_wav(text, wf)
    buf.seek(0)
    with wave.open(buf) as wf:
        sr = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    return sr, data


VOIX_NATURELLES = ("estelle",)  # Chatterbox (voix_naturelle.py) ; "siwis" et "tom" = Piper, plus synthétiques
VOIX_PY = os.environ.get("LECOINRARE_VOIX_PY",
                         os.path.join(os.environ.get("LOCALAPPDATA", ""), "lecoinrare-voix", "venv", "Scripts", "python.exe"))


def synth_naturelle(name, texts):
    """Toutes les phrases d'un Reel d'un coup (le modèle ne se charge qu'une fois), dans l'environnement de la voix."""
    import subprocess, tempfile, wave
    with tempfile.TemporaryDirectory() as tmp:
        demandes = [{"text": t, "out": os.path.join(tmp, f"{i}.wav")} for i, t in enumerate(texts)]
        with open(os.path.join(tmp, "demandes.json"), "w", encoding="utf-8") as f:
            json.dump(demandes, f, ensure_ascii=False)
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voix_naturelle.py")
        subprocess.run([VOIX_PY, script, os.path.join(tmp, "demandes.json"), name], check=True)
        out = []
        for d in demandes:
            with wave.open(d["out"]) as wf:
                data = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
                out.append((wf.getframerate(), data))
        return out


def prepare_voix(spec):
    """Synthétise la voix off ("voix": "estelle", ou "siwis"/"tom" en Piper) et allonge les scènes pour
    qu'elle ne soit jamais coupée. Renvoie [(instant en s, fréquence, échantillons)], ou [] sans voix."""
    name = spec.get("voix")
    if not name:
        return []
    par_scene = [[diction(t) for t in narrations(s)] for s in spec["scenes"]]
    if name in VOIX_NATURELLES:
        flat = iter(synth_naturelle(name, [t for texts in par_scene for t in texts]))
        audios = [[next(flat) for _ in texts] for texts in par_scene]
    else:
        from piper import PiperVoice
        voice = PiperVoice.load(os.path.join(VOIX_DIR, f"fr_FR-{name}-medium.onnx"))
        audios = [[synth(voice, t) for t in texts] for texts in par_scene]
    clips, acc = [], 0.0
    for s, audio in zip(spec["scenes"], audios):
        lens = [len(a[1]) / a[0] for a in audio]
        start = 0.6 if s["type"] == "outro" else 0.35
        if s["type"] == "quiz":
            s["reveal"] = max(quiz_reveal(s), start + lens[0] + 0.5)
            s["duration"] = max(s["duration"], s["reveal"] + 0.15 + lens[1] + 0.6)
            offsets = [start, s["reveal"] + 0.15]
        else:
            s["duration"] = max(s["duration"], start + lens[0] + 0.5)
            offsets = [start]
        for off, (sr, data) in zip(offsets, audio):
            clips.append((acc + off, sr, data))
        acc += s["duration"]
    return clips


def write_voix(clips, total, path):
    import wave
    sr = clips[0][1]
    track = np.zeros(int(total * sr) + 1, np.float32)
    for t, _, data in clips:
        i = int(t * sr)
        n = min(len(data), len(track) - i)
        track[i:i + n] += data[:n]
    peak = np.abs(track).max() or 1
    track = track / peak * 0.89  # -1 dB
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((track * 32767).astype(np.int16).tobytes())


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
            medias[i] = MediaSource(path, s["duration"], s.get("media_focus"))
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


# ---------------------------------------------------------------- rendu en parallèle et encodage

_W = {}  # état de chaque processus de rendu


def _init_worker(scenes, base_dir, bounds, total):
    medias, _ = load_medias(scenes, base_dir)
    _W.update(scenes=scenes, medias=medias, bounds=bounds, total=total)


def _render_chunk(rng):
    f0, f1 = rng
    return b"".join(render_frame(_W["scenes"], _W["medias"], _W["bounds"], _W["total"], f / FPS).tobytes()
                    for f in range(f0, f1))


@lru_cache(maxsize=1)
def encodeur():
    """NVENC (carte graphique NVIDIA) s'il est là : bien plus rapide ; sinon x264 sur le processeur."""
    test = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                           "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
    if test.returncode == 0:
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "23", "-b:v", "5M",
                "-maxrate", "7M", "-bufsize", "14M", "-profile:v", "high"]
    # débit plafonné : un Reel de 60 s reste sous 50 Mo (limite d'envoi des bots Telegram)
    return ["-c:v", "libx264", "-preset", "slow", "-crf", "21", "-maxrate", "7M", "-bufsize", "14M"]


def main(spec_path, out_path, apercu=False):
    import time
    t_start = time.time()
    spec = json.load(open(spec_path, encoding="utf-8"))
    scenes = spec["scenes"]
    clips = prepare_voix(spec)  # allonge les scènes si la voix off en a besoin
    t_voix = time.time()
    total = sum(s["duration"] for s in scenes)
    bounds, acc = [], 0
    for s in scenes[:-1]:
        acc += s["duration"]
        bounds.append(acc)
    medias, credits = load_medias(scenes, os.path.dirname(os.path.abspath(spec_path)))
    stem = os.path.splitext(out_path)[0]
    audio = ["-f", "lavfi", "-t", str(total), "-i", "anullsrc=r=44100:cl=stereo"]
    voix_wav = None
    if clips and not apercu:
        voix_wav = stem + "-voix.wav"
        write_voix(clips, total, voix_wav)
        audio = ["-i", voix_wav]
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
             *audio, *encodeur(), "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
             "-t", str(total), "-movflags", "+faststart", out_path],
            stdin=subprocess.PIPE)
        # images rendues par paquets de 12 sur plusieurs processus, écrites dans l'ordre ; au plus 2 paquets
        # d'avance par processus pour ne pas remplir la mémoire
        import multiprocessing as mp
        n, step = int(total * FPS), 12
        chunks = [(f, min(n, f + step)) for f in range(0, n, step)]
        workers = max(1, min(6, (os.cpu_count() or 2) - 1))
        with mp.Pool(workers, _init_worker, (scenes, os.path.dirname(os.path.abspath(spec_path)), bounds, total)) as pool:
            pending = [pool.apply_async(_render_chunk, (c,)) for c in chunks[:workers * 2]]
            for k in range(len(chunks)):
                proc.stdin.write(pending.pop(0).get())
                if k + workers * 2 < len(chunks):
                    pending.append(pool.apply_async(_render_chunk, (chunks[k + workers * 2],)))
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError("ffmpeg a échoué pendant l'encodage")
    finally:
        for m in medias.values():
            m.close()
        if voix_wav and os.path.exists(voix_wav):
            os.remove(voix_wav)
    # couverture du Reel : même image que celle choisie dans Metricool (videoCoverMilliseconds)
    cover = min(spec.get("cover_ms", 7500) / 1000, total - 0.1)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(cover), "-i", out_path, "-frames:v", "1", "-q:v", "3", stem + ".jpg"], check=True)
    print(f"Reel prêt : {out_path} ({total:.1f} s, {os.path.getsize(out_path) / 1e6:.0f} Mo) + couverture {stem}.jpg "
          f"— voix {t_voix - t_start:.0f} s, images et encodage {time.time() - t_voix:.0f} s")
    if credits:
        print("Crédits images : " + " ; ".join(credits))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0], args[1], apercu="--apercu" in sys.argv)
