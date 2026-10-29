"""Reel « dynamique » LeCoinRare : montage rapide de vraies vidéos, voix off, sous-titres mot à mot, musique.

Usage : python reel_dynamique.py spec.json sortie.mp4 [--apercu] [--planches dossier]

Le format qui retient l'attention : un plan nouveau toutes les 1,5 à 2 s, des sous-titres qui s'affichent au rythme
de la voix (le mot prononcé en couleur), une musique rythmée qui s'efface sous la voix, un « whoosh » à chaque
nouvelle phrase, une accroche en gros dès la première image, 20 à 30 s en tout.

JSON :
  "voix": "estelle", "vitesse": 1.1 (voix accélérée sans changer sa hauteur),
  "musique": "musique/<fichier>.mp3" (relatif à generateur/), "musique_debut": s, "musique_volume": 0.5,
  "accroche": "Texte de l'accroche avec *mots* surlignés" (en gros pendant la 1re phrase),
  "phrases": [{"texte": "Ce que dit la voix, affiché mot à mot", "plans": [{"pixabay": 233037, "debut": 3.5, "x": 0.4}]}],
  "fin": {"texte": "Abonnez-vous pour le prochain secret", "plans": [...]} (dernière phrase, sur le logo),
  "cover_ms", "caption", "sources".
Chaque plan : "pixabay" (id de la vidéo, téléchargée en 4K) ou "fichier" (chemin relatif au JSON), "debut" (s dans la
vidéo), "x" (0 à 1 : où se trouve l'animal dans l'image paysage, pour le recadrage vertical), "zoom" ("in" par défaut,
"out"). La durée de chaque phrase vient de la voix, partagée entre ses plans.
--planches dossier : télécharge les vidéos et écrit, pour chacune, une planche d'images toutes les 2 s avec le cadre
vertical, pour choisir "debut" et "x".
"""
import json, os, re, subprocess, sys, tempfile, wave

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import charte as c
import medias as banques
from reel import diction, encodeur, parse_words, synth_naturelle

W, H, FPS, SR = 1080, 1920, 30, 44100
OVER = 1.12          # les images sont décodées 12 % plus grandes : place pour les zooms
GAP = 0.12           # silence entre deux phrases
CAP_Y = 1180         # centre des sous-titres (au-dessus de la zone des boutons Instagram)
AUTEURS_IA = {"Solarselle77"}  # comptes Pixabay qui ne publient que des vidéos générées par IA


# ---------------------------------------------------------------- vidéos

def pixabay_clip(vid):
    """Télécharge la vidéo Pixabay `vid` dans sa meilleure définition (cache reels/media/)."""
    path = os.path.join(banques.CACHE, f"pixabay-{vid}.mp4")
    if os.path.exists(path):
        return path
    os.makedirs(banques.CACHE, exist_ok=True)
    hit = banques._json(f"https://pixabay.com/api/videos/?key={banques.api_key('pixabay')}&id={vid}")["hits"][0]
    if hit["user"] in AUTEURS_IA or any(m in hit["tags"].lower() for m in ("ai generated", "photorealistic", "generative")):
        raise ValueError(f"pixabay {vid} : vidéo générée par IA ({hit['user']}), on veut de vrais animaux")
    best = max((f for f in hit["videos"].values() if f.get("url")), key=lambda f: f.get("width") or 0)
    banques._download(best["url"], path)
    with open(path + ".json", "w", encoding="utf-8") as f:
        json.dump({"credit": f'Vidéo : {hit["user"]} sur Pixabay', "page": hit["pageURL"]}, f, ensure_ascii=False)
    return path


