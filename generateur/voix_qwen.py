"""Voix off plus humaine : Qwen3-TTS 1.7B (Alibaba, licence Apache 2.0), sur la carte graphique.

Différence avec voix_naturelle.py (Chatterbox) : tout le texte du Reel est lu d'une traite, comme le ferait
quelqu'un qui parle, au lieu d'une phrase à la fois. L'intonation enchaîne d'une phrase à l'autre, les pauses
et le débit sont ceux du modèle (pas d'accélération). Whisper réécoute la lecture, la refait si elle dérape,
puis la découpe phrase par phrase (au milieu des silences) pour le montage.

Voix « estelle » : même enregistrement CC0 de Kyutai que voix_naturelle.py (conversation spontanée), avec sa
transcription : Qwen imite le timbre et la façon de parler.

Ce script tourne dans un environnement Python à part (Qwen impose transformers 4.57.3) :
  %LOCALAPPDATA%\\lecoinrare-qwen\\venv\\Scripts\\python.exe voix_qwen.py demandes.json [voix]
demandes.json : [{"text": "...", "out": "chemin.wav"}, ...] ; reel.py l'appelle tout seul (voix « estelle-qwen »).
"""
import hashlib, json, os, shutil, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voix_naturelle import CACHE, mots, reference, rogner

MODELE = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
TRANSCRIPTIONS = {
    "estelle": "Je voulais pas vraiment de grands souvenirs, pour être très honnête, je me souviens pas, moi j'aimais "
               "bien l'école donc ça va. Très très bonne question, j'ai aucun souvenir. Je peux faire la liste de "
               "poésies que j'ai apprises, ou les fables de La Fontaine, ça c'est sûr.",
}
ESSAIS, SEUIL = 4, 0.85  # SEUIL : part des mots du texte retrouvés par Whisper


CHIFFRES = dict(enumerate("zero un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze "
                          "seize dix-sept dix-huit dix-neuf vingt".split()))
# la diction de reel.py écrit « pé-hache », Whisper entend « pH » : on défait la diction avant de comparer
SONS = [("pé-hache", "pH"), ("u-vé-bé", "UVB"), ("u-vé", "UV"), ("kouiz", "quiz"), ("Kouiz", "Quiz"), ("D trois", "D3")]


def jetons(t):
    """Mots comparables entre le texte demandé et ce que Whisper a écrit (chiffres en lettres, diction défaite)."""
    for a, b in SONS:
        t = t.replace(a, b)
    return [CHIFFRES.get(int(m), m) if m.isdigit() and int(m) <= 20 else m for m in mots(t)]


def aligner(textes, mots_w):
    """Pour chaque phrase, l'indice du dernier mot entendu qui lui appartient, et la part de mots retrouvés."""
    import difflib
    attendus, fins = [], []
    for t in textes:
        attendus += jetons(t)
        fins.append(len(attendus) - 1)
    entendus, proprio = [], []  # jeton entendu -> mot Whisper qui le contient
    for i, w in enumerate(mots_w):
        for j in jetons(w.word):
            entendus.append(j)
            proprio.append(i)
    blocs = difflib.SequenceMatcher(None, attendus, entendus, autojunk=False).get_matching_blocks()
    correspond = {a + k: b + k for a, b, n in blocs for k in range(n)}
    score = sum(n for *_, n in blocs) / max(len(attendus), 1)
    derniers = []
    for f in fins:  # dernier jeton de la phrase retrouvé, sinon le plus proche avant lui, décalé d'autant
        a = max((a for a in correspond if a <= f), default=None)
        b = 0 if a is None else min(correspond[a] + f - a, len(proprio) - 1)
        derniers.append(proprio[b])
    return derniers, score


def decouper(wav, sr, mots_w, textes):
    """Coupe la lecture d'une traite en phrases, au milieu du silence qui suit le dernier mot de chaque phrase."""
    derniers, _ = aligner(textes, mots_w)
    coupes = [0]
    for k in derniers[:-1]:
        k = min(max(k, 0), len(mots_w) - 2)
        coupes.append(int((mots_w[k].end + mots_w[k + 1].start) / 2 * sr))
    coupes.append(min(len(wav), int((mots_w[-1].end + 0.3) * sr)))  # rien après le dernier mot (syllabes parasites)
    return [rogner(wav[a:b], sr, marge=0.12) for a, b in zip(coupes, coupes[1:])]


def main(demandes_path, name="estelle"):
    import librosa, soundfile as sf, torch
    demandes = json.load(open(demandes_path, encoding="utf-8-sig"))
    textes = [d["text"] for d in demandes]
    os.makedirs(CACHE, exist_ok=True)
    cle = hashlib.sha1(f"qwen|{name}|{MODELE}|aligne|{'§'.join(textes)}".encode()).hexdigest()[:16]
    caches = [os.path.join(CACHE, f"{cle}-{i}.wav") for i in range(len(textes))]
    if not all(map(os.path.exists, caches)):
        from qwen_tts import Qwen3TTSModel
        from faster_whisper import WhisperModel
        tts = Qwen3TTSModel.from_pretrained(MODELE, device_map="cuda:0", dtype=torch.bfloat16)
        voix = tts.create_voice_clone_prompt(ref_audio=reference(name), ref_text=TRANSCRIPTIONS[name])
        oreille = WhisperModel("small", device="cpu", compute_type="int8")
        best = None
        for essai in range(ESSAIS):
            torch.manual_seed(1 + essai)
            wavs, sr = tts.generate_voice_clone(text=" ".join(textes), language="French", voice_clone_prompt=voix)
            wav = rogner(np.asarray(wavs[0], dtype=np.float32), sr)
            segs, _ = oreille.transcribe(librosa.resample(wav, orig_sr=sr, target_sr=16000), language="fr",
                                         word_timestamps=True)
            mots_w = [w for s in segs for w in (s.words or [])]
            entendu = "".join(w.word for w in mots_w)
            score = aligner(textes, mots_w)[1] if mots_w else 0
            duree, attendu = len(wav) / sr, 0.36 * len(mots(" ".join(textes))) + 1.5
            if duree > attendu * 1.5:  # a continué à parler après le texte
                score -= 0.5
            print(f"  essai {essai + 1} : {score:.2f} ({duree:.1f} s) « {entendu.strip()[:90]} »", flush=True)
            if best is None or score > best[0]:
                best = (score, wav, sr, mots_w)
            if score >= SEUIL:
                break
        score, wav, sr, mots_w = best
        if score < SEUIL:
            print(f"  ATTENTION : meilleure lecture à {score:.2f} (à réécouter)", flush=True)
        for morceau, path in zip(decouper(wav, sr, mots_w, textes), caches):
            sf.write(path, morceau, sr)
    for d, path in zip(demandes, caches):
        shutil.copy(path, d["out"])


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))
