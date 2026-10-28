"""Trouve et télécharge des photos ou vidéos libres de droits pour les Reels et les carrousels.

Sources essayées dans l'ordre :
  1. Pexels   — gratuit, clé API requise, souvent en 4K ;
  2. Pixabay  — gratuit, clé API requise, beaucoup de vidéos 4K ;
  3. Wikimedia Commons — sans clé ; seulement les fichiers CC0 ou domaine public (aucune attribution obligatoire).
Une source sans clé est sautée. Les clés se lisent dans PEXELS_API_KEY / PIXABAY_API_KEY ou dans les fichiers
agent-cm/.pexels_key et agent-cm/.pixabay_key (ignorés par git : le dépôt est public).

Parmi les résultats pertinents, on écarte ceux qui seraient flous une fois recadrés en vertical 9:16.
Les recherches se font en anglais (« leopard gecko », « planted aquarium ») : bien plus de résultats.
Cache : reels/media/.

Usage seul : python medias.py "leopard gecko" [video|photo] [pexels|pixabay|wikimedia|auto] [index]
Planche de choix : python medias.py "leopard gecko" photo auto --planche sortie.png
  télécharge les 6 premiers candidats et les montre côte à côte, numérotés : on regarde, puis on met le bon
  numéro dans "media_index" (et la source dans "media_source"). À faire avant chaque nouvelle image.
"""
import html, json, os, re, sys, unicodedata, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "reels", "media")
UA = {"User-Agent": "lecoinrare-reels/1.0 (https://github.com/bbiceofficiel-code/lecoinrare-reels)"}
SOURCES = ("pexels", "pixabay", "wikimedia")
MIN_SHARP = {"video": 600, "photo": 800}  # largeur utile minimale après recadrage vertical, en pixels
FREE_LICENSES = ("cc0", "public domain", "pd")


def api_key(name):
    key = os.environ.get(f"{name.upper()}_API_KEY", "").strip()
    path = os.path.join(ROOT, f".{name}_key")
    if not key and os.path.exists(path):
        key = open(path, encoding="utf-8").read().strip()
    return key or None


def sharpness(w, h):
    """Largeur utile une fois l'image recadrée en vertical 9:16 : plus c'est grand, plus c'est net dans le Reel."""
    return min(w, h * 9 / 16)


def _slug(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60]


def _json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def _download(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(path + ".part", "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(path + ".part", path)


# ---------------------------------------------------------------- sources : chacune renvoie des candidats pertinents, dans l'ordre de pertinence

def _pexels(query, kind, key):
    q, out = urllib.parse.quote(query), []
    if kind == "video":
        for v in _json(f"https://api.pexels.com/videos/search?query={q}&per_page=30", {"Authorization": key}).get("videos", []):
            files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("height")]
            if files:
                f = max(files, key=lambda f: sharpness(f["width"], f["height"]))
                out.append(dict(url=f["link"], w=f["width"], h=f["height"], ext=".mp4", credit=f'Vidéo : {v["user"]["name"]} sur Pexels', page=v["url"]))
    else:
        for p in _json(f"https://api.pexels.com/v1/search?query={q}&per_page=30", {"Authorization": key}).get("photos", []):
            out.append(dict(url=p["src"]["original"], w=p["width"], h=p["height"], ext=".jpg", credit=f'Photo : {p["photographer"]} sur Pexels', page=p["url"]))
    return out


def _pixabay(query, kind, key):
    q, out = urllib.parse.quote(query), []
    if kind == "video":
        for v in _json(f"https://pixabay.com/api/videos/?key={key}&q={q}&per_page=30&safesearch=true").get("hits", []):
            files = [f for f in v["videos"].values() if f.get("url") and f.get("width")]
            if files:
                f = max(files, key=lambda f: sharpness(f["width"], f["height"]))
                out.append(dict(url=f["url"], w=f["width"], h=f["height"], ext=".mp4", credit=f'Vidéo : {v["user"]} sur Pixabay', page=v["pageURL"]))
    else:
        for p in _json(f"https://pixabay.com/api/?key={key}&q={q}&image_type=photo&per_page=30&safesearch=true").get("hits", []):
            s = min(1, 1280 / max(p["imageWidth"], p["imageHeight"]))  # largeImageURL : 1280 px max sur le grand côté
            out.append(dict(url=p["largeImageURL"], w=int(p["imageWidth"] * s), h=int(p["imageHeight"] * s), ext=".jpg", credit=f'Photo : {p["user"]} sur Pixabay', page=p["pageURL"]))
    return out


def _wikimedia(query, kind, _key=None):
    search = f"{query} filetype:{'video' if kind == 'video' else 'bitmap'}"
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrsearch": search, "gsrlimit": 40,
              "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiextmetadatafilter": "LicenseShortName|Artist"}
    if kind == "photo":
        params["iiurlwidth"] = 2160  # vignette déjà redimensionnée : inutile de télécharger un original de 6000 px
    data = _json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "").lower()
        if not any(lic.startswith(f) for f in FREE_LICENSES) or not ii.get("width"):
            continue
        if kind == "video" and not ii.get("mime", "").startswith("video/"):
            continue
        artist = re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", ""))).strip() or "auteur inconnu"
        if kind == "photo" and ii.get("thumburl"):
            w, h, url = ii["thumbwidth"], ii["thumbheight"], ii["thumburl"]
        else:
            w, h, url = ii["width"], ii["height"], ii["url"]
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or (".webm" if kind == "video" else ".jpg")
        out.append(dict(url=url, w=w, h=h, ext=ext, credit=f"{'Vidéo' if kind == 'video' else 'Photo'} : {artist}, {lic.upper()}, Wikimedia Commons",
                        page=ii.get("descriptionurl", "")))
    return out


