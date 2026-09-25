"""
Generates a layered, editable SVG floor plan for
Lot 22 Catanzariti Drive, Austral (Clover Homes A210004, Rev D)
in the 101 Studios marketing floor-plan style.

Geometry was traced from the builder's ground / first floor plans.
All coordinates below are in *source-drawing pixels* (the PDF page rendered
at 2000px wide) and are converted to millimetres, then to canvas pixels.

Run:  python3 build_floorplan.py   ->  writes floorplan.svg next to this file.
"""
import base64
import math
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# Style tokens (sampled from the 101 Studios reference plans)
# ----------------------------------------------------------------------------
C_LIVING = "#FFEED4"   # living / kitchen / halls / garage
C_BED = "#B0A39A"      # bedrooms
C_WET = "#B6EBF9"      # bathrooms, ensuite, powder, laundry
C_OUTDOOR = "#C7C7C7"  # alfresco, porch, balcony
C_ROBE = "#FFF8EC"     # robes / WIR / linen
C_WALL = "#1A1A1A"
C_TEXT = "#2B2B2B"
C_LINE = "#4A4A4A"

T_EXT = 10.0   # external wall thickness on canvas (px)
T_INT = 5.0    # internal wall thickness on canvas (px)

FONT = "Nunito, 'Nunito Sans', 'Arial Rounded MT Bold', Arial, sans-serif"

CANVAS_W, CANVAS_H = 2000, 1333
SCALE = 0.0605  # canvas px per mm


# ----------------------------------------------------------------------------
# Coordinate systems
# ----------------------------------------------------------------------------
class Floor:
    def __init__(self, x0, x1, y0, y1, width_mm, depth_mm, ox, oy):
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.w, self.d = width_mm, depth_mm
        self.ox, self.oy = ox, oy

    def mm(self, px, py):
        return ((px - self.x0) * self.w / (self.x1 - self.x0),
                (py - self.y0) * self.d / (self.y1 - self.y0))

    def c(self, px, py):
        mx, my = self.mm(px, py)
        return (round(self.ox + mx * SCALE, 2), round(self.oy + my * SCALE, 2))

    def mm_len_x(self, dpx):
        return dpx * self.w / (self.x1 - self.x0)

    def mm_len_y(self, dpx):
        return dpx * self.d / (self.y1 - self.y0)


# outer faces of each floor in the source drawings
GF = Floor(568, 1340, 270, 890, 16660, 13490, ox=125, oy=160)
FF = Floor(783, 1335, 283, 918, 11460, 13490, ox=125 + 16660 * SCALE + 100, oy=160)


# ----------------------------------------------------------------------------
# SVG helpers
# ----------------------------------------------------------------------------
def f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def pts(points):
    return " ".join(f"{f(x)},{f(y)}" for x, y in points)


class Layer:
    def __init__(self, lid, label):
        self.id, self.label, self.items = lid, label, []

    def add(self, s):
        self.items.append(s)

    def render(self, indent="  "):
        inner = "\n".join(indent + "  " + i for i in self.items)
        return (f'{indent}<g id="{self.id}" inkscape:groupmode="layer" '
                f'inkscape:label="{self.label}">\n{inner}\n{indent}</g>')


# ----------------------------------------------------------------------------
# Wall engine: centreline segments with openings cut out
# ----------------------------------------------------------------------------
def build_walls(floor, walls, openings):
    """walls: (x1,y1,x2,y2,kind) in source px (axis aligned).
    openings: list of (a, b) source-px points spanning the gap along a wall.
    Returns canvas rects (x, y, w, h)."""
    rects = []
    cuts = []
    for (a, b) in openings:
        ca, cb = floor.c(*a), floor.c(*b)
        cuts.append((ca, cb))
    for (x1, y1, x2, y2, kind) in walls:
        t = T_EXT if kind == "ext" else T_INT
        (X1, Y1), (X2, Y2) = floor.c(x1, y1), floor.c(x2, y2)
        horiz = abs(Y1 - Y2) < 0.01
        if horiz:
            lo, hi, fixed = min(X1, X2), max(X1, X2), Y1
        else:
            lo, hi, fixed = min(Y1, Y2), max(Y1, Y2), X1
        # intervals to remove
        removed = []
        for (ca, cb) in cuts:
            if horiz and abs(ca[1] - cb[1]) < 0.01 and abs(ca[1] - fixed) <= t:
                removed.append((min(ca[0], cb[0]), max(ca[0], cb[0])))
            if (not horiz) and abs(ca[0] - cb[0]) < 0.01 and abs(ca[0] - fixed) <= t:
                removed.append((min(ca[1], cb[1]), max(ca[1], cb[1])))
        removed.sort()
        pieces = []
        cur, cur_ext = lo, True
        for (r0, r1) in removed:
            if r1 <= lo or r0 >= hi:
                continue
            if r0 > cur:
                pieces.append((cur, r0, cur_ext, False))
            cur, cur_ext = max(cur, r1), False
        if cur < hi:
            pieces.append((cur, hi, cur_ext, True))
        for (p0, p1, e0, e1) in pieces:
            a = p0 - (t / 2 if e0 else 0)
            b = p1 + (t / 2 if e1 else 0)
            if horiz:
                rects.append((a, fixed - t / 2, b - a, t))
            else:
                rects.append((fixed - t / 2, a, t, b - a))
    return rects


