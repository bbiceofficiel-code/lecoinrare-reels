"""Cherche et télécharge des photos ou vidéos libres de droits sur Pexels (gratuit, clé API requise).

La clé se lit dans la variable d'environnement PEXELS_API_KEY ou dans le fichier agent-cm/.pexels_key
(ignoré par git : le dépôt est public). Les fichiers sont gardés en cache dans reels/media/.

Usage seul : python pexels.py "leopard gecko" [video|photo]
"""
import json, os, re, sys, unicodedata, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "reels", "media")
UA = {"User-Agent": "lecoinrare-reels"}


def api_key():
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    path = os.path.join(ROOT, ".pexels_key")
    if not key and os.path.exists(path):
        key = open(path, encoding="utf-8").read().strip()
    return key or None


def _slug(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60]


def _get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": key, **UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _download(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r, open(path + ".part", "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(path + ".part", path)


def fetch(query, kind="video", index=0, min_height=1920):
    """Renvoie (chemin local, crédit), ou (None, None) sans clé ou sans résultat.

    kind = "video" ou "photo" ; index prend un autre résultat si le premier ne convient pas
    (animal mal maintenu, mauvaise espèce : on ne montre jamais un animal en mauvaises conditions).
    Les recherches se font en anglais (« leopard gecko », « planted aquarium ») : bien plus de résultats.
    """
    key = api_key()
    if not key:
        return None, None
    os.makedirs(CACHE, exist_ok=True)
    base = os.path.join(CACHE, f"{_slug(query)}-{kind}-{index}")
    meta = base + ".json"
    if os.path.exists(meta):
        m = json.load(open(meta, encoding="utf-8"))
        if os.path.exists(m["path"]):
            return m["path"], m["credit"]
    q = urllib.parse.quote(query)
    if kind == "video":
        items = _get(f"https://api.pexels.com/videos/search?query={q}&orientation=portrait&per_page=15", key).get("videos", [])
        if len(items) <= index:
            return None, None
        v = items[index]
        files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("height")]
        if not files:
            return None, None
        # le plus petit fichier qui atteint la hauteur du Reel (souvent du 4K), sinon le plus grand disponible
        tall = sorted((f for f in files if f["height"] >= min_height), key=lambda f: f["height"])
        best = tall[0] if tall else max(files, key=lambda f: f["height"])
        url, ext, credit, page = best["link"], ".mp4", f'Vidéo : {v["user"]["name"]} sur Pexels', v["url"]
    else:
        items = _get(f"https://api.pexels.com/v1/search?query={q}&orientation=portrait&per_page=15", key).get("photos", [])
        if len(items) <= index:
            return None, None
        p = items[index]
        url, ext, credit, page = p["src"]["original"], ".jpg", f'Photo : {p["photographer"]} sur Pexels', p["url"]
    path = base + ext
    _download(url, path)
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"query": query, "path": path, "credit": credit, "page": page}, f, ensure_ascii=False, indent=1)
    return path, credit


if __name__ == "__main__":
    print(fetch(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "video"))
