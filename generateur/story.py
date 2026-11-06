"""Génère les stories Instagram/Facebook (1080x1920, JPG) au design system « Canopée » de LeCoinRare.

Usage : python3 story.py stories.json dossier_sortie

Types : savoir (« Le saviez-vous ? », ou « La réponse » d'un quiz avec "kicker"), sondage (2 à 4 options), quiz (3 options),
question, teaser (annonce d'un Reel, avec sa couverture en "media").
Les zones du haut (profil) et du bas (barre de réponse) d'Instagram restent libres.
TOUT SE PUBLIE SEUL (demande de l'utilisateur, 01/11/2026 : « je compte rien faire à la main ») : l'API ne pose pas les
autocollants interactifs (sondage, quiz, question, lien), donc on n'en utilise aucun. Les options portent une lettre
et l'abonné répond avec la barre « Répondre » de la story (sa réponse arrive en message). La bonne réponse d'un quiz
est donnée par une deuxième story programmée le soir même. Toutes les stories partent en publication automatique.
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


def options(img, items, y, letters=False, h=140, pas=170):
    """Options en boutons « secondaires » du site : carte, bordure verte à 30 %, lettre en vert vif."""
    d = ImageDraw.Draw(img, "RGBA")
    place = W - 2 * M - (112 + 40 if letters else 80)  # largeur utile dans le bouton
    taille = 52
    while taille > 34 and max(charte.font("bold", taille).getlength(o) for o in items) > place:
        taille -= 2  # une option longue rétrécit plutôt que de déborder
    f = charte.font("bold", taille)
    for k, opt in enumerate(items):
        d.rounded_rectangle([M, y, W - M, y + h], radius=36, fill=charte.a(charte.CARTE, 0.94),
                            outline=charte.a(charte.VERT, 0.6), width=3)
        if letters:
            d.text((M + 56, y + h / 2), "ABCD"[k], font=charte.font("black", 56), fill=charte.VERT_VIF, anchor="mm")
            d.text((M + 112, y + h / 2), opt, font=f, fill=charte.BLANC, anchor="lm")
        else:
            d.text((W / 2, y + h / 2), opt, font=f, fill=charte.BLANC, anchor="mm")
        y += pas
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


def consigne(img, s, y, n):
    """Comment répondre sans autocollant : par la barre « Répondre » de la story."""
    lettres = ", ".join("ABCD"[:n - 1]) + " ou " + "ABCD"[n - 1]
    texte = s.get("hint", f"Répondez *{lettres}* à cette story")
    y = c.rich(img, texte, y + 20, "semibold", 44, charte.BLANC, align="center", gap=1.3)
    if s.get("hint2"):
        y = c.rich(img, s["hint2"], y + 4, "medium", 38, charte.GRIS, align="center", gap=1.3)
    return y


def story_sondage(img, s):
    if len(s["options"]) > 2:  # 3 options ou plus : mise en page compacte du quiz, sinon la consigne touche le logo
        y = titre(img, s, "SONDAGE", 80) + 44
        y = options(img, s["options"][:4], y, letters=True, h=118, pas=142)
    else:
        y = titre(img, s, "SONDAGE", 92) + 60
        y = options(img, s["options"][:4], y, letters=True)
    consigne(img, s, y, len(s["options"][:4]))
    return img


def story_quiz(img, s):
    y = titre(img, s, "QUIZ", 80) + 44  # plus compact : 3 réponses et la consigne tiennent au-dessus du logo
    y = options(img, s["options"][:3], y, letters=True, h=118, pas=142)
    consigne(img, s, y, len(s["options"][:3]))
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
