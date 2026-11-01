"""Charte graphique LeCoinRare : le design system « Canopée » du site lecoinrare.com (thème sombre « Deep Forest »).

Référence : docs/design-system.md (fourni par l'équipe le 01/11/2026). Les règles qui comptent sur nos visuels :
- l'or (#D4A853) est réservé aux micro-accents et au dégradé vert → or des titres « hero » (couverture, accroche) ;
  jamais sur un bouton ni sur un gros bloc ;
- les boutons (appels à l'action) sont verts (#326446), texte blanc, coins arrondis « xl » ;
- les cartes : surface #0F1D16, bordure #1A3A2A, coins arrondis « 2xl » ;
- les étiquettes : badge « catégorie » (fond #1A3A2A à 60 %, texte #5E9A6E, bordure #326446 à 40 %) ;
- pas de bleu saturé ; halos d'ambiance #1A3A2A très flous derrière les titres.
Polices : Montserrat (OFL) pour tout, Merriweather italique (OFL) pour les accents (noms scientifiques).
Logo : le caméléon du site (marque/logo.png), suivi de « LeCoin » en blanc et « Rare » en vert accent.
Partagée par reel_dynamique.py, reel.py, carrousel.py et story.py.
"""
import os
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

FOND = (11, 20, 16)          # bg              #0B1410
CARTE = (15, 29, 22)         # surface         #0F1D16  cartes, champs
VERT_SOMBRE = (26, 58, 42)   # secondary       #1A3A2A  bordures, zones atténuées
VERT = (50, 100, 70)         # primary         #326446  boutons, accents forts
ANNEAU = (45, 90, 63)        # ring            #2D5A3F
VERT_TEXTE = (94, 154, 110)  # accent-text     #5E9A6E  texte vert, noms scientifiques, icônes
VERT_VIF = (76, 168, 130)    # accent-bright   #4CA882  survols, liens actifs, mots surlignés
VERT_RARE = VERT_TEXTE       # le « Rare » du nom
OR = (212, 168, 83)          # gold            #D4A853  micro-accents uniquement
BLANC = (244, 244, 245)      # foreground      #F4F4F5
GRIS = (176, 176, 184)       # muted-fg        #B0B0B8  texte secondaire
GRIS_SUBTIL = (113, 113, 122)  # subtle-fg     #71717A  texte tertiaire
ROUGE = (239, 68, 68)        # destructive     #EF4444  erreurs

FONTS = {"black": "Montserrat-Black.ttf", "display": "Montserrat-ExtraBold.ttf", "bold": "Montserrat-Bold.ttf",
         "semibold": "Montserrat-SemiBold.ttf", "medium": "Montserrat-Medium.ttf",
         "serif": ("Merriweather-Italic.ttf", b"Italic"), "serif-bold": ("Merriweather-Italic.ttf", b"Bold Italic")}


@lru_cache(maxsize=None)
def font(name, size):
    nom, variante = FONTS[name] if isinstance(FONTS[name], tuple) else (FONTS[name], None)
    f = ImageFont.truetype(os.path.join(HERE, "fonts", nom), size)
    if variante:
        f.set_variation_by_name(variante)
    return f


@lru_cache(maxsize=None)
def logo(size):
    return Image.open(os.path.join(HERE, "marque", "logo.png")).convert("RGBA").resize((size, size), Image.LANCZOS)


def largeur_marque(size):
    return size * 1.6 + size * 0.3 + font("bold", size).getlength("LeCoinRare")


