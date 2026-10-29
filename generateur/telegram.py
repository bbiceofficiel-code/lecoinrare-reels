"""Envoie les publications sur Telegram pour les valider à distance, avant qu'elles partent.

Mise en place (une seule fois) :
  1. Dans Telegram, écrire à @BotFather, envoyer /newbot, choisir un nom : il donne un jeton.
  2. Coller ce jeton dans agent-cm/.telegram_token (ignoré par git : le dépôt est public).
  3. Ouvrir le nouveau bot, appuyer sur Démarrer (/start), puis : python telegram.py lier

Ensuite :
  python telegram.py envoyer --id reel-gecko --titre "Reel gecko" --quand "lun. 3 nov., 18h" \\
      --legende ..\\reels\\gecko-3-erreurs.json --metricool 123456 ..\\reels\\gecko-3-erreurs.mp4
    envoie la vidéo (ou les images), puis la légende avec les boutons Valider / Refuser.
    Pour demander une correction, on répond au message de la légende en écrivant ce qu'il faut changer.
  python telegram.py decisions [--json]
    lit les réponses reçues depuis le dernier passage et donne l'état de chaque envoi.
  python telegram.py dire "texte"  ou  dire -f message.txt     envoie un message (compte rendu, rappel, rapport)
  python telegram.py oublier <id> [--messages]   retire un envoi traité (et les messages libres lus)

Le bot ne tourne pas en permanence : un appui sur un bouton est pris en compte au passage suivant de l'agent.
Seuls les messages de la conversation reliée (« lier ») comptent ; le bot ignore tous les autres.
État local : agent-cm/.telegram_etat.json (ignoré par git).
"""
import argparse, json, mimetypes, os, re, sys, urllib.error, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETAT = os.path.join(ROOT, ".telegram_etat.json")
UA = {"User-Agent": "lecoinrare-reels/1.0 (https://github.com/bbiceofficiel-code/lecoinrare-reels)"}
STATUTS = {"attente": "⏳ en attente", "ok": "✅ validé", "non": "❌ refusé", "corriger": "✏️ à corriger"}


def token():
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip()
    path = os.path.join(ROOT, ".telegram_token")
    if not tok and os.path.exists(path):
        tok = open(path, encoding="utf-8-sig").read().strip()  # -sig : le Bloc-notes peut ajouter un BOM
    tok = "".join(tok.split())  # un collage depuis le téléphone peut couper le jeton en deux lignes
    if not tok:
        sys.exit("Pas de jeton Telegram : le coller dans agent-cm/.telegram_token (voir l'aide en haut de telegram.py).")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", tok):  # souvent un jeton recopié à la main (Ø au lieu de 0…)
        sys.exit("Le jeton dans agent-cm/.telegram_token a une forme inattendue : le copier-coller depuis le message de @BotFather.")
    return tok


def charger():
    if os.path.exists(ETAT):
        return json.load(open(ETAT, encoding="utf-8"))
    return {"chat": None, "offset": 0, "envois": {}}


def sauver(etat):
    with open(ETAT, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)


def _multipart(fields, files):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        v = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        out += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode(), v.encode(), b"\r\n"]
    for k, path in files.items():
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        out += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{os.path.basename(path)}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n".encode(), open(path, "rb").read(), b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def api(method, params=None, files=None):
    """Appel à l'API Bot de Telegram. Le jeton est dans l'URL : on ne l'affiche jamais, même en cas d'erreur."""
    if files:
        body, ctype = _multipart(params or {}, files)
    else:
        body, ctype = json.dumps(params or {}, ensure_ascii=False).encode(), "application/json"
    req = urllib.request.Request(f"https://api.telegram.org/bot{token()}/{method}", data=body, headers={**UA, "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        data = json.load(e)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram injoignable ({e.reason})") from None
    except Exception as e:  # l'erreur pourrait citer l'URL, donc le jeton : on n'en garde que le type
        raise RuntimeError(f"Telegram {method} : échec ({type(e).__name__}), vérifier le jeton dans agent-cm/.telegram_token") from None
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} : {data.get('description')}")
    return data["result"]


def boutons(id_, statut="attente"):
    if statut == "attente":
        return {"inline_keyboard": [[{"text": "✅ Valider", "callback_data": f"ok:{id_}"},
                                     {"text": "❌ Refuser", "callback_data": f"non:{id_}"}]]}
    # décision prise : un seul bouton qui la rappelle (et permet de changer d'avis)
    return {"inline_keyboard": [[{"text": STATUTS[statut], "callback_data": f"{'non' if statut == 'ok' else 'ok'}:{id_}"}]]}


# ---------------------------------------------------------------- commandes