def photo_path(ref):
    """Photo "pixabay:<id>" (1280 px au plus) ou "wikimedia:<pageid>" (CC0 ou domaine public, 2160 px) : cache reels/media/."""
    src, pid = ref.split(":")
    path = os.path.join(banques.CACHE, f"{src}-photo-{pid}.jpg")
    if os.path.exists(path):
        return path
    os.makedirs(banques.CACHE, exist_ok=True)
    if src == "pixabay":
        hit = banques._json(f"https://pixabay.com/api/?key={banques.api_key('pixabay')}&id={pid}")["hits"][0]
        url, cred = hit["largeImageURL"], f'Photo : {hit["user"]} sur Pixabay'
    else:
        q = banques._json("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata"
                          f"&iiextmetadatafilter=LicenseShortName|Artist&iiurlwidth=2160&pageids={pid}")
        ii = q["query"]["pages"][pid]["imageinfo"][0]
        lic = ii["extmetadata"]["LicenseShortName"]["value"]
        if not lic.lower().startswith(banques.FREE_LICENSES):
            raise ValueError(f"wikimedia:{pid} : licence {lic}, seulement CC0 ou domaine public")
        artist = re.sub(r"<[^>]+>", "", ii["extmetadata"].get("Artist", {}).get("value", "")).strip()
        url, cred = ii.get("thumburl") or ii["url"], f"Photo : {artist}, {lic}, Wikimedia Commons"
    banques._download(url, path)
    with open(path + ".json", "w", encoding="utf-8") as f:
        json.dump({"credit": cred}, f, ensure_ascii=False)
    return path


def clip_path(plan, base):
    if "photo" in plan:
        return photo_path(plan["photo"])
    return pixabay_clip(plan["pixabay"]) if "pixabay" in plan else os.path.join(base, plan["fichier"])


def photo_frames(path, dur, x, y):
    """Photo en plein écran si elle est assez grande, sinon encadrée (bords arrondis) sur un fond flou de la même photo.
    Le mouvement vient du zoom du montage."""
    from PIL import ImageFilter
    ow, oh = int(W * OVER) // 2 * 2, int(H * OVER) // 2 * 2
    img = Image.open(path).convert("RGB")
    s = max(ow / img.width, oh / img.height)
    big = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
    x0 = int((big.width - ow) * min(1, max(0, x)))
    y0 = int((big.height - oh) * min(1, max(0, y)))
    fond = big.crop((x0, y0, x0 + ow, y0 + oh))
    if min(img.width, img.height * 9 / 16) < 900:  # trop petite pour le plein écran : on l'encadre
        fond = fond.resize((ow // 8, oh // 8)).filter(ImageFilter.GaussianBlur(6)).resize((ow, oh), Image.BILINEAR)
        fond = Image.blend(fond, Image.new("RGB", (ow, oh), c.FOND), 0.45)
        k = min((ow - 80) / img.width, (oh * 0.62) / img.height)
        av = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
        masque = Image.new("L", av.size, 0)
        ImageDraw.Draw(masque).rounded_rectangle([0, 0, av.width - 1, av.height - 1], 36, fill=255)
        ombre = Image.new("L", (ow, oh), 0)
        px, py = (ow - av.width) // 2, int(oh * 0.47 - av.height / 2)
        ImageDraw.Draw(ombre).rounded_rectangle([px - 6, py + 14, px + av.width + 6, py + av.height + 26], 40, fill=150)
        fond.paste(Image.new("RGB", (ow, oh), (0, 0, 0)), (0, 0), ombre.filter(ImageFilter.GaussianBlur(18)))
        fond.paste(av, (px, py), masque)
    arr = np.asarray(fond)
    for _ in range(int(round(dur * FPS))):
        yield arr


def credit(path):
    meta = path + ".json"
    return json.load(open(meta, encoding="utf-8"))["credit"] if os.path.exists(meta) else os.path.basename(path)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                          "-of", "json", path], capture_output=True, text=True).stdout
    j = json.loads(out)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


