"""
101 Studios "luxury clean" HDR merge.

Usage:
  python3 hdr_luxe.py OUT.jpg BRACKET1 BRACKET2 BRACKET3 [...]   (RAW or JPG/TIFF)
  python3 hdr_luxe.py --batch IN_DIR OUT_DIR                     (one sub-folder of brackets per room)

Look targets were measured from the reference listing photos:
  - bright, airy midtones (median L* ~76), true blacks kept (1st pct ~1-2)
  - walls neutral with a faint warmth (b* +2..+4 on whites), never blue or yellow
  - restrained saturation, windows held (no blown-out glass), straight verticals
"""
import glob
import os
import sys

import cv2
import numpy as np

RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw"}

# Look parameters (tune here)
TARGET_MEDIAN_L = 76.0     # overall brightness
WHITE_POINT_L = 98.0       # where the 99.5th percentile lands
BLACK_POINT_L = 1.5        # where the 0.5th percentile lands
WALL_WARMTH_B = 2.0        # b* of near-white surfaces after correction
SATURATION = 0.88          # global chroma multiplier
CLARITY = 0.18             # large-radius local contrast
SHARPEN = 0.35
MAX_LONG_EDGE = 6000


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXT:
        import rawpy
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16, gamma=(2.222, 4.5))
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).astype(np.float32) / 65535.0
    else:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise SystemExit(f"Can't read {path}")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = img[..., :3]
        img = img.astype(np.float32) / (65535.0 if img.dtype == np.uint16 else 255.0)
    h, w = img.shape[:2]
    s = MAX_LONG_EDGE / max(h, w)
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def order_by_brightness(imgs):
    return sorted(imgs, key=lambda im: float(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).mean()))


