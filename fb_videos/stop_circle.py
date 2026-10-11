#!/usr/bin/env python3
"""
"Stop it in the circle" reel (9:16, 1080x1920, 30 fps).

A full photo swings left-right on a sine wave; a red circle stays fixed on
screen. The viewer has to pause when the target detail (sunglasses, cocktail,
face...) sits inside the circle. The match happens at the centre of the swing
(its fastest point), one perfect frame per swing; the video is a whole number
of swings so it loops seamlessly. Voiceover uses the same hype voice as
stop_challenge.py.

Photos: StockSnap CC0 (free for commercial use, no attribution required).

Usage:
  python3 stop_circle.py --batch
  python3 stop_circle.py --photo pic.jpg --target 375,280 --radius 150 --script "..." out.mp4
"""
import argparse, math, os, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from stop_challenge import (W, H, FPS, PERIOD_F, HERE, tag_image, tts_expressive, wav_len,
                            ffmpeg_bin)

AMP = 230                       # swing amplitude (px)
CARD_W, CARD_MAX_H = 940, 1340  # photo card size limits
CARD_CY = 1010                  # vertical centre of the card
RING = (235, 40, 50)

# name, photo, target (x, y) in photo pixels, circle radius in photo pixels, script
PRESETS = [
    ("sunglasses", "Q2WJXI3CSE.jpg", (375, 280), 150,
     "Stop her sunglasses inside the circle. Sounds easy, right? Ninety nine percent of people fail. "
     "If you do it, screenshot it and send it to us!"),
    ("beach", "PIY6WUNQ3C.jpg", (522, 340), 95,
     "Can you stop her face perfectly inside the red circle? Almost nobody can. "
     "Take a screenshot and send it to us!"),
    ("cocktail", "YZTR1MJBMJ.jpg", (349, 512), 75,
     "Only people with lightning reflexes can stop the cocktail inside the circle. Think you can? "
     "Screenshot it and send it to us!"),
    ("sunhat", "0VHNHWWKLW.jpg", (710, 278), 95,
     "Stop her face right inside the circle. It's harder than it looks! "
     "If you can do it, take a screenshot and send it to us!"),
    ("sunset", "L8LYHYBS81.jpg", (589, 266), 90,
     "This is the hardest stop challenge on Facebook. Get her face inside the circle. "
     "If you can, send us your screenshot!"),
]


def card(photo, radius=36):
    """Scale photo to fit the card box, round the corners, add a soft shadow."""
    s = min(CARD_W / photo.width, CARD_MAX_H / photo.height)
    ph = photo.resize((round(photo.width * s), round(photo.height * s)), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", ph.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, ph.width - 1, ph.height - 1), radius, fill=255)
    ph.putalpha(m)
    pad = 40
    sh = Image.new("RGBA", (ph.width + 2 * pad, ph.height + 2 * pad), (0, 0, 0, 0))
    sm = Image.new("L", sh.size, 0)
    ImageDraw.Draw(sm).rounded_rectangle((pad, pad + 12, pad + ph.width, pad + ph.height + 12), radius, fill=70)
    sh.putalpha(sm.filter(ImageFilter.GaussianBlur(18)))
    sh.alpha_composite(ph, (pad, pad))
    return sh, s, pad


def ring_layer(cx, cy, r):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.ellipse((cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7), outline=(255, 255, 255, 230), width=14)
    d.ellipse((cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4), outline=RING + (255,), width=8)
    return lay


def crop_square_if_wide(photo, target):
    """Landscape photos look tiny on a 9:16 screen: crop to a square around the target."""
    if photo.width <= photo.height:
        return photo, target
    side = photo.height
    left = int(min(max(target[0] - side / 2, 0), photo.width - side))
    return photo.crop((left, 0, left + side, side)), (target[0] - left, target[1])


def render(photo_path, target, radius, out_path, script, voice_wav=None):
    photo, target = crop_square_if_wide(Image.open(photo_path).convert("RGB"), target)
    cd, s, pad = card(photo)
    x0 = W // 2 - cd.width // 2                     # card position at swing centre
    y0 = CARD_CY - cd.height // 2
    tx, ty = x0 + pad + target[0] * s, y0 + pad + target[1] * s
    ring = ring_layer(round(tx), round(ty), round(max(radius * s, 60)))

    bg = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    bg.alpha_composite(tag_image(), (68, 52))

    wav = voice_wav or os.path.join(tempfile.mkdtemp(), "vo.wav")
    if not voice_wav:
        tts_expressive([(script, wav)])
    swings = max(8, math.ceil((wav_len(wav) + 0.6) * FPS / PERIOD_F))
    n = swings * PERIOD_F
    phi = -2 * math.pi * 5 / PERIOD_F               # frame 5 of each swing = perfect

    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", wav,
           "-af", "apad,loudnorm=I=-14:TP=-1.5", "-t", f"{n / FPS:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n):
        dx = AMP * math.sin(2 * math.pi * f / PERIOD_F + phi)
        fr = bg.copy()
        fr.paste(cd, (round(x0 + dx), y0), cd)     # paste: allows negative x (off-screen)
        fr.alpha_composite(ring)
        p.stdin.write(fr.convert("RGB").tobytes())
    p.stdin.close()
    if p.wait():
        raise SystemExit("ffmpeg failed")
    print(f"{out_path}  {n / FPS:.1f}s  ({swings} swings, voice {wav_len(wav):.1f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--photo"); ap.add_argument("--target"); ap.add_argument("--radius", type=int, default=100)
    ap.add_argument("--script", default="Stop it inside the circle. If you can, screenshot it and send it to us!")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--outdir", default=os.path.join(HERE, "output"))
    a = ap.parse_args()
    if a.batch:
        os.makedirs(a.outdir, exist_ok=True)
        tmp = tempfile.mkdtemp()
        wavs = [os.path.join(tmp, p[0] + ".wav") for p in PRESETS]
        tts_expressive([(p[4], w) for p, w in zip(PRESETS, wavs)])
        for (name, ph, tgt, r, sc), w in zip(PRESETS, wavs):
            render(os.path.join(HERE, "photos", ph), tgt, r,
                   os.path.join(a.outdir, f"circle_{name}.mp4"), sc, voice_wav=w)
        return
    if not (a.photo and a.target and a.out):
        ap.error("need --photo, --target x,y and an output path (or --batch)")
    render(a.photo, tuple(int(v) for v in a.target.split(",")), a.radius, a.out, a.script)


if __name__ == "__main__":
    main()
