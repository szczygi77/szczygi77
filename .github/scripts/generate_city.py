#!/usr/bin/env python3
"""SZCZYGI77 / DIGITAL CITY

Renders the GitHub contribution calendar as an animated, monochrome,
isometric night city (pure SVG + SMIL, standard library only).

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

WIDTH, HEIGHT = 1200, 720
WEEKS, DAYS = 53, 7

# Oblique "isometric" axes: one step along a week / along a weekday.
UX, UY = 18.5, 4.6     # week axis  -> right, slightly down
VX, VY = -12.0, 7.6    # day axis   -> left, down
GAP = 0.14             # street width (fraction of a cell)
MAX_H = 128.0          # tallest tower in px

ORIGIN_X = WIDTH / 2 - (WEEKS * UX + DAYS * VX) / 2
ORIGIN_Y = 250.0

PALETTE = {
    "background": "#07080a",
    "ground": "#0e1115",
    "ground_edge": "#1a1f25",
    "street": "#14181d",
    "text": "#f2f4f7",
    "muted": "#737b85",
}

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
        grid.pop(0) if all(c is None for c in grid[0]) else grid.pop()
    return grid


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

def project(w: float, d: float, z: float = 0.0) -> tuple[float, float]:
    return (ORIGIN_X + w * UX + d * VX, ORIGIN_Y + w * UY + d * VY - z)


def pts(points) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def polygon(points, fill, opacity=1.0, extra="") -> str:
    op = f' opacity="{opacity:.2f}"' if opacity < 1 else ""
    return f'<polygon points="{pts(points)}" fill="{fill}"{op}{extra}/>'


def shade(level: float, lo: int, hi: int) -> str:
    v = round(lo + (hi - lo) * level)
    return f"#{v:02x}{v:02x}{min(255, v + 4):02x}"


# --------------------------------------------------------------------------
# Building renderer
# --------------------------------------------------------------------------

def building(w: int, d: int, count: int, maximum: int, rng: random.Random):
    a, b = w + GAP, w + 1 - GAP
    c, e = d + GAP, d + 1 - GAP

    if count <= 0:
        # Empty lot - a dim slab.
        return polygon([project(a, c), project(b, c), project(b, e),
                        project(a, e)], "#161a1f")

    level = math.sqrt(count / maximum)
    h = 6 + level * MAX_H

    top = [project(a, c, h), project(b, c, h), project(b, e, h),
           project(a, e, h)]
    front = [project(a, e, 0), project(b, e, 0), project(b, e, h),
             project(a, e, h)]
    side = [project(b, c, 0), project(b, e, 0), project(b, e, h),
            project(b, c, h)]

    out = [
        '<g>',
        polygon(front, shade(level, 0x1b, 0x3a)),
        polygon(side, shade(level, 0x2b, 0x6c)),
        polygon(top, shade(level, 0x6a, 0xe6)),
    ]

    # Windows on both visible faces.
    floor_h = 7.5
    floors = int((h - 6) // floor_h)
    if floors >= 1:
        for face in ("front", "side"):
            cols = (0.25, 0.6) if face == "front" else (0.3,)
            for f in range(floors):
                z0 = 5 + f * floor_h
                for s in cols:
                    roll = rng.random()
                    if roll < 0.35:
                        continue
                    s0, s1 = s, s + 0.22
                    if face == "front":
                        p = [project(a + (b - a) * s0, e, z0),
                             project(a + (b - a) * s1, e, z0),
                             project(a + (b - a) * s1, e, z0 + 2.6),
                             project(a + (b - a) * s0, e, z0 + 2.6)]
                    else:
                        p = [project(b, c + (e - c) * s0, z0),
                             project(b, c + (e - c) * s1, z0),
                             project(b, c + (e - c) * s1, z0 + 2.6),
                             project(b, c + (e - c) * s0, z0 + 2.6)]
                    op = 0.25 + 0.65 * rng.random()
                    if roll > 0.9:
                        dur = rng.uniform(3, 9)
                        out.append(
                            f'<polygon points="{pts(p)}" fill="#ffffff" '
                            f'opacity="{op:.2f}"><animate '
                            f'attributeName="opacity" '
                            f'values="{op:.2f};.05;{op:.2f}" '
                            f'dur="{dur:.1f}s" '
                            f'begin="-{rng.uniform(0, dur):.1f}s" '
                            f'repeatCount="indefinite"/></polygon>')
                    else:
                        out.append(polygon(p, "#e9edf2", op))

    # Rim light on the roof edge.
    out.append(
        f'<polyline points="{pts([top[3], top[0], top[1]])}" fill="none" '
        f'stroke="#ffffff" stroke-opacity="{0.15 + 0.5 * level:.2f}" '
        f'stroke-width=".6"/>')
    out.append('</g>')
    return "".join(out), (top, h, level)


# --------------------------------------------------------------------------
# Scene
# --------------------------------------------------------------------------

def render(grid, st) -> str:
    rng = random.Random(77)
    values = [c for col in grid for c in col if c is not None]
    maximum = max(values + [1])

    p = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-labelledby="title desc">')
    p.append('<title id="title">SZCZYGI77 Digital City</title>')
    p.append('<desc id="desc">Animated monochrome isometric city built from '
             'GitHub contributions: every day is a building, its height is '
             'the number of contributions.</desc>')
    p.append("""<defs>