def jeton(_args):
    """Enregistre le jeton copié dans le presse-papiers de Windows, après l'avoir essayé (getMe). Il n'est jamais affiché."""
    import subprocess
    clip = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, encoding="utf-8").stdout or ""
    found = re.search(r"\d{6,}:[A-Za-z0-9_-]{30,}", clip)
    if not found:
        sys.exit("Pas de jeton dans le presse-papiers : copier le jeton dans le message de @BotFather (/mybots > le bot > API Token), puis relancer.")
    os.environ["TELEGRAM_TOKEN"] = found.group()
    try:
        bot = api("getMe")
    except RuntimeError:
        sys.exit("Telegram refuse ce jeton : c'est sans doute un ancien jeton. Prendre celui de /mybots > le bot > API Token.")
    with open(os.path.join(ROOT, ".telegram_token"), "w", encoding="utf-8") as f:
        f.write(found.group())
    print(f"Jeton enregistré : bot @{bot['username']}.")


def lier(_args):
    etat = charger()
    starts = [u["message"] for u in api("getUpdates", {"timeout": 0})
              if u.get("message", {}).get("chat", {}).get("type") == "private"]
    if not starts:
        sys.exit("Aucun message reçu par le bot : lui écrire /start (ou n'importe quoi) dans Telegram, puis relancer.")
    chat = starts[-1]["chat"]
    etat["chat"] = chat["id"]
    sauver(etat)
    api("sendMessage", {"chat_id": chat["id"], "text": "C'est relié 🦎 Je t'enverrai ici chaque publication de LeCoinRare avant qu'elle parte. "
                                                       "Valider, Refuser, ou réponds à la légende pour demander une correction."})
    print(f"Relié à la conversation de {chat.get('first_name', '')} {chat.get('last_name', '')}".strip() + ".")


def legende(valeur):
    if not valeur:
        return ""
    if os.path.exists(valeur):
        if valeur.lower().endswith(".json"):
            return json.load(open(valeur, encoding="utf-8")).get("caption", "")
        return open(valeur, encoding="utf-8").read()
    return valeur