def frames(path, start, dur, x, y=0.5):
    """Images du plan, recadrées en vertical autour de x et agrandies de OVER : générateur de tableaux numpy."""
    if path.lower().endswith((".jpg", ".jpeg", ".png")):
        yield from photo_frames(path, dur, x, y)
        return
    w, h, _ = probe(path)
    cw = min(w, int(h * 9 / 16)) // 2 * 2
    cx = int(max(0, min(w - cw, x * w - cw / 2)))
    ow, oh = int(W * OVER) // 2 * 2, int(H * OVER) // 2 * 2
    vf = f"crop={cw}:{min(h, int(cw * 16 / 9)) // 2 * 2}:{cx}:0,scale={ow}:{oh}:flags=lanczos,fps={FPS},eq=contrast=1.06:saturation=1.12"
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", path, "-t", f"{dur + 0.2:.2f}",
                          "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    last = None
    try:
        for _ in range(int(round(dur * FPS))):
            raw = p.stdout.read(ow * oh * 3)
            if len(raw) == ow * oh * 3:
                last = np.frombuffer(raw, np.uint8).reshape(oh, ow, 3)
            yield last
    finally:
        p.kill()


def zoom(arr, z):
    """z de 0 (image entière, OVER fois trop grande) à 1 (zoom maximal) -> image 1080x1920."""
    oh, ow = arr.shape[:2]
    cw = ow / OVER * (1 + (OVER - 1) * (1 - z))
    ch = oh / OVER * (1 + (OVER - 1) * (1 - z))
    cw, ch = min(ow, cw), min(oh, ch)
    x0, y0 = (ow - cw) / 2, (oh - ch) / 2
    img = Image.fromarray(arr)
    return img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


# ---------------------------------------------------------------- voix

def voix_phrases(spec):
    """Synthétise chaque phrase, accélérée de "vitesse" sans changer la hauteur. Renvoie [(échantillons 44,1 kHz)]."""
    textes = [p["texte"] for p in spec["phrases"]] + ([spec["fin"]["texte"]] if spec.get("fin") else [])
    brut = synth_naturelle(spec.get("voix", "estelle"), [diction(t.replace("*", "")) for t in textes])
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (sr, data) in enumerate(brut):
            src, dst = os.path.join(tmp, f"{i}.wav"), os.path.join(tmp, f"{i}-v.wav")
            with wave.open(src, "wb") as wf:
                wf.setnchannels(1), wf.setsampwidth(2), wf.setframerate(sr)
                wf.writeframes((np.clip(data, -1, 1) * 32767).astype(np.int16).tobytes())
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", f"atempo={spec.get('vitesse', 1.1)}",
                            "-ar", str(SR), "-ac", "1", dst], check=True)
            with wave.open(dst) as wf:
                out.append(np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768)
    return out


def temps_mots(texte, debut, duree):
    """Instant de début de chaque mot affiché : proportionnel à sa longueur, avec une respiration après la ponctuation."""
    mots = []
    for m, hl in parse_words(texte):  # « saviez ? » : le point d'interrogation reste avec son mot
        if mots and re.fullmatch(r"[?!:;»…]+", m):
            mots[-1] = (mots[-1][0] + " " + m, mots[-1][1])  # (Montserrat n'a pas l'espace fine insécable)
        else:
            mots.append((m, hl))
    poids = [len(m) + 2 + (4 if re.search(r"[.,;:!?…]$", m) else 0) for m, _ in mots]
    total, acc, out = sum(poids), 0, []
    for (m, hl), p in zip(mots, poids):
        out.append((m, hl, debut + duree * acc / total, debut + duree * (acc + p) / total))
        acc += p
    return out


