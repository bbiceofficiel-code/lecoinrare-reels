"""Voix off naturelle et gratuite : Chatterbox multilingue (Resemble AI, licence MIT), sur la carte graphique.

Voix « estelle » : enregistrement CC0 de Kyutai (kyutai/tts-voices, unmute-prod-website/developpeuse-3.wav),
copié dans generateur/voix/estelle.wav. Chatterbox imite cette voix et lit le texte en français.

Chatterbox dérape parfois (il invente une suite au texte, ou bafouille). Chaque phrase est donc réécoutée par
Whisper : si la transcription s'éloigne du texte ou si la durée est anormale, on régénère (jusqu'à 5 essais)
et on garde le meilleur. Les phrases déjà validées sont gardées en cache (generateur/voix/cache/).

Ce script tourne dans un environnement Python à part (Chatterbox impose d'autres versions de bibliothèques) :
  %LOCALAPPDATA%\\lecoinrare-voix\\venv\\Scripts\\python.exe voix_naturelle.py demandes.json
demandes.json : [{"text": "...", "out": "chemin.wav"}, ...] ; reel.py l'appelle tout seul.
"""
import difflib, hashlib, json, os, re, shutil, sys, unicodedata
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VOIX = os.path.join(HERE, "voix")
CACHE = os.path.join(VOIX, "cache")
REFS = {"estelle": ("kyutai/tts-voices", "unmute-prod-website/developpeuse-3.wav")}
REGLAGES = dict(exaggeration=0.7, cfg_weight=0.5)  # choix de l'utilisateur le 28/10 : échantillon D, plus vif (C jugé trop mou)
ESSAIS, SEUIL = 5, 0.85


NOMBRES = set("zero un une deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize "
               "vingt trente quarante cinquante soixante cent cents mille et point".split())


def mots(t):
    t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", t)


def ressemblance(attendu, entendu):
    """Ressemblance lettre à lettre, sans les nombres : Whisper écrit « 15 » ce qu'on a écrit « quinze »,
    et « lecoinrare.com » ce qu'on a écrit « le coin rare point com »."""
    net = lambda t: "".join(m for m in mots(t) if not m.isdigit() and m not in NOMBRES)
    return difflib.SequenceMatcher(None, net(attendu), net(entendu)).ratio()


def reference(name):
    path = os.path.join(VOIX, f"{name}.wav")
    if not os.path.exists(path):
        from huggingface_hub import hf_hub_download
        os.makedirs(VOIX, exist_ok=True)
        shutil.copy(hf_hub_download(*REFS[name]), path)
    return path


def rogner(wav, sr, seuil=0.01, marge=0.08):
    """Enlève les silences de début et de fin (garde 80 ms)."""
    idx = np.flatnonzero(np.abs(wav) > seuil * (np.abs(wav).max() or 1))
    if not len(idx):
        return wav
    a, b = max(0, idx[0] - int(marge * sr)), min(len(wav), idx[-1] + int(marge * sr))
    return wav[a:b]


def main(demandes_path, name="estelle"):
    import librosa, soundfile as sf, torch
    demandes = json.load(open(demandes_path, encoding="utf-8-sig"))
    os.makedirs(CACHE, exist_ok=True)
    key = lambda t: hashlib.sha1(f"{name}|{REGLAGES}|{t}".encode()).hexdigest()[:16]
    todo = [d for d in demandes if not os.path.exists(os.path.join(CACHE, key(d["text"]) + ".wav"))]
    if todo:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        from faster_whisper import WhisperModel
        tts = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
        tts.prepare_conditionals(reference(name), exaggeration=REGLAGES["exaggeration"])
        oreille = WhisperModel("small", device="cpu", compute_type="int8")
        for d in todo:
            best = None
            for essai in range(ESSAIS):
                torch.manual_seed(1000 + essai)
                wav = tts.generate(d["text"], language_id="fr", **REGLAGES).squeeze().cpu().numpy()
                wav = rogner(wav, tts.sr)
                segs, _ = oreille.transcribe(librosa.resample(wav, orig_sr=tts.sr, target_sr=16000), language="fr")
                entendu = " ".join(s.text for s in segs)
                score = ressemblance(d["text"], entendu)
                duree, attendu = len(wav) / tts.sr, 0.42 * len(mots(d["text"])) + 1.5
                if duree > attendu * 1.6:  # a continué à parler après le texte
                    score -= 0.5
                print(f"  essai {essai + 1} : {score:.2f} ({duree:.1f} s) « {entendu.strip()[:70]} »", flush=True)
                if best is None or score > best[0]:
                    best = (score, wav)
                if score >= SEUIL:
                    break
            if best[0] < SEUIL:
                print(f"  ATTENTION : meilleure version à {best[0]:.2f} pour « {d['text'][:60]} » (à réécouter)", flush=True)
            sf.write(os.path.join(CACHE, key(d["text"]) + ".wav"), best[1], tts.sr)
    for d in demandes:
        shutil.copy(os.path.join(CACHE, key(d["text"]) + ".wav"), d["out"])


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))
