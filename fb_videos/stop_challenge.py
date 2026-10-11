#!/usr/bin/env python3
"""
"Stop the picture" challenge video generator (9:16, 1080x1920, 30 fps).

Recreates the mechanics of the reference reel:
  - white background, small "99% X failed" tag top-left
  - one big "hero" object on top, a pyramid of 6 small objects underneath
  - thin red outlines of every object stay fixed
  - all objects slide left-right together on a sine wave (1.4 s per swing)
  - they line up with the outlines near the FASTEST point of the swing, so
    it's very hard to pause on (but one frame per swing really is perfect)
  - video length is a whole number of swings, so it loops seamlessly
    (Facebook counts replays -> more watch time)
  - male voiceover via Piper TTS (offline)

Usage:
  python3 stop_challenge.py --hero assets/1f99a.svg --item assets/1f345.svg out.mp4
  python3 stop_challenge.py --hero my_peacock.png --item my_tomato.png \
        --script "Only geniuses can stop this. Try it." out.mp4
  python3 stop_challenge.py --batch          # renders every preset in PRESETS

Hero / item can be .svg or a transparent .png (photo cut-outs look best).
"""
import argparse, io, math, os, subprocess, sys, tempfile, wave
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
W, H, FPS = 1080, 1920, 30
PERIOD_F = 42                 # frames per full swing (1.4 s, same as reference)
AMP = 182                     # swing amplitude in px
ALIGN_SIN = 0.34              # where on the swing objects match outlines
OUTLINE_RGB = (232, 92, 92)
OUTLINE_W = 3
VOICE = os.environ.get("PIPER_VOICE", os.path.join(ASSETS, "en_US-ryan-high.onnx"))
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/"

DEFAULT_SCRIPT = ("One of the hardest challenges in the world. I challenge you to stop the picture. "
                  "If you can stop it, take a screenshot and send it to us.")

PRESETS = [
    ("peacock_tomato",   "1f99a", "1f345", DEFAULT_SCRIPT),
    ("elephant_apple",   "1f418", "1f34e", "Ninety nine percent of people fail this. Stop the video when the elephant fits perfectly. "
                                           "If you can, take a screenshot and send it to us."),
    ("giraffe_donut",    "1f992", "1f369", "Only people with super fast reflexes can do this. Pause it when everything lines up. "
                                           "If you do it, send us the screenshot."),
    ("penguin_strawberry","1f427","1f353", "This is the hardest pause challenge on Facebook. Stop the picture exactly on the outline. "
                                           "Take a screenshot and send it to us."),
    ("lion_orange",      "1f981", "1f34a", "Can you stop the lion in the perfect spot? Almost nobody can. "
                                           "If you can, screenshot it and send it to us."),
]


# ---------------------------------------------------------------- assets
def load_rgba(path, height, max_w=None):
    """Load .svg or .png as RGBA scaled to `height` (and at most `max_w` wide), trimmed."""
    if path.lower().endswith(".svg"):
        import cairosvg
        png = cairosvg.svg2png(url=path, output_height=height * 2)
        im = Image.open(io.BytesIO(png)).convert("RGBA")
    else:
        im = Image.open(path).convert("RGBA")
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    im = im.crop(bbox)
    s = height / im.height
    if max_w and im.width * s > max_w:
        s = max_w / im.width
    return im.resize((max(1, round(im.width * s)), height), Image.LANCZOS)


def outline_of(im):
    """Thin red contour of an RGBA sprite, returned as RGBA of same size + padding."""
    pad = OUTLINE_W * 2
    a = np.array(im.getchannel("A"))
    a = np.pad(a, pad)
    m = (a > 110).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    canvas = np.zeros((*m.shape, 4), np.uint8)
    cv2.drawContours(canvas, cnts, -1, (*OUTLINE_RGB, 255), OUTLINE_W, lineType=cv2.LINE_AA)
    return Image.fromarray(canvas, "RGBA"), pad