def align(imgs):
    u8 = [np.clip(i * 255, 0, 255).astype(np.uint8) for i in imgs]
    cv2.createAlignMTB(max_bits=6).process(u8, u8)
    # MTB only shifts; apply the same shift to float images via phase of u8 result
    out = []
    for f, a in zip(imgs, u8):
        g0 = cv2.cvtColor(np.clip(f * 255, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
        g1 = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
        (dx, dy), _ = cv2.phaseCorrelate(g0, g1)
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        out.append(cv2.warpAffine(f, M, (f.shape[1], f.shape[0]), borderMode=cv2.BORDER_REFLECT))
    return out


def fuse(imgs):
    merge = cv2.createMergeMertens(contrast_weight=1.0, saturation_weight=0.6, exposure_weight=1.0)
    fused = merge.process([np.clip(i, 0, 1) for i in imgs])
    fused = np.clip(fused, 0, None)
    return fused / max(1e-6, np.percentile(fused, 99.9))


def window_pull(fused, imgs):
    """Bring back exterior detail in windows from the darkest frame."""
    if len(imgs) < 2:
        return fused
    mid = imgs[len(imgs) // 2]
    dark = imgs[0]
    lum = cv2.cvtColor(np.clip(mid, 0, 1), cv2.COLOR_BGR2GRAY)
    mask = np.clip((lum - 0.90) / 0.08, 0, 1)
    mask = cv2.GaussianBlur(mask, (0, 0), max(fused.shape[:2]) / 300)
    # match the dark frame's window brightness to a pleasant, slightly bright exterior
    d_lum = cv2.cvtColor(np.clip(dark, 0, 1), cv2.COLOR_BGR2GRAY)
    m = mask > 0.5
    if m.sum() < 50:
        return fused
    gain = np.clip(0.80 / max(1e-4, np.median(d_lum[m])), 0.5, 6.0)
    dark_adj = np.clip(dark * gain, 0, 1)
    return fused * (1 - mask[..., None] * 0.85) + dark_adj * (mask[..., None] * 0.85)


def to_lab(bgr):
    return cv2.cvtColor(np.clip(bgr, 0, 1).astype(np.float32), cv2.COLOR_BGR2LAB)


def from_lab(lab):
    return cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2BGR)


def neutralise_whites(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(a, b)
    whites = (L > np.percentile(L, 70)) & (chroma < 14)
    if whites.sum() < 500:
        return lab
    da = -np.median(a[whites])
    db = WALL_WARMTH_B - np.median(b[whites])
    # apply the correction more on brighter tones (walls, ceilings) than in shadows
    w = np.clip((L - 20) / 60, 0, 1)
    lab[..., 1] += da * w
    lab[..., 2] += db * w
    return lab


def tone(lab):
    L = lab[..., 0]
    lo, hi = np.percentile(L, [0.5, 99.5])
    L = (L - lo) / max(1e-3, hi - lo)
    L = np.clip(L, 0, 1)
    # gamma to land the median where the references sit
    med = np.median(L)
    target = (TARGET_MEDIAN_L - BLACK_POINT_L) / (WHITE_POINT_L - BLACK_POINT_L)
    g = np.log(target) / np.log(max(1e-3, min(0.999, med)))
    L = L ** np.clip(g, 0.45, 1.6)
    # soft shoulder so whites stay clean but not clipped
    L = BLACK_POINT_L + (WHITE_POINT_L - BLACK_POINT_L) * (L - 0.06 * L * (1 - L))
    lab[..., 0] = L
    return lab


def colour(lab):
    a, b = lab[..., 1], lab[..., 2]
    lab[..., 1] = a * SATURATION
    lab[..., 2] = b * SATURATION
    return lab


def detail(bgr):
    lab = to_lab(bgr)
    L = lab[..., 0]
    big = cv2.GaussianBlur(L, (0, 0), max(L.shape) / 120)
    L = L + CLARITY * (L - big) * (1 - np.abs(L - 50) / 70).clip(0.2, 1)
    small = cv2.GaussianBlur(L, (0, 0), 1.2)
    L = L + SHARPEN * (L - small)
    lab[..., 0] = np.clip(L, 0, 100)
    return from_lab(lab)


def straighten_verticals(bgr):
    """Correct converging verticals (camera tilt) with a keystone warp."""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(np.clip(bgr * 255, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    lsd = cv2.createLineSegmentDetector()
    lines = lsd.detect(gray)[0]
    if lines is None:
        return bgr
    rows = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = x2 - x1, y2 - y1
        length = np.hypot(dx, dy)
        if length < h * 0.08:
            continue
        ang = np.degrees(np.arctan2(abs(dx), abs(dy)))
        if ang > 12:
            continue
        # line as a*x + b*y = c (normalised), weighted by length
        a, b = dy, -dx
        n = np.hypot(a, b)
        rows.append((a / n, b / n, (a * x1 + b * y1) / n, length))
    if len(rows) < 6:
        return bgr
    A = np.array([[r[0], r[1]] for r in rows]) * np.array([[r[3]] for r in rows])
    c = np.array([r[2] * r[3] for r in rows])
    vx, vy = np.linalg.lstsq(A, c, rcond=None)[0]
    if abs(vy) < h * 1.2 or abs(vy) > h * 60:
        return bgr  # nothing meaningful to correct, or would over-correct
    def top_x(xb):
        return xb + (vx - xb) * (h / (h - vy))
    src = np.float32([[top_x(0), 0], [top_x(w), 0], [w, h], [0, h]])
    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(bgr, M, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT)
    # crop away any empty wedges, keep aspect ratio
    spread = max(0.0, max(-src[0][0], src[1][0] - w))
    if spread > 0:
        fx = spread / w
        cx0 = int(w * fx / 2 + w * 0.01); cy0 = int(h * fx / 2 + h * 0.01)
        out = cv2.resize(out[cy0:h - cy0, cx0:w - cx0], (w, h), interpolation=cv2.INTER_LANCZOS4)
    return out


def process(paths, out_path):
    imgs = order_by_brightness([load(p) for p in paths])
    shapes = {i.shape for i in imgs}
    if len(shapes) > 1:
        raise SystemExit(f"Brackets have different sizes: {shapes}")
    imgs = align(imgs) if len(imgs) > 1 else imgs
    fused = fuse(imgs) if len(imgs) > 1 else imgs[0]
    fused = window_pull(fused, imgs)
    lab = to_lab(fused)
    lab = neutralise_whites(lab)
    lab = tone(lab)
    lab = colour(lab)
    out = detail(from_lab(lab))
    out = straighten_verticals(out)
    out8 = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    cv2.imwrite(out_path, out8, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return out_path


def main(argv):
    if len(argv) >= 3 and argv[0] == "--batch":
        src, dst = argv[1], argv[2]
        os.makedirs(dst, exist_ok=True)
        for room in sorted(d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d))):
            files = sorted(glob.glob(os.path.join(src, room, "*")))
            if files:
                print("→", process(files, os.path.join(dst, room + ".jpg")))
        return
    if len(argv) < 2:
        raise SystemExit(__doc__)
    print("→", process(argv[1:], argv[0]))


if __name__ == "__main__":
    main(sys.argv[1:])