PROVIDERS = {"pexels": _pexels, "pixabay": _pixabay, "wikimedia": _wikimedia}


def fetch(query, kind="video", index=0, source=None):
    """Renvoie (chemin local, crédit), ou (None, None) si aucune source ne donne de résultat.

    kind = "video" ou "photo" ; index prend le résultat suivant si le premier ne convient pas
    (mauvaise espèce, animal mal maintenu : on ne montre jamais un animal en mauvaises conditions) ;
    source force une source ("pexels", "pixabay" ou "wikimedia").
    """
    os.makedirs(CACHE, exist_ok=True)
    base = os.path.join(CACHE, f"{_slug(query)}-{kind}-{source or 'auto'}-{index}")
    if os.path.exists(base + ".json"):
        m = json.load(open(base + ".json", encoding="utf-8"))
        if os.path.exists(m["path"]):
            return m["path"], m["credit"]
    for name in ([source] if source else SOURCES):
        key = api_key(name) if name != "wikimedia" else None
        if name != "wikimedia" and not key:
            continue
        try:
            found = PROVIDERS[name](query, kind, key)
        except Exception as e:  # source indisponible : on passe à la suivante
            print(f"{name} : recherche impossible ({e}).")
            continue
        # parmi les 12 résultats les plus pertinents, d'abord ceux qui restent nets et entiers une fois recadrés en vertical
        sharp = [c for c in found if sharpness(c["w"], c["h"]) >= MIN_SHARP[kind]]
        sharp = sorted(sharp[:12], key=lambda c: -sharpness(c["w"], c["h"])) + sharp[12:]
        if len(sharp) <= index:
            continue
        c = sharp[index]
        path = base + c["ext"]
        _download(c["url"], path)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"query": query, "source": name, "path": path, "credit": c["credit"], "page": c["page"], "size": [c["w"], c["h"]]},
                      f, ensure_ascii=False, indent=1)
        return path, c["credit"]
    return None, None


def planche(query, kind, source, out, n=6):
    """Planche des n premiers candidats, numérotés comme media_index, avec leur source."""
    import subprocess
    from PIL import Image, ImageDraw, ImageFont
    tiles = []
    for i in range(n):
        path, credit = fetch(query, kind, i, source)
        if not path:
            break
        if kind == "video":  # une image prise à 1 s de la vidéo
            still = path + ".png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", path, "-frames:v", "1", still], check=False)
            path = still
        img = Image.open(path).convert("RGB")
        s = max(270 / img.width, 480 / img.height)
        img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
        x0, y0 = (img.width - 270) // 2, (img.height - 480) // 2
        tile = img.crop((x0, y0, x0 + 270, y0 + 480))  # même recadrage vertical que dans le Reel
        d = ImageDraw.Draw(tile)
        d.rectangle([0, 0, 270, 34], fill=(16, 26, 19))
        d.text((8, 7), f"#{i}  {credit.split(',')[0][:30]}", fill=(244, 239, 230), font=ImageFont.load_default())
        tiles.append(tile)
    if not tiles:
        print("Aucun candidat.")
        return
    sheet = Image.new("RGB", (270 * len(tiles) + 6 * (len(tiles) - 1), 480), (0, 0, 0))
    for k, t in enumerate(tiles):
        sheet.paste(t, (k * 276, 0))
    sheet.save(out)
    print(f"Planche : {out} ({len(tiles)} candidats)")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    kind = a[1] if len(a) > 1 else "video"
    source = a[2] if len(a) > 2 and a[2] != "auto" else None
    if "--planche" in sys.argv:
        planche(a[0], kind, source, sys.argv[sys.argv.index("--planche") + 1])
    else:
        print(fetch(a[0], kind, int(a[3]) if len(a) > 3 else 0, source))
