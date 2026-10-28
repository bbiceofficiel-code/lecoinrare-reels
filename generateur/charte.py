"""Charte graphique LeCoinRare, reprise du site lecoinrare.com (son thème sombre, affiché par défaut).

Couleurs : variables CSS du site. Police : Montserrat, celle du site (licence OFL, dans fonts/).
Logo : le caméléon du site (marque/logo.png), suivi de « LeCoin » en blanc et « Rare » en vert, comme l'en-tête.
Partagée par reel.py, carrousel.py et story.py.
"""
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

FOND = (11, 20, 16)          # --background      #0B1410
CARTE = (15, 29, 22)         # --card            #0F1D16
VERT_SOMBRE = (26, 58, 42)   # --secondary       #1A3A2A
VERT = (58, 138, 106)        # #3A8A6A, vert des boutons et des graphiques
VERT_VIF = (73, 159, 124)    # --accent-bright   #499F7C
VERT_RARE = (88, 142, 106)   # --accent-text     #588E6A, le « Rare » du nom
VERT_LOGO = (71, 162, 75)    # caméléon          #47A24B
OR = (212, 168, 83)          # --gold            #D4A853
BLANC = (244, 244, 245)      # --foreground      #F4F4F5
GRIS = (176, 176, 185)       # --muted-foreground #B0B0B9
ROUGE = (239, 68, 68)        # --destructive     #EF4444

FONTS = {"black": "Montserrat-Black.ttf", "display": "Montserrat-ExtraBold.ttf", "bold": "Montserrat-Bold.ttf",
         "semibold": "Montserrat-SemiBold.ttf", "medium": "Montserrat-Medium.ttf"}


@lru_cache(maxsize=None)
def font(name, size):
    return ImageFont.truetype(os.path.join(HERE, "fonts", FONTS[name]), size)


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