def tag_image():
    """'99% ❌ failed' tag like the reference."""
    font = ImageFont.truetype(os.path.join(ASSETS, "Nunito.ttf"), 44)
    try:
        font.set_variation_by_axes([800])
    except Exception:
        pass
    x_icon = load_rgba(os.path.join(ASSETS, "274c.svg"), 40)
    t1, t2 = "99%", "failed"
    w1 = font.getlength(t1); w2 = font.getlength(t2)
    img = Image.new("RGBA", (int(w1 + w2 + x_icon.width + 16), 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((0, 4), t1, font=font, fill=(20, 20, 20))
    img.alpha_composite(x_icon, (int(w1) + 6, 10))
    d.text((int(w1) + x_icon.width + 10, 4), t2, font=font, fill=(20, 20, 20))
    return img


# ---------------------------------------------------------------- layout
def layout(hero, item):
    """Return list of (sprite, cx, cy) for the 'outline' (target) positions,
    whole composition centred vertically (slightly high, like the reference)."""
    gap, row_gap = 50, 8
    total = hero.height + gap + 3 * item.height + 2 * row_gap
    y0 = max(150, (H - total) // 2 - 40)
    out = [(hero, W // 2, y0 + hero.height // 2)]
    s = item.width + 26                       # spacing in pyramid
    top = y0 + hero.height + gap + item.height // 2
    rows = [1, 2, 3]
    for r, n in enumerate(rows):
        cy = top + r * (item.height + row_gap)
        for k in range(n):
            cx = W // 2 + (k - (n - 1) / 2) * s
            out.append((item, int(cx), int(cy)))
    return out


# ---------------------------------------------------------------- voice
def ensure_voice():
    if os.path.exists(VOICE):
        return
    print("downloading Piper voice (~120 MB) ...")
    for ext in ("", ".json"):
        subprocess.run(["curl", "-sSLf", "-o", VOICE + ext,
                        VOICE_URL + os.path.basename(VOICE) + ext], check=True)


def tts(text, wav_path):
    ensure_voice()
    subprocess.run([sys.executable, "-m", "piper", "-m", VOICE, "-f", wav_path,
                    "--length-scale", "1.0", "--sentence-silence", "0.35"],
                   input=text.encode(), check=True, capture_output=True)
    with wave.open(wav_path) as w:
        return w.getnframes() / w.getframerate()


def ffmpeg_bin():
    for c in ("ffmpeg",):
        if subprocess.run(["which", c], capture_output=True).returncode == 0:
            return c
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------- render
def render(hero_path, item_path, out_path, script=DEFAULT_SCRIPT, hero_h=760, item_h=230,
           tag=True):
    hero = load_rgba(hero_path, hero_h, max_w=560)
    item = load_rgba(item_path, item_h, max_w=item_h)
    slots = layout(hero, item)
    outlines = {id(hero): outline_of(hero), id(item): outline_of(item)}

    # static background: white + outlines + tag (outlines sit ALIGN offset to the right)
    align_dx = int(round(AMP * ALIGN_SIN))
    bg = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    for spr, cx, cy in slots:
        ol, pad = outlines[id(spr)]
        bg.alpha_composite(ol, (cx + align_dx - spr.width // 2 - pad, cy - spr.height // 2 - pad))
    if tag:
        bg.alpha_composite(tag_image(), (68, 52))

    tmp = tempfile.mkdtemp()
    wav = os.path.join(tmp, "vo.wav")
    vo_len = tts(script, wav) if script else 0.0
    swings = max(8, math.ceil((vo_len + 0.6) * FPS / PERIOD_F))
    n_frames = swings * PERIOD_F

    # phase chosen so frame 5 of every swing is a PERFECT match (fair challenge)
    phi = math.asin(ALIGN_SIN) - 2 * math.pi * 5 / PERIOD_F

    ff = ffmpeg_bin()
    cmd = [ff, "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if script:
        cmd += ["-i", wav, "-af", "apad,loudnorm=I=-14:TP=-1.5", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"]
    if script:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += [out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n_frames):
        dx = AMP * math.sin(2 * math.pi * f / PERIOD_F + phi)
        fr = bg.copy()
        for spr, cx, cy in slots:
            fr.alpha_composite(spr, (int(round(cx + dx - spr.width / 2)), cy - spr.height // 2))
        p.stdin.write(fr.convert("RGB").tobytes())
    p.stdin.close()
    if p.wait():
        raise SystemExit("ffmpeg failed")
    print(f"{out_path}  {n_frames / FPS:.1f}s  ({swings} swings, voice {vo_len:.1f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--hero"); ap.add_argument("--item")
    ap.add_argument("--script", default=DEFAULT_SCRIPT)
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--outdir", default=os.path.join(HERE, "output"))
    a = ap.parse_args()
    if a.batch:
        os.makedirs(a.outdir, exist_ok=True)
        for name, h, i, s in PRESETS:
            render(os.path.join(ASSETS, h + ".svg"), os.path.join(ASSETS, i + ".svg"),
                   os.path.join(a.outdir, name + ".mp4"), s)
        return
    if not (a.hero and a.item and a.out):
        ap.error("need --hero, --item and an output path (or --batch)")
    render(a.hero, a.item, a.out, None if a.no_voice else a.script)


if __name__ == "__main__":
    main()