def envoyer(args):
    etat = charger()
    chat = etat.get("chat")
    if not chat:
        sys.exit("Telegram pas encore relié : python telegram.py lier")
    ancien = etat["envois"].get(args.id)
    if ancien:  # nouvelle version : on retire les boutons de l'ancienne pour qu'elle ne puisse plus être validée
        try:
            api("editMessageReplyMarkup", {"chat_id": chat, "message_id": ancien["message_id"], "reply_markup": {"inline_keyboard": []}})
            api("sendMessage", {"chat_id": chat, "text": "♻️ Version remplacée : la nouvelle arrive juste en dessous.",
                                "reply_parameters": {"message_id": ancien["message_id"]}})
        except RuntimeError:
            pass
    videos = [f for f in args.fichiers if f.lower().endswith((".mp4", ".mov"))]
    images = [f for f in args.fichiers if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    for v in videos:
        api("sendVideo", {"chat_id": str(chat), "width": "1080", "height": "1920", "supports_streaming": "true"}, {"video": v})
    for k in range(0, len(images), 10):  # un album Telegram contient 10 images au plus
        lot = images[k:k + 10]
        if len(lot) == 1:
            api("sendPhoto", {"chat_id": str(chat)}, {"photo": lot[0]})
        else:
            media = [{"type": "photo", "media": f"attach://f{i}"} for i in range(len(lot))]
            api("sendMediaGroup", {"chat_id": str(chat), "media": media}, {f"f{i}": p for i, p in enumerate(lot)})
    entete = f"📋 {args.titre}" + (f"\n🗓 {args.quand}" if args.quand else "")
    texte = (entete + "\n\n" + legende(args.legende)).strip()
    if len(texte) > 4000:
        texte = texte[:3990] + "…"
    msg = api("sendMessage", {"chat_id": chat, "text": texte, "reply_markup": boutons(args.id)})
    etat["envois"][args.id] = {"titre": args.titre, "quand": args.quand, "metricool": args.metricool, "statut": "attente",
                               "message_id": msg["message_id"], "corrections": []}
    sauver(etat)
    print(f"Envoyé sur Telegram : {args.titre} ({len(videos)} vidéo(s), {len(images)} image(s)).")


def decisions(args):
    etat = charger()
    chat = etat.get("chat")
    if not chat:
        sys.exit("Telegram pas encore relié : python telegram.py lier")
    par_message = {e["message_id"]: i for i, e in etat["envois"].items()}
    for u in api("getUpdates", {"offset": etat["offset"], "timeout": 0, "allowed_updates": ["message", "callback_query"]}):
        etat["offset"] = u["update_id"] + 1
        if "callback_query" in u:
            q = u["callback_query"]
            if q.get("message", {}).get("chat", {}).get("id") != chat or ":" not in q.get("data", ""):
                continue
            choix, id_ = q["data"].split(":", 1)
            if id_ in etat["envois"]:
                etat["envois"][id_]["statut"] = choix
                try:  # l'appui peut dater de plusieurs heures : Telegram refuse alors l'accusé, sans gravité
                    api("answerCallbackQuery", {"callback_query_id": q["id"], "text": STATUTS[choix]})
                except RuntimeError:
                    pass
                try:  # « message is not modified » si on appuie deux fois sur le même bouton
                    api("editMessageReplyMarkup", {"chat_id": chat, "message_id": q["message"]["message_id"], "reply_markup": boutons(id_, choix)})
                except RuntimeError:
                    pass
        elif "message" in u:
            m = u["message"]
            if m.get("chat", {}).get("id") != chat or not m.get("text"):
                continue
            id_ = par_message.get(m.get("reply_to_message", {}).get("message_id"))
            if id_:
                etat["envois"][id_]["statut"] = "corriger"
                etat["envois"][id_]["corrections"].append(m["text"])
                api("sendMessage", {"chat_id": chat, "text": "Bien noté ✏️ Je corrige et je te renvoie la nouvelle version.",
                                    "reply_parameters": {"message_id": m["message_id"]}})
            elif not m["text"].startswith("/"):
                etat.setdefault("messages", []).append(m["text"])
    sauver(etat)
    if args.json:
        print(json.dumps({"envois": etat["envois"], "messages": etat.get("messages", [])}, ensure_ascii=False, indent=1))
        return
    for id_, e in etat["envois"].items():
        ligne = f"{STATUTS[e['statut']]:16} {id_} : {e['titre']}" + (f" ({e['quand']})" if e.get("quand") else "")
        if e.get("metricool"):
            ligne += f" [Metricool {e['metricool']}]"
        print(ligne)
        for c in e["corrections"]:
            print(f"{'':18}correction : {c}")
    for t in etat.get("messages", []):
        print(f"Message libre : {t}")


def dire(args):
    """Envoie un simple message dans la conversation reliée (compte rendu de l'agent, rappel)."""
    chat = charger().get("chat")
    if not chat:
        sys.exit("Telegram pas encore relié : python telegram.py lier")
    texte = open(args.fichier, encoding="utf-8-sig").read() if args.fichier else " ".join(args.texte)
    if not texte.strip():
        sys.exit("Message vide.")
    api("sendMessage", {"chat_id": chat, "text": texte[:4000]})


def son(args):
    """Envoie des fichiers audio à écouter (essais de voix, musiques), sans boutons de validation."""
    chat = charger().get("chat")
    if not chat:
        sys.exit("Telegram pas encore relié : python telegram.py lier")
    if args.texte:
        api("sendMessage", {"chat_id": chat, "text": args.texte[:4000]})
    for f in args.fichiers:
        titre = os.path.splitext(os.path.basename(f))[0]
        api("sendAudio", {"chat_id": str(chat), "title": titre, "performer": "LeCoinRare"}, {"audio": f})


def oublier(args):
    """Retire de l'état les envois traités (publiés ou abandonnés), pour garder la liste courte."""
    etat = charger()
    for id_ in args.ids:
        etat["envois"].pop(id_, None)
    if args.messages:
        etat["messages"] = []
    sauver(etat)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Validation des publications LeCoinRare sur Telegram.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("jeton", help="enregistre le jeton copié dans le presse-papiers").set_defaults(f=jeton)
    sub.add_parser("lier").set_defaults(f=lier)
    e = sub.add_parser("envoyer")
    e.add_argument("--id", required=True, help="identifiant court, ex. reel-gecko-3-erreurs")
    e.add_argument("--titre", required=True)
    e.add_argument("--quand", default="", help="date prévue, ex. « lun. 3 nov., 18h »")
    e.add_argument("--legende", default="", help="texte, fichier .txt, ou JSON du Reel/carrousel (champ caption)")
    e.add_argument("--metricool", default="", help="id du brouillon Metricool à programmer une fois validé")
    e.add_argument("fichiers", nargs="*")
    e.set_defaults(f=envoyer)
    d = sub.add_parser("decisions")
    d.add_argument("--json", action="store_true")
    d.set_defaults(f=decisions)
    m = sub.add_parser("dire")
    m.add_argument("texte", nargs="*")
    m.add_argument("-f", "--fichier", help="texte du message dans un fichier UTF-8 (pratique pour plusieurs lignes)")
    m.set_defaults(f=dire)
    a = sub.add_parser("son", help="envoie des fichiers audio à écouter (essais de voix)")
    a.add_argument("fichiers", nargs="+")
    a.add_argument("-t", "--texte", default="", help="message envoyé avant les fichiers")
    a.set_defaults(f=son)
    o = sub.add_parser("oublier")
    o.add_argument("ids", nargs="*")
    o.add_argument("--messages", action="store_true", help="vider aussi les messages libres déjà lus")
    o.set_defaults(f=oublier)
    args = p.parse_args()
    try:
        args.f(args)
    except RuntimeError as err:
        sys.exit(str(err))
