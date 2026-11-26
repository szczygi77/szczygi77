#!/usr/bin/env python3
"""SZCZYGI77 / DIGITAL CITY

Renders the GitHub contribution calendar as an animated, monochrome,
isometric night city (pure SVG + SMIL, standard library only).

Every day is one city block, the building height follows the number of
contributions that day.

Data source:
  1. GitHub GraphQL API (when GITHUB_TOKEN is set) - exact counts.
  2. Fallback: public contributions HTML calendar.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
import re
import sys
import urllib.request
from pathlib import Path

USER = os.environ.get("CITY_USER", "szczygi77")
OUT = Path(os.environ.get("CITY_OUT", "dist/contribution-city.svg"))

WIDTH, HEIGHT = 1200, 740
WEEKS, DAYS = 53, 7

# Oblique "isometric" axes: one step along a week / along a weekday.
UX, UY = 18.5, 4.6     # week axis -> right, slightly down
VX, VY = -12.0, 7.6    # day axis  -> left, down
GAP = 0.15             # street width (fraction of a cell)
MAX_H = 150.0          # tallest tower in px
BASE_H = 9.0           # height of a 1-contribution building

ORIGIN_X = WIDTH / 2 - (WEEKS * UX + DAYS * VX) / 2
ORIGIN_Y = 248.0

FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
TEXT, MUTED, DIM = "#eef1f5", "#7b838e", "#3a4049"
BUCKETS = 8

UA = {"User-Agent": "digital-city-generator"}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def fetch_graphql(token: str) -> list[tuple[str, int]]:
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    body = json.dumps({"query": query, "variables": {"login": USER}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={**UA, "Authorization": f"bearer {token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    weeks = (data["data"]["user"]["contributionsCollection"]
             ["contributionCalendar"]["weeks"])
    return [(d["date"], d["contributionCount"])
            for w in weeks for d in w["contributionDays"]]


def fetch_html() -> list[tuple[str, int]]:
    req = urllib.request.Request(
        f"https://github.com/users/{USER}/contributions", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "replace")

    dates: dict[str, str] = {}   # cell id -> ISO date
    for tag in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        d = re.search(r'data-date="([\d-]+)"', tag)
        i = re.search(r'id="([^"]+)"', tag)
        if d and i:
            dates[i.group(1)] = d.group(1)

    counts: dict[str, int] = {}
    for cid, text in re.findall(
            r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)', html):
        if cid not in dates:
            continue
        m = re.match(r"\s*(\d+)\s+contribution", text)
        counts[dates[cid]] = int(m.group(1)) if m else 0
    if not counts:
        raise RuntimeError("Could not parse the contribution calendar")
    return sorted(counts.items())


def load_days() -> list[tuple[str, int]]:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        try:
            return fetch_graphql(token)
        except Exception as exc:  # noqa: BLE001
            print(f"GraphQL failed ({exc}); falling back to HTML",
                  file=sys.stderr)
    return fetch_html()


def to_grid(days: list[tuple[str, int]]):
    """Return a WEEKS x DAYS grid of counts (None = outside the range)."""
    days = sorted(days)[-WEEKS * DAYS:]
    first = dt.date.fromisoformat(days[0][0])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # Sunday
    grid: list[list[int | None]] = [[None] * DAYS for _ in range(WEEKS + 1)]
    for date, count in days:
        delta = (dt.date.fromisoformat(date) - start).days
        w, d = divmod(delta, 7)
        if 0 <= w < len(grid):
            grid[w][d] = count
    # Keep the last 53 weeks.
    while len(grid) > WEEKS:
        if all(c is None for c in grid[0]):
            grid.pop(0)
            start += dt.timedelta(weeks=1)
        else:
            grid.pop()
    return grid, start


def stats(days: list[tuple[str, int]]):
    counts = [c for _, c in sorted(days)]
    total = sum(counts)
    best_day = max(counts) if counts else 0
    active = sum(1 for c in counts if c)
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current = 0
    rev = counts[::-1]
    if rev and rev[0] == 0:          # today may simply not have started yet
        rev = rev[1:]
    for c in rev:
        if not c:
            break
        current += 1
    return {"total": total, "best": best_day, "active": active,
            "longest": longest, "current": current}




# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def P(w: float, d: float, z: float = 0.0) -> tuple[float, float]:
    """Project grid coordinates (week, day, height px) to screen."""
    return (ORIGIN_X + w * UX + d * VX, ORIGIN_Y + w * UY + d * VY - z)


def pts(points) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def poly(points, fill, extra="") -> str:
    return f'<polygon points="{pts(points)}" fill="{fill}"{extra}/>'


def grey(level: float, lo: int, hi: int) -> str:
    v = round(lo + (hi - lo) * max(0.0, min(1.0, level)))
    return f"#{v:02x}{min(255, v + 2):02x}{min(255, v + 6):02x}"


def bucket(level: float) -> int:
    return min(BUCKETS - 1, int(level * BUCKETS))


def text(x, y, s, size, fill, anchor="start", spacing=0.0, weight=None,
         extra=""):
    wt = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-family="{FONT}" font-size="{size}" '
            f'letter-spacing="{spacing}" fill="{fill}"{wt}{extra}>{s}</text>')


# --------------------------------------------------------------------------
# Buildings
# --------------------------------------------------------------------------

def height_for(count: int, maximum: int) -> tuple[float, float]:
    level = math.log1p(count) / math.log1p(maximum)
    return BASE_H + level * (MAX_H - BASE_H), level


def window(face: str, a, b, c, e, s0, s1, z0, z1):
    if face == "front":
        return [P(a + (b - a) * s0, e, z0), P(a + (b - a) * s1, e, z0),
                P(a + (b - a) * s1, e, z1), P(a + (b - a) * s0, e, z1)]
    return [P(b, c + (e - c) * s0, z0), P(b, c + (e - c) * s1, z0),
            P(b, c + (e - c) * s1, z1), P(b, c + (e - c) * s0, z1)]


def box(a, b, c, e, z0, z1, level, rng, windows=True) -> list[str]:
    """One extruded block with gradient faces, rim light and windows."""
    k = bucket(level)
    front = [P(a, e, z0), P(b, e, z0), P(b, e, z1), P(a, e, z1)]
    side = [P(b, c, z0), P(b, e, z0), P(b, e, z1), P(b, c, z1)]
    top = [P(a, c, z1), P(b, c, z1), P(b, e, z1), P(a, e, z1)]
    out = [poly(front, f"url(#f{k})"), poly(side, f"url(#s{k})"),
           poly(top, grey(level, 0x5c, 0xe8))]

    if windows and z1 - z0 > 12:
        floor_h = 6.2
        floors = int((z1 - z0 - 7) // floor_h)
        for face, cols in (("front", 3), ("side", 2)):
            width = 0.8 / cols
            for f in range(floors):
                zf = z0 + 4 + f * floor_h
                floor_lit = rng.random()
                if floor_lit < 0.18:          # dark floor
                    continue
                for i in range(cols):
                    if rng.random() > 0.35 + floor_lit * 0.6:
                        continue
                    s0 = 0.1 + i * width + width * 0.18
                    s1 = s0 + width * 0.64
                    w = window(face, a, b, c, e, s0, s1, zf, zf + 2.6)
                    op = 0.35 + 0.6 * rng.random()
                    if rng.random() < 0.06:
                        dur = rng.uniform(4, 11)
                        out.append(
                            f'<polygon points="{pts(w)}" fill="#f6f8fb" '
                            f'opacity="{op:.2f}"><animate '
                            f'attributeName="opacity" '
                            f'values="{op:.2f};{op:.2f};.04;{op:.2f}" '
                            f'keyTimes="0;.7;.8;1" dur="{dur:.1f}s" '
                            f'begin="-{rng.uniform(0, dur):.1f}s" '
                            f'repeatCount="indefinite"/></polygon>')
                    else:
                        out.append(poly(w, "#eef2f6",
                                        f' opacity="{op:.2f}"'))

    # Crisp corner + roof rim.
    out.append(f'<path d="M{pts([P(b, e, z0)])}L{pts([P(b, e, z1)])}" '
               f'stroke="#fff" stroke-opacity="{0.06 + 0.22 * level:.2f}" '
               f'stroke-width=".6"/>')
    out.append(f'<polyline points="{pts([top[3], top[0], top[1]])}" '
               f'fill="none" stroke="#fff" '
               f'stroke-opacity="{0.18 + 0.55 * level:.2f}" '
               f'stroke-width=".7"/>')
    return out


def building(w, d, count, maximum, rng):
    a, b = w + GAP, w + 1 - GAP
    c, e = d + GAP, d + 1 - GAP

    if count == 0:
        lot = [P(a, c, 1.2), P(b, c, 1.2), P(b, e, 1.2), P(a, e, 1.2)]
        out = poly(lot, "#13171c", ' stroke="#1c2128" stroke-width=".5"')
        if rng.random() < 0.08:          # occasional street lamp
            x, y = P((a + b) / 2, (c + e) / 2, 1.2)
            out += (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" '
                    f'fill="url(#glow)" opacity=".5"/>'
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r=".7" fill="#fff" '
                    f'opacity=".8"/>')
        return out, None

    h, level = height_for(count, maximum)
    out: list[str] = ['<g>']

    # Tiered towers (setbacks) for taller buildings, a bit of variety.
    if h > 75 and rng.random() < 0.8:
        tiers = [(0, 0.6, 0.0), (0.6, 0.85, 0.09), (0.85, 1.0, 0.18)]
    elif h > 40 and rng.random() < 0.6:
        tiers = [(0, 0.78, 0.0), (0.78, 1.0, 0.11)]
    else:
        tiers = [(0, 1.0, 0.0)]

    for lo, hi, inset in tiers:
        out += box(a + inset, b - inset, c + inset, e - inset,
                   h * lo, h * hi, level, rng)

    la, lb = a + tiers[-1][2], b - tiers[-1][2]
    lc, le = c + tiers[-1][2], e - tiers[-1][2]
    roof = [P(la, lc, h), P(lb, lc, h), P(lb, le, h), P(la, le, h)]

    # Rooftop unit on mid-size single blocks.
    if len(tiers) == 1 and h > 22 and rng.random() < 0.55:
        m = 0.28
        out += box(la + m, lb - m, lc + m, le - m, h, h + 3.2, level, rng,
                   windows=False)
    out.append('</g>')
    return "".join(out), (roof, h, level, (w, d))


# --------------------------------------------------------------------------
# Scene
# --------------------------------------------------------------------------

def defs() -> str:
    g = ['<defs>']
    for k in range(BUCKETS):
        lv = k / (BUCKETS - 1)
        g.append(
            f'<linearGradient id="f{k}" x1="0" x2="0" y1="0" y2="1">'
            f'<stop offset="0" stop-color="{grey(lv, 0x24, 0x56)}"/>'
            f'<stop offset="1" stop-color="{grey(lv, 0x0b, 0x17)}"/>'
            f'</linearGradient>'
            f'<linearGradient id="s{k}" x1="0" x2="0" y1="0" y2="1">'
            f'<stop offset="0" stop-color="{grey(lv, 0x36, 0x92)}"/>'
            f'<stop offset="1" stop-color="{grey(lv, 0x12, 0x26)}"/>'
            f'</linearGradient>')
    g.append("""