def wall_thickness_at(floor, a, b, walls):
    (AX, AY), (BX, BY) = floor.c(*a), floor.c(*b)
    horiz = abs(AY - BY) < 0.01
    for (x1, y1, x2, y2, kind) in walls:
        (X1, Y1), (X2, Y2) = floor.c(x1, y1), floor.c(x2, y2)
        t = T_EXT if kind == "ext" else T_INT
        if horiz and abs(Y1 - Y2) < 0.01 and abs(Y1 - AY) <= t:
            if min(X1, X2) - 1 <= min(AX, BX) and max(AX, BX) <= max(X1, X2) + 1:
                return t, Y1
        if (not horiz) and abs(X1 - X2) < 0.01 and abs(X1 - AX) <= t:
            if min(Y1, Y2) - 1 <= min(AY, BY) and max(AY, BY) <= max(Y1, Y2) + 1:
                return t, X1
    return T_INT, (AY if horiz else AX)


# ----------------------------------------------------------------------------
# Symbols
# ----------------------------------------------------------------------------
def door_svg(floor, hinge, closed, opened, walls):
    H, Cc, O = floor.c(*hinge), floor.c(*closed), floor.c(*opened)
    t, line = wall_thickness_at(floor, hinge, closed, walls)
    r = math.dist(H, Cc)
    # snap hinge/closed onto the wall line so the leaf sits on the jamb
    horiz = abs(H[1] - Cc[1]) < 0.01
    if horiz:
        H = (H[0], line)
        Cc = (Cc[0], line)
    else:
        H = (line, H[1])
        Cc = (line, Cc[1])
    # open end at radius r in the direction of `opened`
    ang = math.atan2(O[1] - H[1], O[0] - H[0])
    O = (H[0] + r * math.cos(ang), H[1] + r * math.sin(ang))
    # sweep flag: cross product sign of (C-H) x (O-H)
    cross = (Cc[0] - H[0]) * (O[1] - H[1]) - (Cc[1] - H[1]) * (O[0] - H[0])
    sweep = 1 if cross > 0 else 0
    return (f'<g class="door"><line x1="{f(H[0])}" y1="{f(H[1])}" x2="{f(O[0])}" y2="{f(O[1])}" '
            f'stroke="{C_WALL}" stroke-width="1.8" stroke-linecap="square"/>'
            f'<path d="M{f(Cc[0])},{f(Cc[1])} A{f(r)},{f(r)} 0 0 {sweep} {f(O[0])},{f(O[1])}" '
            f'fill="none" stroke="{C_LINE}" stroke-width="0.9"/></g>')


def window_svg(floor, a, b, walls):
    A, B = floor.c(*a), floor.c(*b)
    t, line = wall_thickness_at(floor, a, b, walls)
    if abs(A[1] - B[1]) < 0.01:
        x, w = min(A[0], B[0]), abs(A[0] - B[0])
        y = line - t / 2
        return (f'<g class="window"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(t)}" '
                f'fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
                f'<line x1="{f(x)}" y1="{f(line)}" x2="{f(x + w)}" y2="{f(line)}" stroke="{C_LINE}" stroke-width="0.8"/></g>')
    y, h = min(A[1], B[1]), abs(A[1] - B[1])
    x = line - t / 2
    return (f'<g class="window"><rect x="{f(x)}" y="{f(y)}" width="{f(t)}" height="{f(h)}" '
            f'fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<line x1="{f(line)}" y1="{f(y)}" x2="{f(line)}" y2="{f(y + h)}" stroke="{C_LINE}" stroke-width="0.8"/></g>')


def slider_svg(floor, a, b, walls, panels=2):
    """Sliding / stacking door: offset thin panels inside the opening."""
    A, B = floor.c(*a), floor.c(*b)
    t, line = wall_thickness_at(floor, a, b, walls)
    out = ['<g class="sliding-door">']
    horiz = abs(A[1] - B[1]) < 0.01
    lo, hi = (min(A[0], B[0]), max(A[0], B[0])) if horiz else (min(A[1], B[1]), max(A[1], B[1]))
    # white backing so the gap reads clean
    if horiz:
        out.append(f'<rect x="{f(lo)}" y="{f(line - t / 2)}" width="{f(hi - lo)}" height="{f(t)}" fill="#FFFFFF"/>')
    else:
        out.append(f'<rect x="{f(line - t / 2)}" y="{f(lo)}" width="{f(t)}" height="{f(hi - lo)}" fill="#FFFFFF"/>')
    seg = (hi - lo) / panels
    for i in range(panels):
        s0 = lo + i * seg - (2 if i else 0)
        s1 = lo + (i + 1) * seg + (2 if i < panels - 1 else 0)
        off = (-1.4 if i % 2 == 0 else 1.4)
        if horiz:
            out.append(f'<rect x="{f(s0)}" y="{f(line + off - 1)}" width="{f(s1 - s0)}" height="2" '
                       f'fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>')
        else:
            out.append(f'<rect x="{f(line + off - 1)}" y="{f(s0)}" width="2" height="{f(s1 - s0)}" '
                       f'fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>')
    out.append("</g>")
    return "".join(out)


def garage_door_svg(floor, a, b, walls):
    A, B = floor.c(*a), floor.c(*b)
    t, line = wall_thickness_at(floor, a, b, walls)
    y0, y1 = min(A[1], B[1]), max(A[1], B[1])
    return (f'<g class="garage-door"><rect x="{f(line - t / 2)}" y="{f(y0)}" width="{f(t)}" height="{f(y1 - y0)}" '
            f'fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<line x1="{f(line - 1.5)}" y1="{f(y0)}" x2="{f(line - 1.5)}" y2="{f(y1)}" stroke="{C_LINE}" stroke-width="0.6"/>'
            f'<line x1="{f(line + 1.5)}" y1="{f(y0)}" x2="{f(line + 1.5)}" y2="{f(y1)}" stroke="{C_LINE}" stroke-width="0.6"/></g>')


def rect_c(floor, x0, y0, x1, y1):
    A, B = floor.c(x0, y0), floor.c(x1, y1)
    return A[0], A[1], B[0] - A[0], B[1] - A[1]


