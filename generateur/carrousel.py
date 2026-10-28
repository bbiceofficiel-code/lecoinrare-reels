"""Génère un carrousel Instagram 1080x1350 (images JPG) aux couleurs de LeCoinRare à partir d'un fichier JSON.

Usage : python3 carrousel.py spec.json dossier_sortie

Types de slides : cover, point, checklist, end. Dans les titres, les mots entre *astérisques* sont surlignés.
Une slide peut avoir une photo de fond : "media" (chemin relatif au JSON) ou "media_query"
(recherche en anglais dans Pexels, Pixabay puis Wikimedia Commons, voir medias.py ; "media_index", "media_source").
"""
import json, os, sys
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medias

W, H = 1080, 1350
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
M = 84  # marge latérale


@lru_cache(maxsize=None)
def font(name, size):
    return ImageFont.truetype(FONTS[name], size)


def backdrop(seed, photo=None):
    """Dégradé vert de marque, halos colorés et grain ; une photo éventuelle passe dessous, assombrie."""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    base = (np.array(VERT_FONCE, np.float32) * (1 - y) + np.array(VERT, np.float32) * y) * np.ones((1, W, 1), np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    rng = np.random.default_rng(seed)
    for color, alpha, rad in ((AMBRE, 0.20, 520), (TURQUOISE, 0.15, 600), (VERT_CLAIR, 0.40, 640)):
        cx, cy = rng.uniform(0, W), rng.uniform(0, H)
        base += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / rad ** 2 * 1.6)[..., None] * (np.array(color, np.float32) * alpha)
    if photo:
        img = Image.open(photo).convert("RGB")
        s = max(W / img.width, H / img.height)
        img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
        x0, y0 = (img.width - W) // 2, (img.height - H) // 2
        base = np.asarray(img.crop((x0, y0, x0 + W, y0 + H)), np.float32) * 0.42 + base * 0.58
    base += rng.normal(0, 3, (H, W, 1)).astype(np.float32)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def rich(d, text, y, fname, size, color, x=M, max_w=W - 2 * M, align="left", gap=1.12):
    """Texte avec retour à la ligne ; les *mots* sont surlignés en ambre. Renvoie le y de fin."""
    f = font(fname, size)
    sp, pad = f.getlength(" "), size * 0.16
    lines, cur, cw = [], [], 0
    for raw in text.split():
        word, hl = raw.replace("*", ""), "*" in raw
        ww = f.getlength(word) + (2 * pad if hl else 0)
        if cur and cw + sp + ww > max_w:
            lines.append((cur, cw))
            cur, cw = [], 0
        cw += (sp if cur else 0) + ww
        cur.append((word, hl, ww))
    if cur:
        lines.append((cur, cw))
    for words, lw in lines:
        lx = (W - lw) / 2 if align == "center" else x
        for word, hl, ww in words:
            if hl:
                d.rounded_rectangle([lx, y + size * 0.1, lx + ww, y + size * 1.16], radius=int(size * 0.18), fill=AMBRE)
            d.text((lx + (pad if hl else 0), y + size * 0.92), word, font=f, fill=VERT_FONCE if hl else color, anchor="ls")
            lx += ww + sp
        y += int(size * gap)
    return y


def pill(d, text, x, y, bg, fg, size=34, center=False):
    f = font("bold", size)
    w, h = f.getlength(text) + size * 1.2, size * 1.7
    if center:
        x = (W - w) / 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=int(h / 2), fill=bg)
    d.text((x + size * 0.6, y + h / 2), text, font=f, fill=fg, anchor="lm")
    return y + h


def slide_cover(img, s):
    d = ImageDraw.Draw(img)
    y = pill(d, s.get("kicker", ""), M, 150, AMBRE, VERT_FONCE) + 50 if s.get("kicker") else 230
    y = rich(d, s["title"], y, "black", 100, CREME, gap=1.08)
    if s.get("subtitle"):
        rich(d, s["subtitle"], y + 36, "medium", 44, CREME, gap=1.3)
    return img


