"""Génère un carrousel Instagram 1080x1350 (images JPG) au design system « Canopée » de LeCoinRare (voir charte.py).

Usage : python3 carrousel.py spec.json dossier_sortie

Types de slides : cover, point, checklist, end. Dans les textes, les mots entre *astérisques* sont surlignés
(dégradé vert → or sur le titre de couverture, vert vif ailleurs) et les mots entre _tirets bas_ s'écrivent en
italique Merriweather vert (noms scientifiques : _Eublepharis macularius_).
Une slide peut avoir une photo de fond : "media" (chemin relatif au JSON) ou "media_query"
(recherche en anglais dans Pexels, Pixabay puis Wikimedia Commons, voir medias.py ; "media_index", "media_source").
"""
import json, os, re, sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charte
import medias
from charte import font, marque

W, H = 1080, 1350
M = 84  # marge latérale
PAD = 44  # marge intérieure des cartes


def backdrop(seed, photo=None):
    """Fond du site (#0B1410) avec ses halos d'ambiance et un grain léger ; une photo éventuelle passe dessous,
    assombrie, et se fond dans le fond vers le bas (« from-surface to-transparent »)."""
    rng = np.random.default_rng(seed)
    base = charte.halos(np.ones((H, W, 3), np.float32) * np.array(charte.FOND, np.float32), rng, W, H)
    if photo:
        img = Image.open(photo).convert("RGB")
        s = max(W / img.width, H / img.height)
        img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
        x0, y0 = (img.width - W) // 2, (img.height - H) // 2
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        part = 0.36 * (1 - np.clip((y - 0.45) / 0.5, 0, 1) ** 1.3)  # visible en haut, fondue en bas ; le texte reste lisible
        base = np.asarray(img.crop((x0, y0, x0 + W, y0 + H)), np.float32) * part + base * (1 - part)
    base += rng.normal(0, 2.5, (H, W, 1)).astype(np.float32)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def _mots(text):
    """[(mot, style)] : style "hl" (*…*), "latin" (_…_) ou None."""
    out, etat = [], None
    text = re.sub(r"(\d) (°C|%|dB|Hz|cm|mm|kg|g|h|min)\b", "\\1\u00a0\\2", text)  # « 25 °C » ne se coupe pas
    for raw in re.split(r"[ \t\n]+", text.strip()):
        ouvre = raw[:len(raw) - len(raw.lstrip("(«“"))]  # « (_Python regius_) » : le marqueur suit la parenthèse
        mot = raw[len(ouvre):]
        for marque_, style in (("*", "hl"), ("_", "latin")):
            if mot.startswith(marque_):
                etat, mot = style, mot[1:]
        mot = ouvre + mot
        fin = None
        for marque_, style in (("*", "hl"), ("_", "latin")):
            coeur = mot.rstrip(".,;:!?…»)")
            if coeur.endswith(marque_):
                mot, fin = coeur[:-1] + mot[len(coeur):], style
        out.append((mot, etat))
        if fin:
            etat = None
    return out


