"""Génère les stories Instagram/Facebook (1080x1920, JPG) au design system « Canopée » de LeCoinRare.

Usage : python3 story.py stories.json dossier_sortie

Types : savoir (« Le saviez-vous ? »), sondage (2 options), quiz (3 options), question (boîte à questions),
teaser (annonce d'un Reel, avec sa couverture en "media").
Les zones du haut (profil) et du bas (barre de réponse) d'Instagram restent libres.
Les autocollants interactifs (sondage, quiz, question, lien) ne peuvent pas être posés par l'API : les options sont
dessinées sur l'image et l'autocollant se pose par-dessus dans l'app, au moment de valider (Metricool envoie une
notification pour ces stories-là).
Une story peut avoir une photo de fond : "media" (chemin relatif au JSON) ou "media_query" (voir medias.py).
"""
import json, os, sys

from PIL import ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carrousel as c
import charte
import medias

c.H = 1920  # même style que les carrousels, au format story
W, H, M = c.W, c.H, c.M
TOP, BOTTOM = 400, H - 380  # zone sûre entre la barre de profil et la barre de réponse


def options(img, items, y, letters=False):
    """Options en boutons « secondaires » du site : carte, bordure verte à 30 %, lettre en vert vif."""
    d = ImageDraw.Draw(img, "RGBA")
    place = W - 2 * M - (112 + 40 if letters else 80)  # largeur utile dans le bouton
    taille = 52
    while taille > 34 and max(charte.font("bold", taille).getlength(o) for o in items) > place:
        taille -= 2  # une option longue rétrécit plutôt que de déborder
    f = charte.font("bold", taille)
    for k, opt in enumerate(items):
        d.rounded_rectangle([M, y, W - M, y + 140], radius=36, fill=charte.a(charte.CARTE, 0.94),
                            outline=charte.a(charte.VERT, 0.6), width=3)
        if letters:
            d.text((M + 56, y + 70), "ABC"[k], font=charte.font("black", 56), fill=charte.VERT_VIF, anchor="mm")
            d.text((M + 112, y + 70), opt, font=f, fill=charte.BLANC, anchor="lm")
        else:
            d.text((W / 2, y + 70), opt, font=f, fill=charte.BLANC, anchor="mm")
        y += 170
    return y


def titre(img, s, kicker, size):
    y = charte.badge(img, s.get("kicker", kicker), M, TOP, size=36) + 56
    return c.rich(img, s["title"], y, "black", size, charte.BLANC, gap=1.08, hero=True,
                  ombre=bool(s.get("media") or s.get("media_query")))


def story_savoir(img, s):
    y = titre(img, s, "LE SAVIEZ-VOUS ?", 96)
    if s.get("text") and (s.get("media") or s.get("media_query")):  # sur une photo : le texte dans une carte
        taille = 46
        while taille > 36 and c.texte_en_carte(img, s["text"], y + 40, size=taille, dessiner=False) > BOTTOM - 20:
            taille -= 2  # la carte ne doit pas toucher le logo ni la barre de réponse
        c.texte_en_carte(img, s["text"], y + 40, size=taille)
    elif s.get("text"):
        c.rich(img, s["text"], y + 40, "medium", 50, charte.GRIS, gap=1.3)
    return img


def story_sondage(img, s):
    y = titre(img, s, "SONDAGE", 92) + 60
    y = options(img, s["options"][:4], y)  # le sondage Instagram accepte 4 réponses
    ImageDraw.Draw(img).text((W / 2, y + 30), s.get("hint", "Votez avec le sondage"), font=charte.font("medium", 40),
                             fill=charte.GRIS, anchor="mm")
    return img


def story_quiz(img, s):
    y = titre(img, s, "QUIZ", 88) + 60
    options(img, s["options"][:3], y, letters=True)
    return img


def story_question(img, s):
    y = titre(img, s, "VOS QUESTIONS", 92)
    if s.get("text"):
        y = c.rich(img, s["text"], y + 40, "medium", 50, charte.GRIS, gap=1.3)
    ImageDraw.Draw(img, "RGBA").rounded_rectangle([M, y + 70, W - M, y + 330], radius=40,  # place de l'autocollant
                                                  outline=charte.a(charte.VERT_VIF, 0.5), width=4)
    return img


def story_teaser(img, s):
    titre(img, s, "NOUVEAU REEL", 96)
    charte.bouton(img, s.get("cta", "À voir sur notre profil"), W / 2, BOTTOM - 160, size=46, center=True)
    return img


STORIES = {"savoir": story_savoir, "sondage": story_sondage, "quiz": story_quiz, "question": story_question, "teaser": story_teaser}


def brand(img):
    c.marque(img, M, BOTTOM + 40, size=34)


def main(spec_path, out_dir):
    spec = json.load(open(spec_path, encoding="utf-8"))
    base_dir = os.path.dirname(os.path.abspath(spec_path))
    os.makedirs(out_dir, exist_ok=True)
    credits = []
    for i, s in enumerate(spec["stories"], 1):
        photo = os.path.join(base_dir, s["media"]) if s.get("media") else None
        if not photo and s.get("media_query"):
            photo, credit = medias.fetch(s["media_query"], "photo", s.get("media_index", 0), s.get("media_source"))
            if credit:
                credits.append(credit)
        img = STORIES[s["type"]](c.backdrop(i * 11, photo), s)
        brand(img)
        img.save(os.path.join(out_dir, f"{i:02d}.jpg"), quality=92, subsampling=0)
    print(f"Stories prêtes : {len(spec['stories'])} images dans {out_dir}")
    if credits:
        print("Crédits images : " + " ; ".join(credits))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