<radialGradient id="sky" cx="50%" cy="62%" r="65%">
 <stop offset="0" stop-color="#1d2228"/>
 <stop offset=".55" stop-color="#0c0e11"/>
 <stop offset="1" stop-color="#050607"/>
</radialGradient>
<radialGradient id="horizon" cx="50%" cy="50%" r="50%">
 <stop offset="0" stop-color="#9aa4b0" stop-opacity=".16"/>
 <stop offset="1" stop-color="#9aa4b0" stop-opacity="0"/>
</radialGradient>
<linearGradient id="groundG" x1="0" x2="1" y1="0" y2="1">
 <stop offset="0" stop-color="#101318"/>
 <stop offset="1" stop-color="#08090c"/>
</linearGradient>
<linearGradient id="refl" x1="0" x2="0" y1="0" y2="1">
 <stop offset="0" stop-color="#dfe6ee" stop-opacity=".13"/>
 <stop offset="1" stop-color="#dfe6ee" stop-opacity="0"/>
</linearGradient>
<linearGradient id="beam" x1="0" x2="0" y1="1" y2="0">
 <stop offset="0" stop-color="#fff" stop-opacity=".10"/>
 <stop offset="1" stop-color="#fff" stop-opacity="0"/>
</linearGradient>
<linearGradient id="sweep" x1="0" x2="1" y1="0" y2="0">
 <stop offset="0" stop-color="#fff" stop-opacity="0"/>
 <stop offset=".5" stop-color="#fff" stop-opacity=".055"/>
 <stop offset="1" stop-color="#fff" stop-opacity="0"/>