def marque(img, x, y, size=42, center=False, alpha=255):
    """Logo + nom, centré verticalement sur y ; x = bord gauche (ou centre si center). Renvoie la largeur."""
    f, ico = font("bold", size), int(size * 1.6)
    w = largeur_marque(size)
    if center:
        x -= w / 2
    lg = logo(ico)
    if alpha < 255:
        lg = lg.copy()
        lg.putalpha(lg.getchannel("A").point(lambda a: a * alpha // 255))
    img.paste(lg, (int(x), int(y - ico / 2)), lg)
    d = ImageDraw.Draw(img)
    tx = x + ico + size * 0.3
    rgba = img.mode == "RGBA"
    d.text((tx, y), "LeCoin", font=f, fill=BLANC + ((alpha,) if rgba else ()), anchor="lm")
    d.text((tx + f.getlength("LeCoin"), y), "Rare", font=f, fill=VERT_RARE + ((alpha,) if rgba else ()), anchor="lm")
    return w


def a(couleur, opacite):
    """Couleur RGBA (pour ImageDraw.Draw(img, "RGBA"), qui fond le dessin dans l'image) : a(VERT, 0.4)."""
    return couleur + (int(255 * opacite),)


def degrade(img, xy, texte, f, anchor="la", etendue=None, couleurs=(VERT_TEXTE, OR), contour=0):
    """Texte en dégradé horizontal vert → or (titres « hero » seulement). etendue = (x0, x1) : le dégradé court sur
    toute cette largeur (un titre entier), sinon sur le mot. contour : liseré sombre pour la vidéo."""
    d = ImageDraw.Draw(img)
    if contour:
        d.text(xy, texte, font=f, anchor=anchor, fill=FOND, stroke_width=contour, stroke_fill=FOND)
    x0, y0, x1, y1 = (int(v) for v in d.textbbox(xy, texte, font=f, anchor=anchor))
    if x1 <= x0 or y1 <= y0:
        return
    masque = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(masque).text((xy[0] - x0, xy[1] - y0), texte, font=f, anchor=anchor, fill=255)
    e0, e1 = etendue or (x0, x1)
    t = np.clip((np.arange(x0, x1, dtype=np.float32) - e0) / max(1, e1 - e0), 0, 1)[None, :, None]
    c0, c1 = (np.array(c, np.float32) for c in couleurs)
    bande = np.broadcast_to(c0 * (1 - t) + c1 * t, (y1 - y0, x1 - x0, 3)).astype(np.uint8)
    img.paste(Image.fromarray(np.ascontiguousarray(bande), "RGB"), (x0, y0), masque)


def espace(d, xy, texte, f, fill, pas=0.12, anchor="lm"):
    """Texte en capitales espacées (« tracking-wider » du site). Renvoie la largeur."""
    x, y = xy
    largeur = sum(f.getlength(ch) for ch in texte) + f.size * pas * (len(texte) - 1)
    if anchor[0] == "m":
        x -= largeur / 2
    for ch in texte:
        d.text((x, y), ch, font=f, fill=fill, anchor="l" + anchor[1])
        x += f.getlength(ch) + f.size * pas
    return largeur


def badge(img, texte, x, y, size=32, style="categorie", center=False):
    """Badge du site : « categorie » (vert), « alerte » (rouge, pour les erreurs), « pro » (or, micro-accent).
    x, y = coin haut gauche (x = centre si center). Renvoie le y du bas."""
    fond, encre, bord = {"categorie": (a(VERT_SOMBRE, 0.6), VERT_TEXTE, a(VERT, 0.4)),
                         "alerte": (a(ROUGE, 0.15), (248, 113, 113), a(ROUGE, 0.35)),
                         "pro": (a(OR, 0.15), OR, a(OR, 0.3))}[style]
    f = font("bold", size)
    d = ImageDraw.Draw(img, "RGBA")
    larg = sum(f.getlength(ch) for ch in texte) + size * 0.14 * (len(texte) - 1)
    w, h = larg + size * 1.3, size * 1.75
    if center:
        x -= w / 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=int(h / 2), fill=fond, outline=bord, width=max(2, size // 14))
    espace(d, (x + size * 0.65, y + h / 2), texte, f, encre, pas=0.14)
    return y + h


def bouton(img, texte, x, y, size=44, center=False):
    """Bouton principal du site : vert #326446, texte blanc, coins « xl ». Renvoie le y du bas."""
    f = font("bold", size)
    w, h = f.getlength(texte) + size * 1.6, size * 2.1
    if center:
        x -= w / 2
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + w, y + h], radius=int(size * 0.55), fill=VERT)
    d.text((x + w / 2, y + h / 2), texte, font=f, fill=(255, 255, 255), anchor="mm")
    return y + h


def carte(img, box, opacite=1.0, bord=VERT_SOMBRE, rayon=40, epaisseur=3):
    """Carte du site : surface #0F1D16, bordure #1A3A2A, coins « 2xl ». opacite < 1 sur une photo."""
    ImageDraw.Draw(img, "RGBA").rounded_rectangle(box, radius=rayon, fill=a(CARTE, opacite), outline=bord,
                                                  width=epaisseur)


def halos(base, rng, w, h, n=3):
    """Halos d'ambiance du site : grandes taches #1A3A2A très floues (et une lueur verte diffuse), sur un tableau
    numpy (h, w, 3) en float32."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    teintes = [(VERT_SOMBRE, 0.55, 0.55), (VERT_SOMBRE, 0.45, 0.6), (VERT_VIF, 0.07, 0.5)][:n]
    for couleur, force, rayon in teintes:
        cx, cy = rng.uniform(0.1, 0.9) * w, rng.uniform(0.05, 0.75) * h
        r = rayon * w
        poids = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / r ** 2)[..., None] * force
        base = base * (1 - poids) + np.array(couleur, np.float32) * poids
    return base