def box(floor, x0, y0, x1, y1, fill="#FFFFFF", stroke=C_LINE, sw=0.8, rx=0, cls="joinery"):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    r = f' rx="{f(rx)}"' if rx else ""
    return (f'<rect class="{cls}" x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}"{r} '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def shower(floor, x0, y0, x1, y1):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    return (f'<g class="shower"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="#FFFFFF" '
            f'stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<line x1="{f(x)}" y1="{f(y)}" x2="{f(x + w)}" y2="{f(y + h)}" stroke="{C_LINE}" stroke-width="0.6"/>'
            f'<line x1="{f(x + w)}" y1="{f(y)}" x2="{f(x)}" y2="{f(y + h)}" stroke="{C_LINE}" stroke-width="0.6"/></g>')


def toilet(floor, cx, cy, facing):
    """facing = direction the bowl points: 'up','down','left','right'."""
    X, Y = floor.c(cx, cy)
    rot = {"up": 0, "right": 90, "down": 180, "left": 270}[facing]
    return (f'<g class="toilet" transform="translate({f(X)},{f(Y)}) rotate({rot})">'
            f'<rect x="-6" y="5" width="12" height="4.5" rx="1" fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<ellipse cx="0" cy="-1" rx="5" ry="6.5" fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<ellipse cx="0" cy="-1.5" rx="3" ry="4.2" fill="none" stroke="{C_LINE}" stroke-width="0.6"/></g>')


def basin(floor, cx, cy, rot=0):
    X, Y = floor.c(cx, cy)
    return (f'<g class="basin" transform="translate({f(X)},{f(Y)}) rotate({rot})">'
            f'<rect x="-6" y="-5" width="12" height="10" rx="2.5" fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<circle cx="0" cy="0.5" r="1.3" fill="none" stroke="{C_LINE}" stroke-width="0.6"/></g>')


def bathtub(floor, x0, y0, x1, y1):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    return (f'<g class="bathtub"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(h / 2)}" '
            f'fill="#FFFFFF" stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<rect x="{f(x + 3)}" y="{f(y + 3)}" width="{f(w - 6)}" height="{f(h - 6)}" rx="{f((h - 6) / 2)}" '
            f'fill="none" stroke="{C_LINE}" stroke-width="0.6"/></g>')


def cooktop(floor, x0, y0, x1, y1):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    out = [f'<g class="cooktop"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="#FFFFFF" '
           f'stroke="{C_LINE}" stroke-width="0.8"/>']
    for i in (0.3, 0.7):
        for j in (0.28, 0.72):
            out.append(f'<circle cx="{f(x + w * i)}" cy="{f(y + h * j)}" r="{f(min(w, h) * 0.16)}" '
                       f'fill="none" stroke="{C_LINE}" stroke-width="0.7"/>')
    out.append("</g>")
    return "".join(out)


def sink(floor, x0, y0, x1, y1):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    return (f'<g class="sink"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="1.5" fill="#FFFFFF" '
            f'stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<circle cx="{f(x + w / 2)}" cy="{f(y + h / 2)}" r="1.2" fill="none" stroke="{C_LINE}" stroke-width="0.6"/></g>')


def washer(floor, x0, y0, x1, y1):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    return (f'<g class="appliance"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="#FFFFFF" '
            f'stroke="{C_LINE}" stroke-width="0.8"/>'
            f'<circle cx="{f(x + w / 2)}" cy="{f(y + h / 2)}" r="{f(min(w, h) * 0.32)}" fill="none" '
            f'stroke="{C_LINE}" stroke-width="0.7"/></g>')


def stairs(floor, x0, y0, x1, y1, risers, up_dir="left"):
    x, y, w, h = rect_c(floor, x0, y0, x1, y1)
    out = [f'<g class="stairs"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="#FFFFFF" '
           f'stroke="{C_LINE}" stroke-width="0.9"/>']
    for i in range(1, risers):
        xi = x + w * i / risers
        out.append(f'<line x1="{f(xi)}" y1="{f(y)}" x2="{f(xi)}" y2="{f(y + h)}" stroke="{C_LINE}" stroke-width="0.7"/>')
    cy = y + h / 2
    if up_dir == "left":
        xs, xe = x + w - 6, x + 8
        head = f'{f(xe)},{f(cy)} {f(xe + 6)},{f(cy - 3.5)} {f(xe + 6)},{f(cy + 3.5)}'
    else:
        xs, xe = x + 6, x + w - 8
        head = f'{f(xe)},{f(cy)} {f(xe - 6)},{f(cy - 3.5)} {f(xe - 6)},{f(cy + 3.5)}'
    out.append(f'<line x1="{f(xs)}" y1="{f(cy)}" x2="{f(xe)}" y2="{f(cy)}" stroke="{C_WALL}" stroke-width="1"/>')
    out.append(f'<polygon points="{head}" fill="{C_WALL}"/>')
    out.append("</g>")
    return "".join(out)


def car(cx, cy, length, width, rot=0, body="#FFFFFF"):
    """Simple top-down car, nose pointing +x before rotation."""
    L, W = length, width
    return (f'<g class="car" transform="translate({f(cx)},{f(cy)}) rotate({rot})">'
            f'<rect x="{f(-L / 2)}" y="{f(-W / 2)}" width="{f(L)}" height="{f(W)}" rx="{f(W * 0.32)}" '
            f'fill="{body}" stroke="#8A8A8A" stroke-width="0.9"/>'
            f'<rect x="{f(-L * 0.02)}" y="{f(-W * 0.40)}" width="{f(L * 0.2)}" height="{f(W * 0.80)}" rx="3" fill="#2E3A44"/>'
            f'<rect x="{f(-L * 0.36)}" y="{f(-W * 0.36)}" width="{f(L * 0.12)}" height="{f(W * 0.72)}" rx="3" fill="#2E3A44"/>'
            f'<rect x="{f(-L * 0.24)}" y="{f(-W * 0.38)}" width="{f(L * 0.22)}" height="{f(W * 0.76)}" rx="2" '
            f'fill="{body}" stroke="#B5B5B5" stroke-width="0.6"/>'
            f'<rect x="{f(L * 0.06)}" y="{f(-W / 2 - 2.5)}" width="4" height="3" rx="1" fill="#8A8A8A"/>'
            f'<rect x="{f(L * 0.06)}" y="{f(W / 2 - 0.5)}" width="4" height="3" rx="1" fill="#8A8A8A"/>'
            f'<rect x="{f(L / 2 - 3)}" y="{f(-W * 0.38)}" width="2" height="{f(W * 0.18)}" rx="1" fill="#E7C66A"/>'
            f'<rect x="{f(L / 2 - 3)}" y="{f(W * 0.20)}" width="2" height="{f(W * 0.18)}" rx="1" fill="#E7C66A"/>'
            f'<rect x="{f(-L / 2 + 1)}" y="{f(-W * 0.38)}" width="2" height="{f(W * 0.16)}" rx="1" fill="#D9534F"/>'
            f'<rect x="{f(-L / 2 + 1)}" y="{f(W * 0.22)}" width="2" height="{f(W * 0.16)}" rx="1" fill="#D9534F"/>'
            f'</g>')


def label(floor, px, py, name, dims=None, size=14, rot=0):
    X, Y = floor.c(px, py)
    lines = name.split("\n")
    total = len(lines) + (1 if dims else 0)
    lh = size + 4
    y_start = -(total - 1) * lh / 2
    out = [f'<g class="room-label" transform="translate({f(X)},{f(Y)}) rotate({rot})" font-family="{FONT}" '
           f'fill="{C_TEXT}" text-anchor="middle" letter-spacing="0.3">']
    for i, ln in enumerate(lines):
        out.append(f'<text x="0" y="{f(y_start + i * lh + size * 0.36)}" font-size="{size}" font-weight="700">{ln}</text>')
    if dims:
        out.append(f'<text x="0" y="{f(y_start + len(lines) * lh + size * 0.36)}" font-size="{size - 1}" font-weight="700">{dims}</text>')
    out.append("</g>")
    return "".join(out)


def poly(floor, points, fill, cls="room", stroke="none"):
    return (f'<polygon class="{cls}" points="{pts([floor.c(*p) for p in points])}" fill="{fill}" '
            f'stroke="{stroke}"/>')


# ============================================================================
# GROUND FLOOR  (source: Clover Homes DRWG 3 rev D)
# ============================================================================
g = GF
g_walls = [
    # external (outer face + 5.5px = centreline)
    (573.5, 275.5, 1015, 275.5, "ext"),        # north wall, rumpus -> laundry
    (1015, 275.5, 1282.5, 275.5, "ext"),       # north wall, garage
    (573.5, 275.5, 573.5, 691.5, "ext"),       # west wall
    (573.5, 691.5, 808.5, 691.5, "ext"),       # family / alfresco wall
    (808.5, 691.5, 808.5, 884.5, "ext"),       # dining / alfresco wall
    (808.5, 884.5, 1334.5, 884.5, "ext"),      # south wall
    (1334.5, 884.5, 1334.5, 712, "ext"),       # east wall, guest bed
    (1334.5, 712, 1271, 712, "ext"),           # guest bed north (under porch)
    (1271, 712, 1271, 548, "ext"),             # entry east wall (porch)
    (1015, 548, 1282.5, 548, "ext"),           # garage south wall
    (1282.5, 275.5, 1282.5, 548, "ext"),       # garage east wall (panel lift door)
    (1015, 275.5, 1015, 548, "ext"),           # garage west wall
    # internal
    (573.5, 457, 783, 457, "int"),             # rumpus / family
    (783, 275.5, 783, 457, "int"),             # rumpus / butlers pantry
    (783, 455, 816, 455, "int"),               # pantry south stub
    (882, 275.5, 882, 370, "int"),             # pantry / laundry
    (882, 370, 1015, 370, "int"),              # laundry south
    (915, 370, 915, 457, "int"),               # pantry / passage
    (858, 418, 858, 455, "int"),               # fridge nook
    (858, 418, 915, 418, "int"),               # fridge nook head
    (960, 457, 1015, 457, "int"),              # passage south (above bench)
    (960, 370, 960, 410, "int"),               # linen west
    (960, 410, 1015, 410, "int"),              # linen south
    (1015, 548, 1015, 652, "int"),             # kitchen back wall (study side)
    (973, 705, 973, 884.5, "int"),             # dining / powder
    (1025, 705, 1025, 884.5, "int"),           # powder / WIR+ens
    (1025, 705, 1148, 705, "int"),             # WIR north
    (973, 790, 1025, 790, "int"),              # powder WC partition
    (1025, 790, 1148, 790, "int"),             # WIR / ensuite
    (1148, 705, 1148, 884.5, "int"),           # guest bed west
    (1148, 712, 1271, 712, "int"),             # entry / guest bed
]

g_doors = [
    # (hinge, closed-end, open-direction point)
    ((778, 457), (736, 457), (778, 415)),        # rumpus 920 glass door
    ((922, 281), (960, 281), (922, 319)),        # laundry external door
    ((922, 370), (960, 370), (922, 332)),        # laundry door off passage
    ((915, 413), (915, 381), (883, 413)),        # butlers pantry -> passage 720
    ((1005, 410), (972, 410), (980, 432)),       # linen 720
    ((1015, 452), (1015, 413), (976, 452)),      # garage -> house 820
    ((977, 790), (1017, 790), (977, 830)),       # powder WC 820
    ((1148, 748), (1148, 784), (1112, 748)),     # guest WIR 720
    ((1148, 832), (1148, 796), (1112, 832)),     # guest ensuite 720
    ((1152, 712), (1190, 712), (1152, 752)),     # guest bedroom 820
    ((1271, 702), (1271, 648), (1217, 702)),     # front entry 1200
]
g_open = [  # square-set openings (no door leaf)
    ((816, 455), (858, 455)),                   # pantry -> kitchen (2400H bulkhead)
    ((918, 457), (960, 457)),                   # passage -> kitchen (2400H SQ. SET)
]
g_windows = [
    ((573.5, 297), (573.5, 441)),     # ASW1530 rumpus
    ((573.5, 479), (573.5, 524)),     # AAW1810T family
    ((573.5, 622), (573.5, 667)),     # AAW1810T family
    ((812, 275.5), (880, 275.5)),     # ASW1315 butlers pantry
    ((858, 884.5), (942, 884.5)),     # ASW1818T dining
    ((988, 884.5), (1015, 884.5)),    # ASW1206 powder
    ((1080, 884.5), (1108, 884.5)),   # ASW1206 ensuite
    ((1334.5, 762), (1334.5, 845)),   # ASW1818T guest bed
    ((1271, 556), (1271, 612)),       # AFW1512SP entry sidelight
]
g_sliders = [
    ((633, 691.5), (800, 691.5)),     # AST2436 family -> alfresco
    ((808.5, 708), (808.5, 848)),     # AST2430 dining -> alfresco
]
g_garage = [((1282.5, 300), (1282.5, 524))]  # panel lift door 4810 wide

# ============================================================================
# FIRST FLOOR  (source: Clover Homes DRWG 4 rev D)
# ============================================================================
ff = FF
f_walls = [
    (788, 288, 1271, 288, "ext"),               # north
    (788, 288, 788, 913, "ext"),                # west
    (788, 913, 1330, 913, "ext"),               # south
    (1330, 913, 1330, 744, "ext"),              # lounge east
    (1330, 744, 1271, 744, "ext"),              # lounge / balcony
    (1271, 744, 1271, 288, "ext"),              # east (bed 1 / ensuite / balcony)
    # internal
    (788, 450, 940, 450, "int"),                # bed 4 south
    (940, 288, 940, 913, "int"),                # bedrooms east spine
    (862, 450, 862, 518, "int"),                # WIR / linen
    (788, 518, 940, 518, "int"),                # linen / bed 3
    (788, 688, 940, 688, "int"),                # bed 3 / WIRs
    (860, 688, 860, 760, "int"),                # WIR / WIR
    (788, 760, 940, 760, "int"),                # WIRs / bed 2
    (940, 386, 1105, 386, "int"),               # master WIR south
    (1105, 288, 1105, 388, "int"),              # master WIR / ensuite
    (1105, 388, 1271, 388, "int"),              # ensuite south
    (1000, 386, 1000, 565, "int"),              # hall / master
    (1000, 565, 1271, 565, "int"),              # master south / stair
    (1105, 335, 1188, 335, "int"),              # ensuite WC / shower head wall
    (1135, 335, 1135, 388, "int"),              # ensuite shower west
    (940, 818, 990, 818, "int"),                # bath north-west
    (990, 818, 990, 757, "int"),                # bath notch
    (990, 757, 1085, 757, "int"),               # bath north
    (1085, 757, 1085, 913, "int"),              # bath / lounge
]
f_doors = [
    ((940, 445), (940, 405), (900, 445)),        # bed 4 820
    ((940, 455), (940, 490), (905, 455)),        # linen 720
    ((940, 650), (940, 688), (902, 650)),        # bed 3 820
    ((940, 768), (940, 807), (901, 768)),        # bed 2 820
    ((945, 818), (985, 818), (945, 856)),        # bathroom 820
    ((1000, 556), (1000, 518), (1038, 556)),     # master bedroom 820
    ((1188, 331), (1188, 296), (1153, 331)),     # ensuite WC 720
    ((1283, 744), (1321, 744), (1283, 706)),     # lounge -> balcony 820
]
f_open = [
    ((822, 450), (862, 450)),                   # bed 4 WIR (2150H sq. set)
    ((862, 688), (900, 688)),                   # bed 3 WIR
    ((822, 760), (860, 760)),                   # bed 2 WIR
    ((1195, 388), (1233, 388)),                 # ensuite (2150H sq. set)
]
f_csd = [((1050, 386), (1090, 386))]            # master WIR 820 cavity slider
f_windows = [
    ((788, 333), (788, 407)),         # ASW1215 bed 4
    ((788, 551), (788, 650)),         # ASW0621 bed 3
    ((788, 794), (788, 868)),         # ASW1215 bed 2
    ((1113, 288), (1141, 288)),       # ASW1206 obscure (ensuite WC)
    ((1200, 288), (1235, 288)),       # AAW1208 obscure (ensuite)
    ((1271, 300), (1271, 385)),       # AFW0418 ensuite
    ((1271, 432), (1271, 555)),       # AAW1224 master
    ((1271, 582), (1271, 732)),       # AFW1232 stair / balcony
    ((1330, 785), (1330, 870)),       # ASW1818T lounge
    ((952, 913), (1004, 913)),        # ASW1212 obscure bath
    ((1112, 913), (1225, 913)),       # AFW0624 lounge
]


# ----------------------------------------------------------------------------
# Assemble a floor
# ----------------------------------------------------------------------------
def floor_layers(prefix, title, floor, walls, doors, openings, windows, sliders=(), garage=(), csd=()):
    L = {k: Layer(f"{prefix}-{k}", f"{title} · {k.replace('-', ' ').title()}") for k in
         ["outdoor", "room-fills", "joinery-fixtures", "stairs", "walls", "windows", "doors", "labels"]}
    cut = [(d[0], d[1]) for d in doors] + list(openings) + list(windows) + list(sliders) + list(garage) + list(csd)
    for (x, y, w, h) in build_walls(floor, walls, cut):
        L["walls"].add(f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="{C_WALL}"/>')
    for (hinge, closed, opened) in doors:
        L["doors"].add(door_svg(floor, hinge, closed, opened, walls))
    for (a, b) in sliders:
        L["doors"].add(slider_svg(floor, a, b, walls))
    for (a, b) in csd:
        L["doors"].add(slider_svg(floor, a, b, walls, panels=1))
    for (a, b) in garage:
        L["doors"].add(garage_door_svg(floor, a, b, walls))
    for (a, b) in windows:
        L["windows"].add(window_svg(floor, a, b, walls))
    return L


gl = floor_layers("gf", "Ground Floor", g, g_walls, g_doors, g_open, g_windows, g_sliders, g_garage)
fl = floor_layers("ff", "First Floor", ff, f_walls, f_doors, f_open, f_windows, csd=f_csd)

# ---- Ground: outdoor -------------------------------------------------------
gl["outdoor"].add(poly(g, [(568, 691.5), (808.5, 691.5), (808.5, 890), (568, 890)], C_OUTDOOR, "outdoor"))
gl["outdoor"].add(poly(g, [(1271, 540), (1340, 540), (1340, 712), (1271, 712)], C_OUTDOOR, "outdoor"))
# alfresco piers + porch posts
for r in [(568, 855, 584, 890), (794, 855, 808.5, 890), (1329, 540, 1340, 551), (1329, 701, 1340, 712)]:
    gl["walls"].add(box(g, *r, fill=C_WALL, stroke="none", cls="post"))
# pre-cast concrete steps up to the alfresco
x, y, w, h = rect_c(g, 526, 728, 568, 852)
steps = [f'<g class="steps"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" fill="#DADADA" '
         f'stroke="{C_LINE}" stroke-width="0.8"/>']
for i in range(1, 4):
    xi = x + w * i / 4
    steps.append(f'<line x1="{f(xi)}" y1="{f(y)}" x2="{f(xi)}" y2="{f(y + h)}" stroke="{C_LINE}" stroke-width="0.7"/>')
steps.append("</g>")
gl["outdoor"].add("".join(steps))

# ---- Ground: room fills ----------------------------------------------------
gl["room-fills"].add(poly(g, [(573.5, 275.5), (1282.5, 275.5), (1282.5, 548), (1271, 548), (1271, 712),
                              (1334.5, 712), (1334.5, 884.5), (808.5, 884.5), (808.5, 691.5), (573.5, 691.5)],
                          C_LIVING, "floor-base"))
gl["room-fills"].add(poly(g, [(882, 275.5), (1015, 275.5), (1015, 370), (882, 370)], C_WET))            # laundry
gl["room-fills"].add(poly(g, [(960, 370), (1015, 370), (1015, 410), (960, 410)], C_ROBE))               # linen
gl["room-fills"].add(poly(g, [(973, 705), (1025, 705), (1025, 884.5), (973, 884.5)], C_WET))            # powder
gl["room-fills"].add(poly(g, [(1025, 705), (1148, 705), (1148, 790), (1025, 790)], C_ROBE))             # WIR
gl["room-fills"].add(poly(g, [(1025, 790), (1148, 790), (1148, 884.5), (1025, 884.5)], C_WET))          # ensuite
gl["room-fills"].add(poly(g, [(1148, 712), (1334.5, 712), (1334.5, 884.5), (1148, 884.5)], C_BED))      # guest

# ---- Ground: joinery & fixtures -------------------------------------------
J = gl["joinery-fixtures"]
J.add(box(g, 786, 279, 806, 364))                 # pantry tall cupboard
J.add(box(g, 786, 367, 806, 411))                 # pantry shelves
J.add(box(g, 809, 279, 879, 299))                 # pantry back bench
J.add(sink(g, 836, 282, 856, 296))
J.add(box(g, 809, 299, 830, 408))                 # pantry side bench
J.add(box(g, 885, 279, 918, 368))                 # laundry tall cupboard (2300x1940)
J.add(washer(g, 988, 279, 1012, 312))             # washing machine
J.add(box(g, 988, 316, 1012, 346))                # laundry bench
J.add(sink(g, 991, 320, 1009, 342))               # laundry tub
J.add(box(g, 988, 349, 1012, 368))                # linen chute
J.add(box(g, 861, 421, 912, 453))                 # fridge space
J.add(box(g, 866, 522, 925, 645))                 # island (2660 long)
J.add(sink(g, 884, 552, 908, 578))                # island sink
J.add(box(g, 985, 460, 1012, 652))                # back bench
J.add(cooktop(g, 988, 541, 1010, 571))            # cooktop
J.add(box(g, 1028, 708, 1145, 716))               # WIR shelf + rail
J.add(toilet(g, 999, 866, "up"))                  # powder WC
J.add(box(g, 1049, 794, 1080, 822))               # ensuite vanity
J.add(basin(g, 1064, 808))
J.add(shower(g, 1028, 838, 1066, 881))            # ensuite shower 900x950
J.add(toilet(g, 1133, 858, "left"))               # ensuite WC

# garage cars (door on the east wall, cars nose-in facing east)
c1 = g.c(1150, 345)
c2 = g.c(1150, 480)
car_len, car_w = 4600 * SCALE, 1850 * SCALE
J.add(car(c1[0], c1[1], car_len, car_w, 0, "#FFFFFF"))
J.add(car(c2[0], c2[1], car_len, car_w, 0, "#D9D9D9"))

gl["stairs"].add(stairs(g, 1043, 550, 1262, 592, 17, "left"))

# ---- Ground: labels --------------------------------------------------------
GL = gl["labels"]
GL.add(label(g, 678, 369, "RUMPUS", "4.4 M X 3.8 M"))
GL.add(label(g, 856, 352, "BUTLERS\nPANTRY", size=11))
GL.add(label(g, 953, 318, "LAUNDRY", size=11))
GL.add(label(g, 987, 391, "LIN", size=10))
GL.add(label(g, 1150, 412, "GARAGE", "5.5 M X 5.7 M"))
GL.add(label(g, 690, 575, "FAMILY", "4.9 M X 5.0 M"))
GL.add(label(g, 930, 492, "KITCHEN", "4.4 M X 4.2 M"))
GL.add(label(g, 890, 770, "DINING", "3.6 M X 3.8 M"))
GL.add(label(g, 1080, 622, "STUDY"))
GL.add(label(g, 1190, 628, "ENTRY"))
GL.add(label(g, 999, 745, "PWR", size=11))
GL.add(label(g, 1080, 752, "W.I.R", size=11))
GL.add(label(g, 1090, 855, "ENS", size=11))
GL.add(label(g, 1242, 798, "GUEST BEDROOM", "3.9 M X 3.6 M"))
GL.add(label(g, 688, 790, "ALFRESCO", "5.0 M X 4.1 M"))
GL.add(label(g, 1306, 626, "PORCH", size=12, rot=-90))

# ---- First: outdoor --------------------------------------------------------
fl["outdoor"].add(poly(ff, [(1276, 572), (1335, 572), (1335, 744), (1276, 744)], C_OUTDOOR, "outdoor"))
for seg in [((1271, 576), (1331, 576)), ((1331, 576), (1331, 744))]:
    (ax, ay), (bx, by) = ff.c(*seg[0]), ff.c(*seg[1])
    fl["walls"].add(f'<line class="balustrade" x1="{f(ax)}" y1="{f(ay)}" x2="{f(bx)}" y2="{f(by)}" '
                    f'stroke="{C_WALL}" stroke-width="3" stroke-linecap="square"/>')

# ---- First: room fills -----------------------------------------------------
fl["room-fills"].add(poly(ff, [(788, 288), (1271, 288), (1271, 744), (1330, 744), (1330, 913), (788, 913)],
                          C_LIVING, "floor-base"))
F = fl["room-fills"]
F.add(poly(ff, [(788, 288), (940, 288), (940, 450), (788, 450)], C_BED))            # bed 4
F.add(poly(ff, [(788, 450), (862, 450), (862, 518), (788, 518)], C_ROBE))           # WIR
F.add(poly(ff, [(862, 450), (940, 450), (940, 518), (862, 518)], C_ROBE))           # linen
F.add(poly(ff, [(788, 518), (940, 518), (940, 688), (788, 688)], C_BED))            # bed 3
F.add(poly(ff, [(788, 688), (940, 688), (940, 760), (788, 760)], C_ROBE))           # WIRs
F.add(poly(ff, [(788, 760), (940, 760), (940, 913), (788, 913)], C_BED))            # bed 2
F.add(poly(ff, [(940, 818), (990, 818), (990, 757), (1085, 757), (1085, 913), (940, 913)], C_WET))  # bath
F.add(poly(ff, [(940, 288), (1105, 288), (1105, 386), (940, 386)], C_ROBE))         # master WIR
F.add(poly(ff, [(1105, 288), (1271, 288), (1271, 388), (1105, 388)], C_WET))        # ensuite
F.add(poly(ff, [(1000, 386), (1271, 386), (1271, 565), (1000, 565)], C_BED))        # master
F.add(poly(ff, [(1118, 610), (1271, 610), (1271, 742), (1118, 742)], "#FFFFFF", "void"))

# void balustrades
for seg in [((1036, 610), (1118, 610)), ((1118, 610), (1118, 742)), ((1118, 742), (1271, 742))]:
    (ax, ay), (bx, by) = ff.c(*seg[0]), ff.c(*seg[1])
    fl["walls"].add(f'<line class="balustrade" x1="{f(ax)}" y1="{f(ay)}" x2="{f(bx)}" y2="{f(by)}" '
                    f'stroke="{C_WALL}" stroke-width="2.2" stroke-linecap="square"/>')

# ---- First: joinery & fixtures --------------------------------------------
J = fl["joinery-fixtures"]
J.add(box(ff, 791, 453, 806, 516))                  # bed 4 WIR shelf
J.add(box(ff, 944, 291, 1102, 300))                 # master WIR shelf + rail
J.add(box(ff, 944, 357, 966, 383))                  # ACD
J.add(box(ff, 969, 357, 996, 383))                  # chute
J.add(box(ff, 791, 691, 857, 700))                  # bed 2 WIR shelf
J.add(box(ff, 791, 700, 800, 757))
J.add(box(ff, 928, 691, 937, 740))                  # bed 3 WIR shelf
J.add(box(ff, 863, 740, 925, 757))
J.add(toilet(ff, 1122, 311, "right"))               # ensuite WC
J.add(shower(ff, 1138, 338, 1186, 385))             # ensuite shower 1160x1060
J.add(box(ff, 1242, 291, 1268, 385))                # ensuite double vanity
J.add(basin(ff, 1255, 313, 90))
J.add(basin(ff, 1255, 362, 90))
J.add(shower(ff, 993, 760, 1062, 800))              # bath shower 900x1310
J.add(box(ff, 1065, 760, 1082, 800))                # ACD
J.add(box(ff, 1062, 808, 1082, 878))                # bath vanity 1500
J.add(basin(ff, 1072, 825, 90))
J.add(basin(ff, 1072, 858, 90))
J.add(toilet(ff, 1070, 896, "left"))                # bath WC
J.add(bathtub(ff, 948, 868, 1012, 906))             # 1500 free-standing bath

fl["stairs"].add(stairs(ff, 1036, 568, 1262, 610, 17, "left"))

# ---- First: labels ---------------------------------------------------------
FLb = fl["labels"]
FLb.add(label(ff, 864, 372, "BEDROOM 4", "3.1 M X 3.2 M"))
FLb.add(label(ff, 830, 488, "W.I.R", size=10))
FLb.add(label(ff, 901, 488, "LINEN", size=10))
FLb.add(label(ff, 864, 606, "BEDROOM 3", "3.1 M X 3.2 M"))
FLb.add(label(ff, 828, 728, "W.I.R", size=10))
FLb.add(label(ff, 895, 718, "W.I.R", size=10))
FLb.add(label(ff, 864, 842, "BEDROOM 2", "3.1 M X 3.2 M"))
FLb.add(label(ff, 1040, 840, "BATH", size=13))
FLb.add(label(ff, 1022, 340, "W.I.R", size=11))
FLb.add(label(ff, 1212, 350, "ENSUITE", size=11, rot=-90))
FLb.add(label(ff, 1135, 478, "MASTER BEDROOM", "5.4 M X 3.5 M"))
FLb.add(label(ff, 1205, 832, "LOUNGE", "4.9 M X 3.3 M"))
FLb.add(label(ff, 1195, 680, "VOID", size=12))
FLb.add(label(ff, 1303, 660, "BALCONY", size=12, rot=-90))
FLb.add(label(ff, 970, 470, "HALL", size=11, rot=-90))

# ============================================================================
# Page furniture (floor titles, address, disclaimer, compass, logo slot)
# ============================================================================
page = Layer("page", "Page · Titles, Footer, Compass, Logo")
gx, gy = GF.c(568, 890)
page.add(f'<text x="{f(gx)}" y="{f(gy + 38)}" font-size="14" font-weight="700" text-anchor="start" '
         f'font-family="{FONT}" fill="{C_TEXT}" letter-spacing="0.5">GROUND FLOOR</text>')
fx, fy = FF.c(783, 918)
page.add(f'<text x="{f(fx)}" y="{f(fy + 38)}" font-size="14" font-weight="700" text-anchor="start" '
         f'font-family="{FONT}" fill="{C_TEXT}" letter-spacing="0.5">FIRST FLOOR</text>')

page.add('<text id="address" x="62" y="1213" font-family="Arial, Helvetica, sans-serif" font-size="38" '
         'fill="#595959" text-anchor="start" font-weight="400">Lot 22 Catanzariti Drive, Austral NSW 2179</text>')
page.add('<rect x="62" y="1222" width="863" height="3" fill="#1A1A1A"/>')
page.add('<text id="disclaimer" font-family="Arial, Helvetica, sans-serif" font-size="17.5" fill="#595959" '
         'text-anchor="start" font-weight="400">'
         '<tspan x="62" y="1255">Floor plan prepared by <tspan font-weight="700" fill="#1A1A1A">101 STUDIOS</tspan>'
         ' — All measurements and</tspan>'
         '<tspan x="62" y="1278">dimensions are approximate. This floor plan is not to scale and</tspan>'
         '<tspan x="62" y="1301">is intended for illustrative purposes only.</tspan></text>')

# compass (rotate the inner group to set true north; currently plan-north = up)
page.add('<g id="compass" transform="translate(1376,1222)">'
         '<circle r="58" fill="none" stroke="#4D4D4D" stroke-width="5"/>'
         '<g id="compass-needle" transform="rotate(0)">'
         '<polygon points="0,-72 -11,6 0,-4" fill="#4D4D4D"/>'
         '<polygon points="0,-72 11,6 0,-4" fill="#8C8C8C"/>'
         '<text x="0" y="50" font-family="Georgia, \'Times New Roman\', serif" font-size="26" fill="#4D4D4D" '
         'text-anchor="middle" font-weight="700">N</text></g></g>')

# agency logo placeholder
page.add('<g id="agency-logo-placeholder">'
         '<rect x="1650" y="1175" width="300" height="100" fill="none" stroke="#BDBDBD" stroke-width="1.5" '
         'stroke-dasharray="6 5"/>'
         '<text x="1800" y="1231" font-family="Arial, Helvetica, sans-serif" font-size="16" fill="#9E9E9E" '
         'text-anchor="middle">AGENCY LOGO</text></g>')


# ============================================================================
# Write SVG
# ============================================================================
# Nunito (SIL Open Font License) embedded so browsers / previews render the house style.
# Design apps use the installed font of the same name.
with open(os.path.join(OUT_DIR, "Nunito-latin.woff2"), "rb") as fh:
    FONT_B64 = base64.b64encode(fh.read()).decode()


def floor_group(gid, label_, layers):
    order = ["outdoor", "room-fills", "joinery-fixtures", "stairs", "walls", "windows", "doors", "labels"]
    inner = "\n".join(layers[k].render("    ") for k in order)
    return (f'  <g id="{gid}" inkscape:groupmode="layer" inkscape:label="{label_}">\n{inner}\n  </g>')


svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}">
  <title>Lot 22 Catanzariti Drive, Austral – Floor Plan</title>
  <defs>
    <style>
      @font-face {{ font-family: 'Nunito'; font-weight: 600 700; src: url(data:font/woff2;base64,{FONT_B64}) format('woff2'); }}
    </style>
  </defs>
  <rect id="background" width="{CANVAS_W}" height="{CANVAS_H}" fill="#FFFFFF"/>
{floor_group("ground-floor", "Ground Floor", gl)}
{floor_group("first-floor", "First Floor", fl)}
{page.render("  ")}
</svg>
'''

out_path = os.path.join(OUT_DIR, "floorplan.svg")
with open(out_path, "w") as fh:
    fh.write(svg)
print("wrote", out_path)