</linearGradient>
<radialGradient id="glow">
 <stop offset="0" stop-color="#fff" stop-opacity="1"/>
 <stop offset="1" stop-color="#fff" stop-opacity="0"/>
</radialGradient>
<radialGradient id="vignette" cx="50%" cy="50%" r="75%">
 <stop offset=".6" stop-color="#000" stop-opacity="0"/>
 <stop offset="1" stop-color="#000" stop-opacity=".65"/>
</radialGradient>
<linearGradient id="rule" x1="0" x2="1">
 <stop offset="0" stop-color="#fff" stop-opacity="0"/>
 <stop offset=".5" stop-color="#fff" stop-opacity=".16"/>
 <stop offset="1" stop-color="#fff" stop-opacity="0"/>
</linearGradient>""")
    pad = 0.55
    ground = [P(-pad, -pad), P(WEEKS + pad, -pad), P(WEEKS + pad, DAYS + pad),
              P(-pad, DAYS + pad)]
    g.append(f'<clipPath id="groundClip"><polygon points="{pts(ground)}"/>'
             f'</clipPath>')
    g.append('</defs>')
    return "\n".join(g), ground


def render(grid, st, first_date: dt.date) -> str:
    rng = random.Random(77)
    values = [c for col in grid for c in col if c is not None]
    maximum = max(values + [1])
    defs_svg, ground = defs()

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
         f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
         f'aria-labelledby="title desc">',
         '<title id="title">SZCZYGI77 Digital City</title>',
         '<desc id="desc">Animated monochrome isometric night city built '
         'from GitHub contributions. Every day is a city block and the '
         'building height follows the number of contributions.</desc>',
         defs_svg,
         f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#sky)"/>']

    # Stars (upper sky only)
    for _ in range(90):
        x, y = rng.uniform(24, WIDTH - 24), rng.uniform(24, 260)
        if y < 125 and (x < 560 or x > 930):   # keep the header clean
            continue
        r = rng.choice((.35, .5, .5, .7, .9, 1.2))
        dur, delay = rng.uniform(3, 8), rng.uniform(0, 8)
        lo = rng.uniform(.05, .2)
        p.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="#fff" '
                 f'opacity="{lo:.2f}"><animate attributeName="opacity" '
                 f'values="{lo:.2f};{lo + .55:.2f};{lo:.2f}" dur="{dur:.1f}s" '
                 f'begin="-{delay:.1f}s" repeatCount="indefinite"/></circle>')

    # Aircraft crossing the sky (blinking nav light).
    p.append('<g><animateMotion path="M-40,150 L1240,96" dur="46s" '
             'begin="-12s" repeatCount="indefinite"/>'
             '<circle r=".9" fill="#fff" opacity=".7"/>'
             '<circle cx="-7" r=".7" fill="#fff" opacity="0">'
             '<animate attributeName="opacity" values="0;.9;0;0" '
             'keyTimes="0;.1;.2;1" dur="1.6s" repeatCount="indefinite"/>'
             '</circle></g>')

    # Horizon glow behind the skyline
    cx, cy = P(WEEKS / 2, DAYS / 2)
    p.append(f'<ellipse cx="{cx:.0f}" cy="{cy - 70:.0f}" rx="620" ry="230" '
             f'fill="url(#horizon)"/>')

    # Pre-compute heights for searchlights
    heights = []
    for w in range(WEEKS):
        for d in range(DAYS):
            c = grid[w][d]
            if c:
                heights.append((height_for(c, maximum)[0], w, d))
    heights.sort(reverse=True)

    # Searchlights sweeping from the two tallest blocks
    for i, (_, w, d) in enumerate(heights[:2]):
        x, y = P(w + .5, d + .5)
        a0, a1 = (-22, 16) if i == 0 else (18, -14)
        dur = 17 + i * 5
        p.append(f'<g opacity=".9"><animateTransform attributeName="transform" '
                 f'type="rotate" values="{a0} {x:.0f} {y:.0f};{a1} {x:.0f} '
                 f'{y:.0f};{a0} {x:.0f} {y:.0f}" dur="{dur}s" '
                 f'repeatCount="indefinite"/>'
                 f'<polygon points="{x:.0f},{y:.0f} {x - 26:.0f},{y - 330:.0f} '
                 f'{x + 26:.0f},{y - 330:.0f}" fill="url(#beam)"/></g>')

    # Ground slab: thickness, glass top, street grid
    t = 9
    gl = [(x, y + t) for x, y in ground]
    p.append(poly([ground[3], ground[2], gl[2], gl[3]], "#0b0d10"))
    p.append(poly([ground[1], ground[2], gl[2], gl[1]], "#14181d"))
    p.append(poly(ground, "url(#groundG)"))
    p.append(f'<path d="M{pts([ground[3]])}L{pts([ground[2]])}L'
             f'{pts([ground[1]])}" fill="none" stroke="#fff" '
             f'stroke-opacity=".22" stroke-width=".8"/>')
    lines = []
    for w in range(WEEKS + 1):
        lines.append(f"M{pts([P(w, 0)])}L{pts([P(w, DAYS)])}")
    for d in range(DAYS + 1):
        lines.append(f"M{pts([P(0, d)])}L{pts([P(WEEKS, d)])}")
    p.append(f'<path d="{"".join(lines)}" stroke="#202630" '
             f'stroke-width=".45" fill="none"/>')

    # Black-glass reflections, clipped to the ground
    refl = ['<g clip-path="url(#groundClip)">']
    for w in range(WEEKS):
        for d in range(DAYS):
            c = grid[w][d]
            if not c:
                continue
            h = height_for(c, maximum)[0] * 0.45
            a, b = w + GAP, w + 1 - GAP
            cc, e = d + GAP, d + 1 - GAP
            refl.append(poly([P(a, e), P(b, e), P(b, e, -h), P(a, e, -h)],
                             "url(#refl)"))
            refl.append(poly([P(b, cc), P(b, e), P(b, e, -h), P(b, cc, -h)],
                             "url(#refl)", ' opacity=".7"'))
    refl.append('</g>')
    p.append("".join(refl))

    # Traffic on interior avenues (drawn below buildings)
    def car(s, e_, dur, delay, r=0.9, op=0.75):
        x0, y0 = P(*s)
        x1, y1 = P(*e_)
        return (f'<circle r="{r}" fill="#fff" opacity="{op}">'
                f'<animateMotion path="M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}" '
                f'dur="{dur:.0f}s" begin="-{delay:.0f}s" '
                f'repeatCount="indefinite"/></circle>')

    for i in range(7):
        d = rng.randint(1, DAYS - 1)
        fwd = rng.random() < .5
        s, e_ = ((-.3, d), (WEEKS + .3, d)) if fwd else ((WEEKS + .3, d),
                                                        (-.3, d))
        p.append(car(s, e_, rng.uniform(28, 48), rng.uniform(0, 40)))

    # Buildings, back to front (painter's algorithm)
    tops = []
    for diag in range(WEEKS + DAYS - 1):
        for w in range(WEEKS):
            d = diag - w
            if 0 <= d < DAYS and grid[w][d] is not None:
                svg, info = building(w, d, grid[w][d], maximum, rng)
                p.append(svg)
                if info:
                    tops.append(info)

    # Front avenue traffic (in front of everything)
    for s, e_, dur, delay in (((-.4, DAYS + .3), (WEEKS + .4, DAYS + .3), 30, 0),
                              ((WEEKS + .4, DAYS + .3), (-.4, DAYS + .3), 36, 11),
                              ((-.4, DAYS + .3), (WEEKS + .4, DAYS + .3), 30, 17),
                              ((WEEKS + .3, -.4), (WEEKS + .3, DAYS + .4), 10, 3)):
        p.append(car(s, e_, dur, delay, r=1.1, op=.9))

    # Beacons + antennas on the tallest towers
    for i, (roof, h, level, _) in enumerate(
            sorted(tops, key=lambda x: -x[1])[:5]):
        cx = sum(x for x, _ in roof) / 4
        cy = sum(y for _, y in roof) / 4
        top_y = cy - 12 - (4 if i == 0 else 0)
        dur = 2.2 + i * 0.37
        p.append(f'<path d="M{cx:.1f},{cy:.1f}V{top_y:.1f}" stroke="#c9d0d8" '
                 f'stroke-width=".8"/>')
        p.append(f'<circle cx="{cx:.1f}" cy="{top_y:.1f}" r="9" '
                 f'fill="url(#glow)" opacity=".1"><animate '
                 f'attributeName="opacity" values=".05;.55;.05" '
                 f'dur="{dur:.2f}s" repeatCount="indefinite"/></circle>')
        p.append(f'<circle cx="{cx:.1f}" cy="{top_y:.1f}" r="1.3" '
                 f'fill="#fff"/>')

    # Month labels along the front edge
    seen = None
    for w in range(WEEKS):
        day = first_date + dt.timedelta(weeks=w)
        if day.month != seen and w < WEEKS - 2:
            if seen is not None or day.day <= 7:
                x, y = P(w + .1, DAYS + 1.25)
                p.append(text(x, y, day.strftime("%b").upper(), 9.5, MUTED,
                              spacing=1.5,
                              extra=f' transform="rotate(13.9 {x:.1f} '
                                    f'{y:.1f})"'))
                tx, ty = P(w, DAYS + .55)
                p.append(f'<path d="M{tx:.1f},{ty:.1f}l{VX * .25:.1f},'
                         f'{VY * .25:.1f}" stroke="{MUTED}" '
                         f'stroke-width=".6"/>')
            seen = day.month

    # Slow light sweep across the scene
    p.append(f'<rect x="-320" y="100" width="280" height="500" '
             f'fill="url(#sweep)"><animate attributeName="x" '
             f'values="-320;{WIDTH + 40}" dur="16s" '
             f'repeatCount="indefinite"/></rect>')

    p.append(f'<rect width="{WIDTH}" height="{HEIGHT}" '
             f'fill="url(#vignette)"/>')

    # ---------- HUD / typography ----------
    m = 18
    p.append(f'<rect x="{m}" y="{m}" width="{WIDTH - 2 * m}" '
             f'height="{HEIGHT - 2 * m}" rx="14" fill="none" '
             f'stroke="#fff" stroke-opacity=".07"/>')
    for x, y, sx, sy in ((m + 8, m + 8, 1, 1), (WIDTH - m - 8, m + 8, -1, 1),
                         (m + 8, HEIGHT - m - 8, 1, -1),
                         (WIDTH - m - 8, HEIGHT - m - 8, -1, -1)):
        p.append(f'<path d="M{x},{y + 10 * sy}V{y}H{x + 10 * sx}" '
                 f'fill="none" stroke="#fff" stroke-opacity=".35" '
                 f'stroke-width=".8"/>')

    L, R = 58, WIDTH - 58
    p.append(text(L, 60, "GITHUB.COM/SZCZYGI77", 10.5, MUTED, spacing=3))
    p.append(text(L, 90, "SZCZYGI77 / DIGITAL CITY", 23, TEXT, spacing=6,
                  weight=500))
    p.append(text(L, 112, "A YEAR OF BUILDING THINGS · 1 DAY = 1 BLOCK",
                  10.5, MUTED, spacing=3))

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y.%m.%d")
    p.append(f'<circle cx="{R - 140}" cy="59" r="2.4" fill="#fff">'
             f'<animate attributeName="opacity" values="1;.2;1" dur="2s" '
             f'repeatCount="indefinite"/></circle>')
    p.append(f'<circle cx="{R - 140}" cy="59" r="6" fill="url(#glow)" '
             f'opacity=".35"><animate attributeName="r" values="3;8;3" '
             f'dur="2s" repeatCount="indefinite"/></circle>')
    p.append(text(R - 130, 62, "LIVE DATA", 10.5, TEXT, spacing=3))
    p.append(text(R, 90, f"UPDATED {stamp}", 10.5, MUTED, "end", 3))
    p.append(text(R, 110, f"{len(values)} DAYS · {sum(values):,} EVENTS"
                  .replace(",", " "), 10.5, MUTED, "end", 3))

    # Bottom rule + stats
    p.append(f'<rect x="{L}" y="{HEIGHT - 122}" width="{R - L}" height=".8" '
             f'fill="url(#rule)"/>')
    stats_list = [("CONTRIBUTIONS", f"{st['total']:,}".replace(",", " ")),
                  ("ACTIVE DAYS", st["active"]),
                  ("BEST DAY", st["best"]),
                  ("LONGEST STREAK", f"{st['longest']}d"),
                  ("CURRENT STREAK", f"{st['current']}d")]
    col = 162
    for i, (label, value) in enumerate(stats_list):
        x = L + i * col
        p.append(text(x, HEIGHT - 82, value, 26, TEXT, weight=500))
        p.append(text(x, HEIGHT - 61, label, 9.5, MUTED, spacing=2.5))
        if i:
            p.append(f'<rect x="{x - 18}" y="{HEIGHT - 100}" width=".6" '
                     f'height="40" fill="#fff" opacity=".1"/>')

    # Legend: LESS ▮▮▮▮ MORE as tiny isometric blocks
    lx = R - 170
    ly = HEIGHT - 66
    p.append(text(lx - 8, ly, "LESS", 9.5, MUTED, "end", 2.5))
    for i, lv in enumerate((0.0, .25, .5, .75, 1.0)):
        x0 = lx + 8 + i * 22
        hh = 3 + lv * 26
        w_, d_ = 8, 4
        front = [(x0, ly), (x0 + w_, ly + 2), (x0 + w_, ly + 2 - hh),
                 (x0, ly - hh)]
        side = [(x0 + w_, ly + 2), (x0 + w_ + 5, ly - 1),
                (x0 + w_ + 5, ly - 1 - hh), (x0 + w_, ly + 2 - hh)]
        top = [(x0, ly - hh), (x0 + w_, ly + 2 - hh),
               (x0 + w_ + 5, ly - 1 - hh), (x0 + 5, ly - 3 - hh)]
        k = bucket(lv)
        p.append(poly(front, f"url(#f{k})") + poly(side, f"url(#s{k})") +
                 poly(top, grey(lv, 0x5c, 0xe8)))
    p.append(text(lx + 8 + 5 * 22 + 4, ly, "MORE", 9.5, MUTED, spacing=2.5))

    p.append(text(WIDTH / 2, HEIGHT - 34, "EVERY COMMIT BUILDS SOMETHING",
                  10.5, "#5d646e", "middle", 5))
    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    days = load_days()
    grid, first_date = to_grid(days)
    svg = render(grid, stats(days), first_date)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    print(f"Wrote {OUT} ({len(svg) / 1024:.0f} KB, {len(days)} days)")


if __name__ == "__main__":
    main()