def slide_point(img, s):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((W - 40, -60), str(s["n"]), font=font("black", 460), fill=(0, 0, 0, 0), anchor="ra",
                                stroke_width=6, stroke_fill=(ROUGE if s.get("warn") else AMBRE) + (140,))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img)
    y = pill(d, s.get("tag", f"ÉTAPE {s['n']}"), M, 360, ROUGE if s.get("warn") else AMBRE, CREME if s.get("warn") else VERT_FONCE) + 44
    y = rich(d, s["title"], y, "black", 82, CREME, gap=1.08)
    rich(d, s["text"], y + 30, "medium", 44, CREME, gap=1.32)
    return img


def slide_checklist(img, s):
    d = ImageDraw.Draw(img)
    y = pill(d, s.get("kicker", "CHECKLIST"), M, 150, AMBRE, VERT_FONCE) + 44
    y = rich(d, s["title"], y, "black", 76, CREME, gap=1.08) + 36
    for item in s["items"]:
        b = 52
        d.rounded_rectangle([M, y + 8, M + b, y + 8 + b], radius=12, fill=AMBRE)
        d.line([(M + 13, y + 36), (M + 23, y + 46), (M + 40, y + 22)], fill=VERT_FONCE, width=7, joint="curve")
        y = rich(d, item, y, "medium", 42, CREME, x=M + b + 28, max_w=W - 2 * M - b - 28, gap=1.28) + 22
    return img


def slide_end(img, s):
    d = ImageDraw.Draw(img)
    f = font("black", 120)
    x = (W - f.getlength("LeCoinRare")) / 2
    d.text((x, 470), "LeCoin", font=f, fill=CREME, anchor="ls")
    d.text((x + f.getlength("LeCoin"), 470), "Rare", font=f, fill=AMBRE, anchor="ls")
    y = rich(d, s["title"], 540, "display", 64, CREME, align="center")
    if s.get("text"):
        y = rich(d, s["text"], y + 20, "bold", 44, AMBRE, align="center", gap=1.3)
    pill(d, s.get("cta", "Suivez @lecoinrare"), 0, y + 60, AMBRE, VERT_FONCE, size=46, center=True)
    return img


SLIDES = {"cover": slide_cover, "point": slide_point, "checklist": slide_checklist, "end": slide_end}


def footer(img, i, n):
    d = ImageDraw.Draw(img)
    y = H - 84
    d.ellipse([M, y - 11, M + 22, y + 11], fill=AMBRE)
    d.text((M + 36, y), "LeCoinRare", font=font("bold", 34), fill=CREME, anchor="lm")
    for k in range(n):  # points de progression
        cx = W / 2 + (k - (n - 1) / 2) * 26
        d.ellipse([cx - 6, y - 6, cx + 6, y + 6], fill=AMBRE if k == i - 1 else (90, 110, 96))
    d.text((W - M, y), "Glissez →" if i < n else "lecoinrare.com", font=font("bold", 32), fill=AMBRE if i < n else CREME, anchor="rm")


def main(spec_path, out_dir):
    spec = json.load(open(spec_path, encoding="utf-8"))
    base_dir = os.path.dirname(os.path.abspath(spec_path))
    os.makedirs(out_dir, exist_ok=True)
    slides, credits = spec["slides"], []
    for i, s in enumerate(slides, 1):
        photo = os.path.join(base_dir, s["media"]) if s.get("media") else None
        if not photo and s.get("media_query"):
            photo, credit = medias.fetch(s["media_query"], "photo", s.get("media_index", 0), s.get("media_source"))
            if credit:
                credits.append(credit)
            else:
                print(f"Slide {i} : aucune photo trouvée pour « {s['media_query']} », fond de marque seul.")
        img = SLIDES[s["type"]](backdrop(i * 7, photo), s)
        footer(img, i, len(slides))
        img.save(os.path.join(out_dir, f"{i:02d}.jpg"), quality=92, subsampling=0)
    print(f"Carrousel prêt : {len(slides)} slides dans {out_dir}")
    if credits:
        print("Crédits images : " + " ; ".join(credits))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