def rich(img, text, y, fname, size, color, x=M, max_w=W - 2 * M, align="left", gap=1.12, hero=False, dessiner=True,
         ombre=False):
    """Texte avec retour à la ligne et mots surlignés (voir en haut). hero : dégradé vert → or sur les mots
    surlignés (titres de couverture). ombre : liseré sombre diffus, pour un titre posé sur une photo.
    dessiner=False : mesure seulement. Renvoie le y de fin."""
    f, fl = font(fname, size), font("serif-bold" if fname in ("black", "display", "bold") else "serif", size)
    sp = f.getlength(" ")
    lignes, cur, cw = [], [], 0
    for mot, style in _mots(text):
        ww = (fl if style == "latin" else f).getlength(mot)
        if cur and cw + sp + ww > max_w:
            lignes.append((cur, cw))
            cur, cw = [], 0
        cw += (sp if cur else 0) + ww
        cur.append((mot, style, ww))
    if cur:
        lignes.append((cur, cw))
    if not dessiner:
        return y + int(size * gap) * len(lignes)
    d, dv = ImageDraw.Draw(img), ImageDraw.Draw(img, "RGBA")
    for mots, lw in lignes:
        lx = x + (max_w - lw) / 2 if align == "center" else x
        for mot, style, ww in mots:
            pos = (lx, y + size * 0.92)
            if ombre:
                dv.text(pos, mot, font=fl if style == "latin" else f, anchor="ls", fill=charte.a(charte.FOND, 0.55),
                        stroke_width=max(4, size // 11), stroke_fill=charte.a(charte.FOND, 0.55))
            if style == "hl" and hero:
                charte.degrade(img, pos, mot, f, anchor="ls", etendue=(x, x + max_w))
            else:
                couleur = {"hl": charte.VERT_VIF, "latin": charte.VERT_TEXTE}.get(style, color)
                d.text(pos, mot, font=fl if style == "latin" else f, fill=couleur, anchor="ls")
            lx += ww + sp
        y += int(size * gap)
    return y


def texte_en_carte(img, text, y, size=42, opacite=0.92, dessiner=True):
    """Paragraphe dans une carte du site (surface, bordure, coins arrondis). Renvoie le y du bas de la carte."""
    inner = W - 2 * M - 2 * PAD
    bas = rich(img, text, y + PAD - size * 0.1, "medium", size, charte.BLANC, x=M + PAD, max_w=inner, gap=1.32,
               dessiner=False) + PAD - size * 0.25
    if not dessiner:
        return bas
    charte.carte(img, [M, y, W - M, bas], opacite)
    rich(img, text, y + PAD - size * 0.1, "medium", size, charte.BLANC, x=M + PAD, max_w=inner, gap=1.32)
    return bas


def slide_cover(img, s):
    y = charte.badge(img, s["kicker"], M, 150, size=32) + 56 if s.get("kicker") else 230
    photo = bool(s.get("media") or s.get("media_query"))
    y = rich(img, s["title"], y, "black", 100, charte.BLANC, gap=1.08, hero=True, ombre=photo)
    if s.get("subtitle"):
        rich(img, s["subtitle"], y + 36, "medium", 44, charte.GRIS, gap=1.3, ombre=photo)
    return img


def slide_point(img, s):
    warn = s.get("warn")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((W - 40, -60), str(s["n"]), font=font("black", 460), fill=(0, 0, 0, 0), anchor="ra",
                                stroke_width=6, stroke_fill=(charte.ROUGE + (110,)) if warn else (charte.VERT_VIF + (120,)))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    # bloc centré dans la hauteur libre (sous le grand chiffre, au-dessus du pied de page)
    hauteur = texte_en_carte(img, s["text"], rich(img, s["title"], 100, "black", 82, None, gap=1.08, dessiner=False) + 34,
                             dessiner=False)
    y = max(340, (H - 150 - hauteur) / 2 + 60)
    y = charte.badge(img, s.get("tag", f"ÉTAPE {s['n']}"), M, y, size=32, style="alerte" if warn else "categorie") + 44
    y = rich(img, s["title"], y, "black", 82, charte.BLANC, gap=1.08)
    texte_en_carte(img, s["text"], y + 34)
    return img


def slide_checklist(img, s):
    b, tx = 48, M + PAD + 48 + 26
    inner = W - M - PAD - tx
    hauteurs = [rich(img, it, 0, "medium", 40, charte.BLANC, x=tx, max_w=inner, gap=1.28, dessiner=False) for it in s["items"]]
    total = 100 + rich(img, s["title"], 0, "black", 76, None, gap=1.08, dessiner=False) + 36 + 2 * PAD + sum(hauteurs) \
        + 22 * (len(hauteurs) - 1)
    y = charte.badge(img, s.get("kicker", "CHECKLIST"), M, max(150, (H - 150 - total) / 2), size=32) + 44
    y = rich(img, s["title"], y, "black", 76, charte.BLANC, gap=1.08) + 36
    charte.carte(img, [M, y, W - M, y + 2 * PAD + sum(hauteurs) + 22 * (len(hauteurs) - 1) - 10], 0.92)
    d = ImageDraw.Draw(img)
    y += PAD - 6
    for item, h in zip(s["items"], hauteurs):
        bx = M + PAD
        if s.get("warn"):  # liste d'erreurs : une croix rouge, pas une coche (qui dirait « à faire »)
            d.rounded_rectangle([bx, y + 4, bx + b, y + 4 + b], radius=12, fill=charte.ROUGE)
            d.line([(bx + 14, y + 18), (bx + 34, y + 38)], fill=charte.BLANC, width=6)
            d.line([(bx + 34, y + 18), (bx + 14, y + 38)], fill=charte.BLANC, width=6)
        else:
            d.rounded_rectangle([bx, y + 4, bx + b, y + 4 + b], radius=12, fill=charte.VERT)
            d.line([(bx + 12, y + 30), (bx + 21, y + 39), (bx + 37, y + 17)], fill=(255, 255, 255), width=6, joint="curve")
        rich(img, item, y, "medium", 40, charte.BLANC, x=tx, max_w=inner, gap=1.28)
        y += h + 22
    return img


def confiance(img, y):
    """Bandeau de confiance du site : capitales espacées gris discret, puce verte."""
    d = ImageDraw.Draw(img)
    f = font("semibold", 24)
    textes = charte.MARQUE.get("confiance", [])
    largeurs = [sum(f.getlength(ch) for ch in t) + 24 * 0.14 * (len(t) - 1) for t in textes]
    x = (W - sum(largeurs) - len(textes) * 30 - max(0, len(textes) - 1) * 60) / 2
    for t, lw in zip(textes, largeurs):
        d.ellipse([x, y - 7, x + 14, y + 7], fill=charte.VERT)
        charte.espace(d, (x + 30, y), t, f, charte.GRIS_SUBTIL, pas=0.14)
        x += 30 + lw + 60


def slide_end(img, s):
    img.paste(charte.logo(220), ((W - 220) // 2, 150), charte.logo(220))
    d = ImageDraw.Draw(img)
    f = font("bold", 104)
    x = (W - f.getlength(charte.NOM)) / 2
    d.text((x, 470), charte.NOM_DEBUT, font=f, fill=charte.BLANC, anchor="ls")
    d.text((x + f.getlength(charte.NOM_DEBUT), 470), charte.NOM_FIN, font=f, fill=charte.VERT_RARE, anchor="ls")
    y = rich(img, s["title"], 540, "display", 64, charte.BLANC, align="center")
    if s.get("text"):
        y = rich(img, s["text"], y + 20, "semibold", 42, charte.GRIS, align="center", gap=1.3)
    y = charte.bouton(img, s.get("cta", "Suivez " + charte.COMPTE), W / 2, y + 56, size=44, center=True)
    confiance(img, y + 70)
    return img


SLIDES = {"cover": slide_cover, "point": slide_point, "checklist": slide_checklist, "end": slide_end}


def footer(img, i, n):
    d = ImageDraw.Draw(img)
    y = H - 84
    marque(img, M, y, size=32)
    for k in range(n):  # points de progression
        cx = W / 2 + (k - (n - 1) / 2) * 26
        r = 7 if k == i - 1 else 5
        d.ellipse([cx - r, y - r, cx + r, y + r], fill=charte.VERT_VIF if k == i - 1 else (38, 74, 54))
    d.text((W - M, y), "Glissez →" if i < n else charte.SITE, font=font("bold", 30),
           fill=charte.VERT_TEXTE if i < n else charte.GRIS, anchor="rm")


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
