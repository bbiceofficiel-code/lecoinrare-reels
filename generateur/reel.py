"""Génère un Reel vertical 1080x1920 (texte animé aux couleurs LeCoinRare) à partir d'un fichier JSON.

Usage : python3 reel.py spec.json sortie.mp4
"""
import json, subprocess, sys, math
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
VERT = (28, 42, 31)        # #1C2A1F, couleur de marque
VERT_CLAIR = (46, 70, 52)
CREME = (244, 239, 230)
AMBRE = (232, 180, 74)
ROUGE = (226, 104, 86)
FONT_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FONT_DISPLAY = "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf"
FONT_REG = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        test = (cur + " " + word).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def draw_block(draw, text, fnt, y, color, t, max_w=900, line_gap=1.18, align="center"):
    """Dessine un bloc de texte qui glisse depuis le bas et apparaît en fondu. Renvoie le y de fin."""
    lines = wrap(draw, text, fnt, max_w)
    size = fnt.size
    a = ease(t)
    offset = int((1 - a) * 60)
    col = tuple(int(c * a + v * (1 - a)) for c, v in zip(color, VERT))
    for line in lines:
        w = draw.textlength(line, font=fnt)
        x = (W - w) / 2 if align == "center" else 90
        draw.text((x, y + offset), line, font=fnt, fill=col)
        y += int(size * line_gap)
    return y


def background(draw, progress):
    draw.rectangle([0, 0, W, H], fill=VERT)
    # motif discret de cercles (écailles / bulles)
    for i in range(7):
        r = 220 + i * 40
        cx = W - 60 + int(30 * math.sin(progress * 2 + i))
        cy = 260 + i * 260
        draw.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3], outline=VERT_CLAIR, width=3)


def brand(draw):
    f = font(FONT_BOLD, 40)
    draw.text((90, 110), "LeCoinRare", font=f, fill=AMBRE)
    f2 = font(FONT_REG, 30)
    draw.text((90, 160), "Le réseau des passionnés d'animaux", font=f2, fill=CREME)


def progress_bar(draw, p):
    draw.rectangle([90, H - 140, W - 90, H - 128], fill=VERT_CLAIR)
    draw.rectangle([90, H - 140, 90 + int((W - 180) * p), H - 128], fill=AMBRE)


def render_scene(draw, scene, t, local):
    kind = scene["type"]
    if kind == "hook":
        y = 640
        y = draw_block(draw, scene.get("kicker", ""), font(FONT_BOLD, 52), y, AMBRE, local * 3)
        y += 30
        draw_block(draw, scene["title"], font(FONT_DISPLAY, 104), y, CREME, local * 3 - 0.3)
    elif kind == "point":
        num = font(FONT_DISPLAY, 260)
        a = ease(local * 3)
        draw.text((90, 430 - int((1 - a) * 80)), str(scene["n"]), font=num, fill=ROUGE if scene.get("warn") else AMBRE)
        y = 780
        y = draw_block(draw, scene["title"], font(FONT_DISPLAY, 92), y, CREME, local * 3 - 0.2, align="left")
        y += 40
        draw_block(draw, scene["text"], font(FONT_REG, 54), y, CREME, local * 3 - 0.6, align="left")
    elif kind == "outro":
        y = 700
        y = draw_block(draw, scene["title"], font(FONT_DISPLAY, 96), y, CREME, local * 3)
        y += 50
        y = draw_block(draw, scene["text"], font(FONT_REG, 56), y, AMBRE, local * 3 - 0.4)
        y += 80
        a = ease(local * 3 - 0.8)
        if a > 0:
            f = font(FONT_BOLD, 54)
            label = scene.get("cta", "Abonnez-vous")
            w = draw.textlength(label, font=f)
            x0, y0 = (W - w) / 2 - 50, y
            draw.rounded_rectangle([x0, y0, x0 + w + 100, y0 + 110], radius=55, fill=AMBRE)
            draw.text((x0 + 50, y0 + 22), label, font=f, fill=VERT)


def main(spec_path, out_path):
    spec = json.load(open(spec_path, encoding="utf-8"))
    scenes = spec["scenes"]
    total = sum(s["duration"] for s in scenes)
    nframes = int(total * FPS)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-f", "lavfi", "-t", str(total), "-i", "anullsrc=r=44100:cl=stereo",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-shortest", "-movflags", "+faststart", out_path],
        stdin=subprocess.PIPE)
    for i in range(nframes):
        t = i / FPS
        acc = 0
        for s in scenes:
            if t < acc + s["duration"]:
                scene, local = s, (t - acc) / s["duration"]
                break
            acc += s["duration"]
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        background(d, t)
        brand(d)
        render_scene(d, scene, t, local)
        progress_bar(d, t / total)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    proc.wait()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
