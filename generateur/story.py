"""Génère les stories Instagram/Facebook (1080x1920, JPG) aux couleurs de LeCoinRare à partir d'un fichier JSON.

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
import medias

c.H = 1920  # même style que les carrousels, au format story
W, H, M = c.W, c.H, c.M
TOP, BOTTOM = 400, H - 380  # zone sûre entre la barre de profil et la barre de réponse


def options(d, items, y, letters=False):
    f = c.font("bold", 54)
    for k, opt in enumerate(items):
        d.rounded_rectangle([M, y, W - M, y + 140], radius=70, fill=c.CREME)
        label = f"{'ABC'[k]}.  {opt}" if letters else opt
        d.text((W / 2, y + 70), label, font=f, fill=c.VERT_FONCE, anchor="mm")
        y += 170
    return y


def story_savoir(img, s):
    d = ImageDraw.Draw(img)
    y = c.pill(d, s.get("kicker", "LE SAVIEZ-VOUS ?"), M, TOP, c.AMBRE, c.VERT_FONCE, size=40) + 50
    y = c.rich(d, s["title"], y, "black", 96, c.CREME, gap=1.08)
    if s.get("text"):
        c.rich(d, s["text"], y + 40, "medium", 50, c.CREME, gap=1.3)
    return img


def story_sondage(img, s):
    d = ImageDraw.Draw(img)
    y = c.pill(d, s.get("kicker", "SONDAGE"), M, TOP, c.AMBRE, c.VERT_FONCE, size=40) + 50
    y = c.rich(d, s["title"], y, "black", 92, c.CREME, gap=1.08) + 60
    y = options(d, s["options"][:2], y)
    d.text((W / 2, y + 30), s.get("hint", "Votez avec le sondage"), font=c.font("medium", 40), fill=c.AMBRE, anchor="mm")
    return img


def story_quiz(img, s):
    d = ImageDraw.Draw(img)
    y = c.pill(d, s.get("kicker", "QUIZ"), M, TOP, c.AMBRE, c.VERT_FONCE, size=40) + 50
    y = c.rich(d, s["title"], y, "black", 88, c.CREME, gap=1.08) + 60
    options(d, s["options"][:3], y, letters=True)
    return img


def story_question(img, s):
    d = ImageDraw.Draw(img)
    y = c.pill(d, s.get("kicker", "VOS QUESTIONS"), M, TOP, c.AMBRE, c.VERT_FONCE, size=40) + 50
    y = c.rich(d, s["title"], y, "black", 92, c.CREME, gap=1.08)
    if s.get("text"):
        y = c.rich(d, s["text"], y + 40, "medium", 50, c.CREME, gap=1.3)
    d.rounded_rectangle([M, y + 70, W - M, y + 330], radius=40, outline=c.AMBRE, width=5)  # place de l'autocollant
    return img


def story_teaser(img, s):
    d = ImageDraw.Draw(img)
    y = c.pill(d, s.get("kicker", "NOUVEAU REEL"), M, TOP, c.AMBRE, c.VERT_FONCE, size=40) + 50
    y = c.rich(d, s["title"], y, "black", 96, c.CREME, gap=1.08)
    c.pill(d, s.get("cta", "À voir sur notre profil"), 0, BOTTOM - 150, c.AMBRE, c.VERT_FONCE, size=46, center=True)
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
