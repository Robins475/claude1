#!/usr/bin/env python3
"""
"Stop the picture" challenge video generator (9:16, 1080x1920, 30 fps).

Recreates the mechanics of the reference reel:
  - white background, small "99% X failed" tag top-left
  - one big "hero" object on top, a pyramid of 6 small objects underneath
  - thin red outlines of every object stay fixed
  - all objects slide left-right together on a sine wave (1.4 s per swing)
  - outlines are centred on screen and objects swing symmetrically around them;
    they line up at the FASTEST point of the swing (dead centre), so
    it's very hard to pause on (but one frame per swing really is perfect)
  - video length is a whole number of swings, so it loops seamlessly
    (Facebook counts replays -> more watch time)
  - human-sounding 'hype' male voiceover via Chatterbox (Kokoro fallback), offline

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
ALIGN_SIN = 0.0               # objects match outlines at the centre of the swing (its fastest point)
OUTLINE_RGB = (232, 92, 92)
OUTLINE_W = 3
VOICE = os.environ.get("VOICE", "am_fenrir")

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
        if im.getchannel("A").getextrema()[0] == 255:   # no transparency -> cut it out
            im = cutout(im)
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    im = im.crop(bbox)
    s = height / im.height
    if max_w and im.width * s > max_w:
        s = max_w / im.width
    return im.resize((max(1, round(im.width * s)), height), Image.LANCZOS)


def cutout(im):
    """Remove the background of a photo / AI image (e.g. ChatGPT render on white)."""
    from rembg import remove, new_session
    out = remove(im.convert("RGB"), session=new_session("isnet-general-use"),
                 post_process_mask=True)
    a = np.array(out.getchannel("A"))
    # keep only the largest blob so stray background specks don't get outlines
    n, lab, stats, _ = cv2.connectedComponentsWithStats((a > 110).astype(np.uint8))
    if n > 2:
        keep = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        a[(lab != keep) & (lab != 0)] = 0
        out.putalpha(Image.fromarray(a))
    return out


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
    whole composition centred on screen."""
    gap, row_gap = 50, 8
    total = hero.height + gap + 3 * item.height + 2 * row_gap
    y0 = max(150, (H - total) // 2)
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
# Kokoro neural TTS (Apache-2.0, runs offline). am_fenrir is the closest match
# to the reference voice (~150 Hz, deliberate pace). Others: am_michael, am_adam,
# am_puck, bm_george (British) ...
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
_kokoro = None


def ensure_voice():
    global _kokoro
    if _kokoro:
        return _kokoro
    for f in KOKORO_FILES:
        path = os.path.join(ASSETS, f)
        if not os.path.exists(path):
            print(f"downloading {f} ...")
            subprocess.run(["curl", "-sSLf", "-o", path, KOKORO_URL + f], check=True)
    from kokoro_onnx import Kokoro
    _kokoro = Kokoro(*(os.path.join(ASSETS, f) for f in KOKORO_FILES))
    return _kokoro


def tts(text, wav_path, voice=VOICE, speed=0.92, gap=0.3):
    """Speak each sentence separately with a short natural pause between them."""
    import re, soundfile as sf
    k = ensure_voice()
    lang = "en-gb" if voice.startswith("b") else "en-us"
    parts, sr = [], 24000
    for sent in [t for t in re.split(r"(?<=[.!?])\s+", text.strip()) if t]:
        a, sr = k.create(sent, voice=voice, speed=speed, lang=lang)
        parts += [np.asarray(a, np.float32), np.zeros(int(gap * sr), np.float32)]
    audio = np.concatenate(parts[:-1])
    sf.write(wav_path, audio, sr)
    return len(audio) / sr


# Chatterbox (default): same fenrir voice, human "hype" delivery. Needs its own venv,
# see tts_chatterbox.py. Falls back to Kokoro if that venv isn't there.
TTS_PY = os.environ.get("TTS_PY", os.path.join(HERE, ".venv-tts", "bin", "python"))


def tts_expressive(jobs):
    """jobs: list of (text, wav_path). One model load for the whole list."""
    import json
    if not os.path.exists(TTS_PY):
        print("Chatterbox venv not found -> using Kokoro voice")
        for text, wav in jobs:
            tts(text, wav)
        return
    jf = os.path.join(tempfile.mkdtemp(), "jobs.json")
    json.dump(jobs, open(jf, "w"))
    subprocess.run([TTS_PY, os.path.join(HERE, "tts_chatterbox.py"), jf], check=True,
                   stderr=subprocess.DEVNULL)


def wav_len(path):
    import soundfile as sf
    return sf.info(path).duration


def ffmpeg_bin():
    for c in ("ffmpeg",):
        if subprocess.run(["which", c], capture_output=True).returncode == 0:
            return c
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------- render
def render(hero_path, item_path, out_path, script=DEFAULT_SCRIPT, hero_h=760, item_h=230,
           tag=True, voice_wav=None):
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
    wav = voice_wav or os.path.join(tmp, "vo.wav")
    if script and not voice_wav:
        tts_expressive([(script, wav)])
    vo_len = wav_len(wav) if script else 0.0
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
        tmp = tempfile.mkdtemp()
        wavs = [os.path.join(tmp, name + ".wav") for name, *_ in PRESETS]
        tts_expressive([(s, w) for (_, _, _, s), w in zip(PRESETS, wavs)])
        for (name, h, i, s), w in zip(PRESETS, wavs):
            render(os.path.join(ASSETS, h + ".svg"), os.path.join(ASSETS, i + ".svg"),
                   os.path.join(a.outdir, name + ".mp4"), s, voice_wav=w)
        return
    if not (a.hero and a.item and a.out):
        ap.error("need --hero, --item and an output path (or --batch)")
    render(a.hero, a.item, a.out, None if a.no_voice else a.script)


if __name__ == "__main__":
    main()