<radialGradient id="ambient" cx="50%" cy="50%" r="50%">
<stop offset="0%" stop-color="#3a4048" stop-opacity=".45"/>
<stop offset="100%" stop-color="#07080a" stop-opacity="0"/>
</radialGradient>
<linearGradient id="sweep" x1="0" x2="1" y1="0" y2="0">
<stop offset="0" stop-color="#fff" stop-opacity="0"/>
<stop offset=".5" stop-color="#fff" stop-opacity=".07"/>
<stop offset="1" stop-color="#fff" stop-opacity="0"/>
</linearGradient>
<linearGradient id="fog" x1="0" x2="0" y1="0" y2="1">
<stop offset="0" stop-color="#07080a" stop-opacity="0"/>
<stop offset="1" stop-color="#07080a" stop-opacity=".9"/>
</linearGradient>
<radialGradient id="beacon">
<stop offset="0" stop-color="#fff" stop-opacity=".9"/>
<stop offset="1" stop-color="#fff" stop-opacity="0"/>
</radialGradient>
</defs>""")
    p.append(f'<rect width="{WIDTH}" height="{HEIGHT}" '
             f'fill="{PALETTE["background"]}"/>')
    p.append(f'<ellipse cx="{WIDTH / 2}" cy="380" rx="600" ry="320" '
             f'fill="url(#ambient)"/>')

    # Stars
    for _ in range(70):
        x, y = rng.uniform(20, WIDTH - 20), rng.uniform(20, 300)
        r, delay, dur = rng.uniform(.4, 1.3), rng.uniform(0, 5), rng.uniform(3, 7)
        p.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="#fff" '
                 f'opacity=".3"><animate attributeName="opacity" '
                 f'values=".08;.75;.08" dur="{dur:.1f}s" begin="-{delay:.1f}s" '
                 f'repeatCount="indefinite"/></circle>')

    # Header
    p.append(f'<text x="{WIDTH / 2}" y="58" text-anchor="middle" '
             f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
             f'font-size="18" letter-spacing="8" fill="{PALETTE["text"]}">'
             f'SZCZYGI77 / DIGITAL CITY</text>')
    p.append(f'<text x="{WIDTH / 2}" y="84" text-anchor="middle" '
             f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
             f'font-size="9.5" letter-spacing="4" fill="{PALETTE["muted"]}">'
             f'A YEAR OF BUILDING THINGS · 1 DAY = 1 BUILDING</text>')

    # Ground slab with thickness
    pad = 0.6
    g = [project(-pad, -pad), project(WEEKS + pad, -pad),
         project(WEEKS + pad, DAYS + pad), project(-pad, DAYS + pad)]
    t = 7
    p.append(polygon([g[3], g[2], (g[2][0], g[2][1] + t), (g[3][0], g[3][1] + t)],
                     "#0a0c0f"))
    p.append(polygon([g[1], g[2], (g[2][0], g[2][1] + t), (g[1][0], g[1][1] + t)],
                     "#111419"))
    p.append(polygon(g, PALETTE["ground"]))
    p.append(f'<polygon points="{pts(g)}" fill="none" '
             f'stroke="{PALETTE["ground_edge"]}" stroke-width="1"/>')

    # Traffic lights moving along the outer avenues.
    for (s, e_, dur, delay) in (((-.3, DAYS + .3), (WEEKS + .3, DAYS + .3), 26, 0),
                                ((WEEKS + .3, DAYS + .3), (-.3, DAYS + .3), 31, 9),
                                ((WEEKS + .3, -.3), (WEEKS + .3, DAYS + .3), 9, 2),
                                ((-.3, -.3), (WEEKS + .3, -.3), 34, 14)):
        x0, y0 = project(*s)
        x1, y1 = project(*e_)
        p.append(f'<circle r="1.3" fill="#fff" opacity=".85">'
                 f'<animateMotion path="M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}" '
                 f'dur="{dur}s" begin="-{delay}s" repeatCount="indefinite"/>'
                 f'</circle>')

    # Buildings, back to front (painter's algorithm).
    tops = []
    for diag in range(WEEKS + DAYS - 1):
        for w in range(WEEKS):
            d = diag - w
            if 0 <= d < DAYS and grid[w][d] is not None:
                res = building(w, d, grid[w][d], maximum, rng)
                if isinstance(res, tuple):
                    svg, info = res
                    tops.append(info)
                else:
                    svg = res
                p.append(svg)

    # Beacons on the five tallest towers.
    for i, (top, h, level) in enumerate(sorted(tops, key=lambda x: -x[1])[:5]):
        cx = sum(x for x, _ in top) / 4
        cy = sum(y for _, y in top) / 4
        dur = 2.4 + i * 0.35
        p.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx:.1f}" '
                 f'y2="{cy - 9:.1f}" stroke="#cfd5dc" stroke-width=".8"/>')
        p.append(f'<circle cx="{cx:.1f}" cy="{cy - 9:.1f}" r="7" '
                 f'fill="url(#beacon)" opacity=".2"><animate '
                 f'attributeName="opacity" values=".1;.9;.1" dur="{dur:.1f}s" '
                 f'repeatCount="indefinite"/></circle>')
        p.append(f'<circle cx="{cx:.1f}" cy="{cy - 9:.1f}" r="1.4" '
                 f'fill="#fff"/>')

    # Slow light sweep across the skyline.
    p.append(f'<rect x="-300" y="110" width="260" height="520" '
             f'fill="url(#sweep)"><animate attributeName="x" '
             f'values="-300;{WIDTH + 40}" dur="14s" repeatCount="indefinite"/>'
             f'</rect>')

    # Fog at the bottom
    p.append(f'<rect y="{HEIGHT - 190}" width="{WIDTH}" height="190" '
             f'fill="url(#fog)"/>')

    # Stats bar
    labels = [("CONTRIBUTIONS", st["total"]), ("ACTIVE DAYS", st["active"]),
              ("BEST DAY", st["best"]), ("LONGEST STREAK", st["longest"]),
              ("CURRENT STREAK", st["current"])]
    span = 190
    x0 = WIDTH / 2 - span * (len(labels) - 1) / 2
    for i, (label, value) in enumerate(labels):
        x = x0 + i * span
        p.append(f'<text x="{x:.0f}" y="{HEIGHT - 78}" text-anchor="middle" '
                 f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
                 f'font-size="20" fill="{PALETTE["text"]}">{value}</text>')
        p.append(f'<text x="{x:.0f}" y="{HEIGHT - 60}" text-anchor="middle" '
                 f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
                 f'font-size="8.5" letter-spacing="2.5" '
                 f'fill="{PALETTE["muted"]}">{label}</text>')

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    p.append(f'<text x="{WIDTH / 2}" y="{HEIGHT - 26}" text-anchor="middle" '
             f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
             f'font-size="9.5" letter-spacing="4" fill="#858b93">'
             f'EVERY COMMIT BUILDS SOMETHING · UPDATED {stamp}</text>')
    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    days = load_days()
    grid = to_grid(days)
    svg = render(grid, stats(days))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    print(f"Wrote {OUT} ({len(svg) / 1024:.0f} KB, {len(days)} days)")


if __name__ == "__main__":
    main()