def groupes(mots, maxi=3, chars=17):
    """Sous-titres par petits groupes (3 mots au plus), coupés après la ponctuation."""
    out, cur = [], []
    for m in mots:
        if cur and (len(cur) >= maxi or sum(len(x[0]) + 1 for x in cur) + len(m[0]) > chars):
            out.append(cur)
            cur = []
        cur.append(m)
        if re.search(r"[.,;:!?…]$", m[0]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- son

def charger_musique(path, debut, duree):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(debut), "-i", path, "-t", str(duree + 1), "-f", "f32le",
                          "-ac", "2", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    m = np.frombuffer(raw, np.float32).reshape(-1, 2)
    out = np.zeros((int(duree * SR), 2), np.float32)
    out[:min(len(m), len(out))] = m[:len(out)]
    return out


def whoosh(n=int(0.32 * SR), seed=0):
    """Souffle filtré qui monte puis retombe (bruit blanc, filtre passe-bas dont la fréquence balaie)."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, n).astype(np.float32)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t ** 0.7) ** 2
    cut = 300 + 5000 * np.sin(np.pi * t) ** 2
    a = 1 - np.exp(-2 * np.pi * cut / SR)
    y, out = 0.0, np.empty(n, np.float32)
    for i in range(n):
        y += a[i] * (noise[i] - y)
        out[i] = y
    return out * env / (np.abs(out * env).max() or 1)


def mixer(voix, debuts, total, spec, coupes):
    track = np.zeros(int(total * SR) + SR, np.float32)
    for v, t in zip(voix, debuts):
        i = int(t * SR)
        track[i:i + len(v)] += v
    track /= np.abs(track).max() or 1
    env = np.convolve(np.abs(track), np.ones(int(0.25 * SR)) / int(0.25 * SR), "same")
    env = np.clip(env / (env.max() or 1) * 3, 0, 1)
    mix = np.repeat(track[:, None] * 0.9, 2, axis=1)
    if spec.get("musique"):
        mus = charger_musique(os.path.join(HERE, spec["musique"]), spec.get("musique_debut", 0), total + 1)
        mus = mus[:len(mix)] if len(mus) >= len(mix) else np.pad(mus, ((0, len(mix) - len(mus)), (0, 0)))
        vol = spec.get("musique_volume", 0.5)
        gain = vol * (1 - 0.72 * env)  # la musique s'efface sous la voix
        fade = np.clip((total - np.arange(len(mix)) / SR) / 1.2, 0, 1)  # fondu de fin
        fade *= np.clip(np.arange(len(mix)) / SR / 0.05, 0, 1)
        mix += mus / (np.abs(mus).max() or 1) * (gain * fade)[:, None]
    w = whoosh()
    for k, t in enumerate(coupes):
        i = max(0, int((t - 0.2) * SR))
        n = min(len(w), len(mix) - i)
        mix[i:i + n] += (w[:n] * 0.16)[:, None]
    mix = mix[:int(total * SR)]
    return np.clip(mix / (np.abs(mix).max() or 1) * 0.95, -1, 1)


# ---------------------------------------------------------------- dessin

VIGNETTE = None


def vignette():
    global VIGNETTE
    if VIGNETTE is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.7)) ** 2)
        haut = np.clip((380 - yy) / 380, 0, 1) ** 1.5 * 0.55       # logo lisible
        bas = np.clip((yy - 1350) / 570, 0, 1) ** 1.3 * 0.6          # zone des boutons Instagram
        k = np.clip(1 - 0.35 * np.clip(r - 0.55, 0, 1) - haut - bas, 0, 1)
        VIGNETTE = Image.fromarray((k * 255).astype(np.uint8), "L")
    return VIGNETTE


def texte_contour(d, xy, mot, f, couleur, anchor="mm"):
    d.text(xy, mot, font=f, fill=couleur, anchor=anchor, stroke_width=max(4, f.size // 11), stroke_fill=(0, 0, 0))


def sous_titres(img, mots_t, t):
    """Groupe de mots en cours, le mot prononcé en or, petit effet « pop » à l'apparition du groupe."""
    for g in groupes(mots_t):
        if g[0][2] - 0.02 <= t < (g[-1][3] + 0.05):
            break
    else:
        return
    age = t - g[0][2]
    scale = 0.86 + 0.14 * min(1, age / 0.1) + 0.04 * max(0, 1 - abs(age - 0.1) / 0.1)
    f = c.font("black", int(96 * scale))
    esp = f.getlength(" ")
    larg = sum(f.getlength(m.upper()) for m, *_ in g) + esp * (len(g) - 1)
    if larg > W - 120:  # groupe trop large : on réduit
        f = c.font("black", int(96 * scale * (W - 120) / larg))
        esp = f.getlength(" ")
        larg = sum(f.getlength(m.upper()) for m, *_ in g) + esp * (len(g) - 1)
    d = ImageDraw.Draw(img)
    x = (W - larg) / 2
    for m, hl, t0, t1 in g:
        actif = t0 <= t < t1 + 0.04
        couleur = c.OR if actif else (c.VERT_VIF if hl else c.BLANC)
        texte_contour(d, (x, CAP_Y), m.upper(), f, couleur, anchor="lm")
        x += f.getlength(m.upper()) + esp


def accroche(img, texte, t, duree):
    """L'accroche en gros, en haut, mot après mot, pendant la première phrase."""
    if t >= duree:
        return
    f = c.font("black", 104)
    mots = parse_words(texte)
    lignes, cur, lw = [], [], 0
    for m, hl in mots:
        w = f.getlength(m.upper())
        if cur and lw + f.getlength(" ") + w > W - 140:
            lignes.append(cur)
            cur, lw = [], 0
        lw += (f.getlength(" ") if cur else 0) + w
        cur.append((m, hl))
    lignes.append(cur)
    d = ImageDraw.Draw(img)
    y, k, sortie = 470 - (len(lignes) - 1) * 62, 0, max(0, 1 - (duree - t) / 0.15)
    for ligne in lignes:
        lw = sum(f.getlength(m.upper()) for m, _ in ligne) + f.getlength(" ") * (len(ligne) - 1)
        x = (W - lw) / 2
        for m, hl in ligne:
            apparu = t - k * 0.07
            if apparu > 0:
                dy = int(40 * (1 - min(1, apparu / 0.12)) ** 2) - int(30 * sortie)
                if hl:
                    w = f.getlength(m.upper())
                    d.rounded_rectangle([x - 12, y - 66 + dy, x + w + 12, y + 62 + dy], 14, fill=c.OR)
                    d.text((x, y + dy), m.upper(), font=f, fill=c.FOND, anchor="lm")
                else:
                    texte_contour(d, (x, y + dy), m.upper(), f, c.BLANC, anchor="lm")
            x += f.getlength(m.upper()) + f.getlength(" ")
            k += 1
        y += 124


def carte_fin(img, t, debut, duree):
    """Dernière phrase : fond sombre de la marque qui monte, logo, appel à s'abonner."""
    p = min(1, (t - debut) / 0.35)
    if p <= 0:
        return img
    voile = Image.new("RGB", (W, H), c.FOND)
    img = Image.blend(img, voile, 0.82 * p)
    d = ImageDraw.Draw(img)
    lg = c.logo(260)
    img.paste(lg, (W // 2 - 130, 640 - int(40 * (1 - p))), lg)
    c.marque(img, W // 2, 980, size=64, center=True)
    d.text((W // 2, 1080), "lecoinrare.com", font=c.font("semibold", 40), fill=c.GRIS, anchor="mm")
    return img


def carte_chiffre(img, texte, age):
    """Grosse pastille dorée (un chiffre clé : « 26 °C = FEMELLES ») qui surgit en haut de l'image."""
    p = min(1, age / 0.18)
    scale = 0.6 + 0.4 * p + 0.08 * max(0, 1 - abs(age - 0.18) / 0.12)
    f = c.font("black", int(84 * scale))
    tw = f.getlength(texte.upper())
    if tw > W - 160:
        f = c.font("black", int(84 * scale * (W - 160) / tw))
        tw = f.getlength(texte.upper())
    d = ImageDraw.Draw(img)
    cy = 560
    d.rounded_rectangle([W / 2 - tw / 2 - 34, cy - 70, W / 2 + tw / 2 + 34, cy + 70], 28, fill=c.OR)
    d.text((W / 2, cy), texte.upper(), font=f, fill=c.FOND, anchor="mm")


def composer(base, t, mots_t, spec, d_accroche, fin_debut, flash, cartes=()):
    img = Image.composite(base, Image.new("RGB", (W, H), (0, 0, 0)), vignette())
    for t0, t1, texte in cartes:
        if t0 <= t < t1:
            carte_chiffre(img, texte, t - t0)
    if fin_debut is not None and t >= fin_debut:
        img = carte_fin(img, t, fin_debut, 0)
    if flash > 0:
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 255, 255)), flash)
    if spec.get("accroche") and t < d_accroche:
        accroche(img, spec["accroche"], t, d_accroche)
    else:
        sous_titres(img, mots_t, t)
    if fin_debut is None or t < fin_debut:
        marque_lisible(img)
    return img


def marque_lisible(img, x=64, y=150, size=36):
    """Logo sur une pastille sombre arrondie : « Rare » (vert) reste lisible sur un fond clair."""
    w = int(c.largeur_marque(size)) + 44
    box = (x - 22, y - 38, x - 22 + w, y + 38)
    zone = img.crop(box)
    sombre = Image.blend(zone, Image.new("RGB", zone.size, c.FOND), 0.62)
    masque = Image.new("L", zone.size, 0)
    ImageDraw.Draw(masque).rounded_rectangle([0, 0, zone.width - 1, zone.height - 1], 38, fill=255)
    img.paste(sombre, box[:2], masque)
    c.marque(img, x, y, size=size)


# ---------------------------------------------------------------- montage

def planches(spec, base, dossier):
    os.makedirs(dossier, exist_ok=True)
    ids = []
    for p in spec["phrases"] + ([spec["fin"]] if spec.get("fin") else []):
        for pl in p["plans"]:
            if "pixabay" in pl and pl["pixabay"] not in ids:
                ids.append(pl.get("pixabay"))
    for vid in ids:
        path = pixabay_clip(vid)
        w, h, dur = probe(path)
        ts = np.arange(0.5, dur - 0.3, 2.0)
        tiles = []
        for t in ts:
            raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                                  "-vf", "scale=480:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            th = len(raw) // (480 * 3)
            if not th:
                continue
            im = Image.fromarray(np.frombuffer(raw, np.uint8)[:480 * th * 3].reshape(th, 480, 3))
            d = ImageDraw.Draw(im)
            for k in range(1, 10):  # graduations x = 0.1 ... 0.9
                d.line([(48 * k, th - 14), (48 * k, th)], fill=(255, 255, 0), width=2)
            d.text((6, 4), f"{t:.1f}s", fill=(255, 255, 0), font=c.font("bold", 22))
            tiles.append(im)
        cols = 4
        th = tiles[0].height
        sheet = Image.new("RGB", (cols * 484, ((len(tiles) + cols - 1) // cols) * (th + 4)), (30, 30, 30))
        for k, im in enumerate(tiles):
            sheet.paste(im, ((k % cols) * 484, (k // cols) * (th + 4)))
        sheet.save(os.path.join(dossier, f"pixabay-{vid}.jpg"), quality=80)
        print(f"pixabay-{vid} : {w}x{h}, {dur:.1f} s")


def main(spec_path, out_path, apercu=False):
    import time
    t0 = time.time()
    spec = json.load(open(spec_path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(spec_path))
    phrases = spec["phrases"] + ([spec["fin"]] if spec.get("fin") else [])
    voix = voix_phrases(spec)
    t_voix = time.time()

    # chronologie : chaque phrase dure le temps de sa voix (+ un souffle), partagé entre ses plans
    debuts, mots_t, plans, coupes, cartes = [], [], [], [], []
    t, seg = 0.15, 0.0  # la voix démarre à 0,15 s ; seg = début visuel de la phrase
    for p, v in zip(phrases, voix):
        d = len(v) / SR
        debuts.append(t)
        mots_t += temps_mots(p["texte"], t + 0.03, d - 0.08)
        fin = t + d + GAP + (0.9 if p is spec.get("fin") else 0)
        if p.get("carte"):  # chiffre clé en gros pendant la phrase
            cartes.append((t + 0.1, fin, p["carte"]))
        n = len(p["plans"])
        for k, pl in enumerate(p["plans"]):
            plans.append((pl, seg + k * (fin - seg) / n, (fin - seg) / n))
        coupes.append(seg)
        seg = t = fin
    total = seg
    d_accroche = debuts[1] if len(debuts) > 1 else total
    fin_debut = debuts[-1] if spec.get("fin") else None
    print(f"Durée : {total:.1f} s, {len(plans)} plans, {len(phrases)} phrases")

    stem = os.path.splitext(out_path)[0]
    if apercu:
        for i, (pl, start, dur) in enumerate(plans):
            arr = next(frames(clip_path(pl, base), pl.get("debut", 0) + dur * 0.6, 0.1, pl.get("x", 0.5), pl.get("y", 0.5)))
            tt = start + dur * 0.6
            composer(zoom(arr, 0.5), tt, mots_t, spec, d_accroche, fin_debut, 0, cartes).save(f"{stem}-apercu-{i + 1:02d}.png")
        print(f"Aperçus : {stem}-apercu-*.png")
        return

    son = mixer(voix, debuts, total, spec, coupes[1:])
    wav = stem + "-son.wav"
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(2), wf.setsampwidth(2), wf.setframerate(SR)
        wf.writeframes((son * 32767).astype(np.int16).tobytes())
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, *encodeur(), "-pix_fmt", "yuv420p",
                             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
                             "-t", f"{total:.3f}", "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)
    credits, n_img = [], 0
    try:
        for i, (pl, start, dur) in enumerate(plans):
            path = clip_path(pl, base)
            if credit(path) not in credits:
                credits.append(credit(path))
            n = int(round((start + dur) * FPS)) - n_img
            for k, arr in enumerate(frames(path, pl.get("debut", 0), n / FPS + 0.05, pl.get("x", 0.5), pl.get("y", 0.5))):
                if k >= n:
                    break
                tt = n_img / FPS
                u = k / max(1, n - 1)
                punch = max(0, 1 - k / 6)  # petit coup de zoom à chaque coupe
                z = (0.15 + 0.6 * u if pl.get("zoom", "in") == "in" else 0.75 - 0.6 * u) + 0.25 * punch
                flash = 0.35 * max(0, 1 - k / 3) if (i and any(abs(start - cp) < 0.05 for cp in coupes)) else 0
                img = composer(zoom(arr, min(1, z)), tt, mots_t, spec, d_accroche, fin_debut, flash, cartes)
                proc.stdin.write(img.tobytes())
                n_img += 1
        proc.stdin.close()
        if proc.wait():
            raise RuntimeError("ffmpeg a échoué pendant l'encodage")
    finally:
        os.remove(wav)
    cover = min(spec.get("cover_ms", 500) / 1000, total - 0.1)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(cover), "-i", out_path, "-frames:v", "1", "-q:v", "3",
                    stem + ".jpg"], check=True)
    print(f"Reel prêt : {out_path} ({total:.1f} s, {os.path.getsize(out_path) / 1e6:.0f} Mo) — voix {t_voix - t0:.0f} s, "
          f"montage {time.time() - t_voix:.0f} s")
    print("Crédits : " + " ; ".join(credits))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--planches" in sys.argv:
        planches(json.load(open(args[0], encoding="utf-8")), os.path.dirname(os.path.abspath(args[0])),
                 sys.argv[sys.argv.index("--planches") + 1])
    else:
        main(args[0], args[1], apercu="--apercu" in sys.argv)
