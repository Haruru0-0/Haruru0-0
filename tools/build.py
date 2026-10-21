"""Generate the terminal-style SVG cards and README.md for the profile.

Usage: python tools/build.py   (needs `gh` logged in and `pip install pillow`)
"""
import hashlib
import json
import subprocess
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from PIL import Image, ImageOps

LOGIN = "Haruru0-0"
NAME = "Ahmad Kanaan"
ROLE = "Full Stack Developer"
LOCATION = "Tripoli, Lebanon"
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

VERSIONS = {}  # card name -> content hash, filled in main() and used by the README image URLs

FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
BG, CARD, BORDER = "#0b0f14", "#010409", "#30363d"  # CARD is darker than GitHub's dark page (#0d1117) so cards stand out
FG, MUTED, BLUE, GREEN = "#e6edf3", "#8b949e", "#58a6ff", "#3fb950"
LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572a5",
    "Jupyter Notebook": "#da5b0b", "CSS": "#9b59d0", "HTML": "#e34c26",
    "Java": "#b07219", "Shell": "#89e051",
}


SKILL_GROUPS = [
    ("DevOps / Cloud", ["Docker", "Kubernetes", "AWS", "AWS Lambda", "API Gateway", "Google Cloud", "Azure"]),
    ("Backend", ["Spring Boot", "Node.js", "Express", "NestJS", "FastAPI", "Django", "Laravel"]),
    ("Frontend", ["React", "Next.js", "React Native", "TypeScript", "Tailwind CSS", "shadcn/ui", "React Query", "GSAP", "Howler"]),
    ("E-commerce", ["Shopify", "Storefront API", "Admin API", "Hydrogen/Oxygen", "Stripe"]),
    ("APIs", ["REST", "GraphQL"]),
    ("Realtime / Auth", ["WebSocket", "Yjs", "Tiptap", "JWT"]),
    ("Automation", ["n8n", "Webhooks"]),
    ("Testing", ["Jest", "Playwright", "Vitest", "Cypress"]),
    ("Monitoring", ["Sentry"]),
    ("Databases & ORMs", ["PostgreSQL", "MongoDB", "Firebase Firestore", "Redis", "Supabase", "Drizzle ORM"]),
    ("Data Science / ML", ["Pandas", "Scikit-learn", "NumPy", "Matplotlib", "Data Visualization"]),
    ("AI", ["OpenAI API", "Google Gemini", "Vercel AI SDK"]),
]


class Reveal:
    """Looping reveal animations built from CSS keyframes.

    GitHub shows SVGs through <img>, so there is no script and no "scroll into view" trigger.
    Every element shares one cycle: it reveals at its start time, holds, then all erase together
    and the loop restarts, so the reveal is visible whenever someone looks.
    """

    def __init__(self, cycle):
        self.d, self.css, self.n = cycle, [], 0

    def cls(self, start, dur, kind="fade", steps=0):
        self.n += 1
        name = f"r{self.n}"
        a, b = start / self.d * 100, (start + dur) / self.d * 100
        assert b < 92, "reveal must finish before the shared erase"
        hid, shown = {"fade": ("opacity:0", "opacity:1"),
                      "type": ("clip-path:inset(-4px calc(100% + 4px) -4px -4px)","clip-path:inset(-4px -4px -4px -4px)")}[kind]
        timing = f"animation-timing-function:steps({steps});" if steps else ""
        self.css.append(f"@keyframes {name}{{0%,{a:.2f}%{{{hid}}}{b:.2f}%,93%{{{shown}}}97%,100%{{{hid}}}}}"
                        f".{name}{{animation:{name} {self.d}s infinite;{timing}}}")
        return name

    def style(self, extra=""):
        return ("<style>" + "".join(self.css) + extra +
                "@media(prefers-reduced-motion:reduce){*{animation:none!important}}</style>")


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def esc(s):
    return escape(str(s), quote=True)


def svg(w, h, body, defs=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="{FONT}">\n<defs>{defs}</defs>\n{body}\n</svg>\n'
    )


def watermark(w, h):
    return ""  # no third-party branding


def window(w, h, title, inner, radius=12):
    dots = "".join(
        f'<circle cx="{22 + i * 20}" cy="20" r="6" fill="{c}"/>'
        for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"])
    )
    return (
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="{radius}" fill="{CARD}" stroke="{BORDER}"/>'
        f'<path d="M0.5 40.5V{radius + 0.5}a{radius} {radius} 0 0 1 {radius} -{radius}H{w - radius - 0.5}'
        f'a{radius} {radius} 0 0 1 {radius} {radius}V40.5z" fill="#161b22"/>'
        f'<path d="M0.5 40.5H{w - 0.5}" stroke="{BORDER}"/>{dots}'
        f'<text x="{w / 2}" y="24" text-anchor="middle" font-size="12" fill="{MUTED}">{esc(title)}</text>'
        f"{inner}"
    )


def wrap(text, width, lines):
    words, out, cur = text.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > width:
            out.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: width - 1].rstrip() + "…"
    return out


# ---------- data ----------
def load_data():
    user = gh("api", "user")
    repos = gh("repo", "list", LOGIN, "--limit", "30", "--json",
               "name,description,primaryLanguage,stargazerCount,updatedAt,isFork,repositoryTopics")
    repos = [r for r in repos if not r["isFork"]]
    for r in repos:
        try:
            r["langs"] = gh("api", f"repos/{LOGIN}/{r['name']}/languages")
        except subprocess.CalledProcessError:
            r["langs"] = {}
    q = ('{user(login:"%s"){contributionsCollection{contributionCalendar{totalContributions '
         "weeks{contributionDays{contributionCount date}}}}}}") % LOGIN
    cal = gh("api", "graphql", "-f", f"query={q}")["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return user, repos, cal


# ---------- cards ----------
def fetch_avatar(avatar_url):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(urllib.request.urlopen(avatar_url + "&s=400").read())
    return Image.open(f.name).convert("RGB")


RAMP = " .:-=+*#%@"


def ascii_art(avatar_url, cols=50, rows=25):
    """Return rows of (char, hex colour) tuples; char cells are ~2x taller than wide."""
    im = ImageOps.autocontrast(fetch_avatar(avatar_url), cutoff=2)
    side = im.width
    crop_h = int(side * rows * 2 / cols)  # keep the avatar's aspect after the 1:2 cell squash
    crop_h = min(crop_h, side)
    top = max(0, (side - crop_h) // 2 - side // 14)
    im = im.crop((0, top, side, top + crop_h)).resize((cols, rows), Image.LANCZOS)
    out = []
    for y in range(rows):
        row = []
        for x in range(cols):
            r, g, b = im.getpixel((x, y))
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if lum < 0.10:
                row.append((" ", None))
                continue
            m = max(r, g, b) or 1
            k = min(1.4, 235 / m)
            col = "#%02x%02x%02x" % (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)))
            row.append((RAMP[min(len(RAMP) - 1, int(lum ** 0.8 * len(RAMP)))], col))
        out.append(row)
    return out


def portrait(avatar_url):
    cols, rows, step = 60, 36, 12
    w, h = cols * step + 60, rows * step + 60
    im = fetch_avatar(avatar_url)
    side = im.width
    crop_h = int(side * rows / cols)
    top = max(0, (side - crop_h) // 2 - side // 12)
    im = im.crop((0, top, side, top + crop_h)).resize((cols, rows), Image.LANCZOS)
    dots = []
    for y in range(rows):
        for x in range(cols):
            r, g, b = im.getpixel((x, y))
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if lum < 0.12:
                continue
            m = max(r, g, b) or 1
            k = min(1.35, 235 / m)  # lift brightness without washing out hue
            col = "#%02x%02x%02x" % (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)))
            rad = 1.6 + lum * 2.6
            dots.append(f'<circle cx="{30 + x * step + step / 2}" cy="{30 + y * step + step / 2}" r="{rad:.1f}" fill="{col}"/>')
    body = f'<rect width="{w}" height="{h}" rx="14" fill="#090c10" stroke="{BORDER}"/>' + "".join(dots)
    return w, h, svg(w, h, body)


def longest_streak(cal):
    best = cur = 0
    for wk in cal["weeks"]:
        for d in wk["contributionDays"]:
            cur = cur + 1 if d["contributionCount"] else 0
            best = max(best, cur)
    return best


def identity(user, stars, contribs, streak):
    w, h = 440, 340
    rows = [("repos", user["public_repos"]), ("stars", stars), ("contributions", contribs),
            ("longest streak", f"{streak} days"), ("followers", user["followers"]),
            ("location", LOCATION)]
    L, R = 28, w - 28
    an = Reveal(12)
    b = [f'<rect width="{w}" height="{h}" rx="14" fill="#090c10" stroke="{BORDER}"/>',
         f'<rect x="{L}" y="28" width="{R - L}" height="{h - 56}" rx="4" fill="none" stroke="{BLUE}" stroke-opacity="0.6"/>',
         f'<text x="{L + 14}" y="32" font-size="13" fill="{BLUE}" stroke="#090c10" stroke-width="8" paint-order="stroke">[ IDENTITY ]</text>',
         f'<text class="{an.cls(0.3, 0.9, "type", len(NAME))}" x="{L + 20}" y="66" font-size="16" font-weight="bold" fill="{FG}">{esc(NAME)}</text>',
         f'<text class="{an.cls(1.3, 0.4)}" x="{L + 20}" y="88" font-size="13" fill="{MUTED}">{esc(ROLE)}</text>',
         f'<path d="M{L} 112H{R}" stroke="{BLUE}" stroke-opacity="0.6"/>',
         f'<text x="{L + 14}" y="116" font-size="13" fill="{BLUE}" stroke="#090c10" stroke-width="8" paint-order="stroke">[ TELEMETRY ]</text>']
    y = 150
    for i, (k, v) in enumerate(rows):
        b.append(f'<g class="{an.cls(2.0 + i * 0.35, 0.4)}"><text x="{L + 20}" y="{y}" font-size="14" fill="{MUTED}">{k}</text>'
                 f'<text x="{R - 20}" y="{y}" font-size="14" fill="{FG}" text-anchor="end">{esc(v)}</text></g>')
        y += 28
    return w, h, svg(w, h, "".join(b), an.style())


def skills(groups):
    w, lx, cx0 = 880, 28, 190
    y, parts = 112, []
    an = Reveal(16)
    for gi, (label, items) in enumerate(groups):
        parts.append(f'<g class="{an.cls(1.4 + gi * 0.4, 0.45)}"><text x="{lx}" y="{y - 2}" font-size="12" fill="{MUTED}">{esc(label)}</text>')
        x = cx0
        for it in items:
            cw = len(it) * 7.4 + 22
            if x + cw > w - 24:
                x, y = cx0, y + 32
            parts.append(f'<rect x="{x:.1f}" y="{y - 18}" width="{cw:.1f}" height="26" rx="6" fill="#111826" stroke="#1f3558"/>'
                         f'<text x="{x + cw / 2:.1f}" y="{y - 1}" text-anchor="middle" font-size="12" fill="{BLUE}">{esc(it)}</text>')
            x += cw + 8
        parts.append("</g>")
        y += 42
    h = y + 4
    inner = (f'<text class="{an.cls(0.3, 1.0, "type", 22)}" x="28" y="72" font-size="14"><tspan fill="{GREEN}" font-weight="bold">{LOGIN.lower()}@github</tspan>'
             f'<tspan fill="{FG}"> :~$ ls skills/</tspan></text>') + "".join(parts)
    return w, h, svg(w, h, window(w, h, f"{LOGIN.lower()}@github: ~$ ls skills/", inner), an.style())


def donut(cx, cy, pct, color):
    r, c = 22, 2 * 3.14159 * 22
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1c2330" stroke-width="6"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="6" '
            f'stroke-dasharray="{c * pct / 100:.1f} {c:.1f}" transform="rotate(-90 {cx} {cy})"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="11" font-weight="bold" fill="{FG}">{pct}%</text>')


def projects(repos):
    shown = [r for r in repos if r["name"] != LOGIN][:6]
    cw, ch, gap, pad = 392, 128, 16, 28
    w = pad * 2 + cw * 2 + gap
    rows = (len(shown) + 1) // 2
    h = 76 + rows * (ch + gap) + 10
    b = [f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="{CARD}" stroke="#1f3558"/>',
         f'<text x="{pad}" y="40" font-size="13" fill="{BLUE}" letter-spacing="2">PROJECTS.LIST</text>',
         f'<text x="{pad + 150}" y="40" font-size="11" fill="{MUTED}">./projects.sh --all</text>',
         f'<text x="{w - pad}" y="40" font-size="11" fill="{MUTED}" text-anchor="end">{len(shown)} projects</text>',
         f'<path d="M{pad} 52H{w - pad}" stroke="#1f3558"/>']
    for i, r in enumerate(shown):
        x, y = pad + (i % 2) * (cw + gap), 68 + (i // 2) * (ch + gap)
        lang = (r["primaryLanguage"] or {}).get("name", "")
        total = sum(r["langs"].values()) or 1
        pct = round(100 * r["langs"].get(lang, 0) / total) if lang else 0
        color = LANG_COLORS.get(lang, BLUE)
        desc = wrap(r["description"] or "No description yet.", 40, 2)
        b.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="10" fill="#0a0e14" stroke="#243a5e"/>'
                 f'<text x="{x + 14}" y="{y + 20}" font-size="10" fill="{MUTED}">• {LOGIN}/{esc(r["name"])}</text>'
                 f'<circle cx="{x + cw - 16}" cy="{y + 16}" r="4" fill="{GREEN}"/>'
                 f'<path d="M{x} {y + 30}H{x + cw}" stroke="#1b2a45"/>'
                 f'<text x="{x + 14}" y="{y + 54}" font-size="15" font-weight="bold" fill="{FG}">{esc(r["name"])} <tspan fill="{BLUE}">_</tspan></text>')
        for j, line in enumerate(desc):
            b.append(f'<text x="{x + 14}" y="{y + 74 + j * 14}" font-size="10.5" fill="{MUTED}">{esc(line)}</text>')
        if lang:
            b.append(donut(x + cw - 44, y + 76, pct, color))
            b.append(f'<rect x="{x + 14}" y="{y + 100}" width="{len(lang) * 6.5 + 20}" height="18" rx="9" fill="#101826" stroke="#243a5e"/>'
                     f'<text x="{x + 24}" y="{y + 112}" font-size="9.5" fill="{BLUE}">{esc(lang)}</text>')
    return w, h, svg(w, h, "".join(b))


def neofetch(user, stars, contribs, top_lang, art):
    cw, lh, fs = 6.6, 12, 11
    ox, oy = 28, 66
    w = 880
    h = oy + len(art) * lh + 60
    an = Reveal(16)
    rows = []
    for i, row in enumerate(art):
        chars = "".join(f'<text x="{ox + j * cw:.1f}" y="{oy + 8 + i * lh}" fill="{col}">{esc(ch)}</text>'
                        for j, (ch, col) in enumerate(row) if ch != " ")
        rows.append(f'<g class="{an.cls(0.3 + i * 0.05, 0.3)}">{chars}</g>')
    inner = f'<g font-size="{fs}">{"".join(rows)}</g>'
    ix = ox + len(art[0]) * cw + 40
    info = [("OS", "GitHub public cloud"), ("Host", f"{LOGIN}"), ("Name", NAME), ("Role", ROLE),
            ("Location", LOCATION), ("Repos", user["public_repos"]), ("Stars", stars),
            ("Followers", user["followers"]), ("Top Lang", top_lang), ("Activity", f"{contribs} contributions"),
            ("Shell", "spring-boot · react · postgres")]
    y0 = oy + 20
    inner += (f'<g class="{an.cls(0.8, 0.9, "type", len(LOGIN) + 7)}"><text x="{ix}" y="{y0}" font-size="16"><tspan fill="{BLUE}" font-weight="bold">{LOGIN.lower()}</tspan>'
              f'<tspan fill="{MUTED}">@github</tspan></text>'
              f'<path d="M{ix} {y0 + 10}H{w - 28}" stroke="{BORDER}"/></g>')
    for i, (k, v) in enumerate(info):
        yy = y0 + 36 + i * 24
        n = len(k) + len(str(v)) + 8
        inner += (f'<g class="{an.cls(1.8 + i * 0.4, 0.5, "type", n)}"><text x="{ix}" y="{yy}" font-size="14" fill="{BLUE}" font-weight="bold">{k}</text>'
                  f'<text x="{ix + 110}" y="{yy}" font-size="14" fill="{FG}">{esc(v)}</text></g>')
    py = y0 + 36 + len(info) * 24 + 14
    h = max(h, py + 76)
    sw = "".join(f'<rect x="{ix + i * 30}" y="{py}" width="24" height="16" rx="3" fill="{c}"/>'
                 for i, c in enumerate(["#f85149", GREEN, "#d29922", BLUE, "#a371f7", "#22d3ee", FG, MUTED]))
    inner += f'<g class="{an.cls(6.4, 0.6)}">{sw}</g>'
    prompt = f"{LOGIN.lower()}@github ~ $ cat README.md"
    inner += (f'<text class="{an.cls(7.4, 1.6, "type", len(prompt))}" x="{ix}" y="{py + 52}" font-size="14"><tspan fill="{GREEN}" font-weight="bold">{LOGIN.lower()}@github</tspan>'
              f'<tspan fill="{FG}"> ~ $ </tspan><tspan fill="{MUTED}">cat README.md</tspan></text>'
              f'<g class="{an.cls(9.0, 0.1)}"><text x="{ix + len(prompt) * 8.4 + 6:.0f}" y="{py + 52}" font-size="14" fill="{BLUE}" class="cur">█</text></g>')
    style = an.style("@keyframes b{0%,49%{opacity:1}50%,100%{opacity:0}}.cur{animation:b 1s steps(1) infinite}")
    return w, h, svg(w, h, window(w, h, f"{LOGIN.lower()}@github: ~$ neofetch", inner), style)


def activity(cal):
    cell, gap, left, top = 11, 3, 40, 92
    weeks = cal["weeks"]
    w = left * 2 + len(weeks) * (cell + gap)
    h = top + 7 * (cell + gap) + 40
    mx = max((d["contributionCount"] for wk in weeks for d in wk["contributionDays"]), default=1) or 1
    pal = ["#161b22", "#1b3556", "#24558f", "#3b82d6", "#58a6ff"]
    an = Reveal(12)
    b = [f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="{CARD}" stroke="#1f3558"/>',
         f'<text class="{an.cls(0.2, 1.0, "type", 21)}" x="{left}" y="46" font-size="22" font-weight="bold" fill="{FG}">Contribution Activity</text>',
         f'<text class="{an.cls(1.2, 0.5)}" x="{left}" y="68" font-size="12" fill="{MUTED}">{cal["totalContributions"]} contributions in the last year</text>',
         f'<g class="{an.cls(1.4, 0.5)}"><text x="{w - left - 150}" y="62" font-size="11" fill="{MUTED}">Less</text>']
    for i, c in enumerate(pal):
        b.append(f'<rect x="{w - left - 120 + i * 16}" y="52" width="11" height="11" rx="2" fill="{c}"/>')
    b.append(f'<text x="{w - left - 34}" y="62" font-size="11" fill="{MUTED}">More</text></g>')
    for i, wk in enumerate(weeks):
        b.append(f'<g class="{an.cls(1.6 + i * 0.1, 0.45)}">')
        for d in wk["contributionDays"]:
            n = d["contributionCount"]
            lvl = 0 if n == 0 else min(4, 1 + int(3 * n / mx))
            dow = datetime.strptime(d["date"], "%Y-%m-%d").weekday()
            row = (dow + 1) % 7  # Sunday first
            b.append(f'<rect x="{left + i * (cell + gap)}" y="{top + row * (cell + gap)}" width="{cell}" height="{cell}" rx="2.5" fill="{pal[lvl]}"/>')
        b.append("</g>")
    return w, h, svg(w, h, "".join(b), an.style())


def footer():
    w, h = 820, 120
    body = (f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="{CARD}" stroke="#1f3558"/>'
            f'<rect x="{w / 2 - 110}" y="34" width="220" height="52" rx="26" fill="#0a0e14" stroke="#4b5b78" stroke-width="1.5"/>'
            f'<circle cx="{w / 2 - 80}" cy="60" r="13" fill="#1c2330"/>'
            f'<text x="{w / 2 - 80}" y="65" text-anchor="middle" font-size="14" font-weight="bold" fill="{FG}">G</text>'
            f'<text x="{w / 2 - 56}" y="55" font-size="10" fill="{MUTED}">GitHub</text>'
            f'<text x="{w / 2 - 56}" y="72" font-size="13" font-weight="bold" fill="{FG}">@{LOGIN}</text>')
    return w, h, svg(w, h, body)


# ---------- README ----------
def readme(sizes, top_langs, projects_rows):
    def img(name, alt, width=None):
        w = f' width="{width}"' if width else ""
        v = f"?v={VERSIONS[name]}" if name in VERSIONS else ""  # cache-bust: GitHub caches images ~5 min
        return f'<img src="assets/{name}.svg{v}" alt="{alt}"{w}/>'

    pct = " | ".join(f"**{l}**<br/>{p}%" for l, p in top_langs)
    sep = " | ".join("---" for _ in top_langs)
    return f"""<div align="center">

<code>{LOGIN.lower()}@github ~ $ neofetch --live</code>

{img("portrait", "Portrait", 760)}

{img("identity", "Identity and telemetry", 380)}

● **ONLINE** · {ROLE} in {LOCATION}. Building AI-powered products with Spring Boot, React and PostgreSQL.

</div>

## `$ tail -n 5 /var/log/build.log`

```text
[ok] identity loaded: {NAME}
[ok] role detected: {ROLE}
[ok] experience: 5 years of enterprise apps, teams of 5-7, 10+ developers mentored
[ok] primary stack: Spring Boot · React · Next.js · TypeScript · PostgreSQL
[run] Building AI-powered products on my own.
```

[Portfolio](https://ahmad-kanaan.vercel.app) · [Blog](https://ahmadkanaan.hashnode.dev)

## `$ git launchpad --all`

<div align="center">

{img("projects", "Projects")}

</div>

| Project | What it does | Stack |
|---|---|---|
{projects_rows}

## `$ which --all toolchain`

<div align="center">

{img("skills", "Skills")}

| {pct} |
| {sep} |

</div>

## `$ cat highlights.md`

- Built an OpenAI automation pipeline that cut manual development time by 20%.
- Led 3 high-profile projects to delivery with 95%+ client satisfaction.
- Shipped React Native apps to both the App Store and Google Play.
- Wrote the Spring Boot and React training curriculum and ran workshops for 15+ people.

## `$ git status --short`

<div align="center">

**working tree: clean · shipping consistently**

{img("neofetch", "neofetch")}

</div>

## `$ git log --graph --all`

<div align="center">

{img("activity", "Contribution activity")}

</div>

## `$ ssh {LOGIN.lower()}@github`

Off the keyboard: UI/UX design, 3D modeling, chess, reading manga. Languages: English, French, Arabic.

<div align="center">

{img("footer", "GitHub footer")}

</div>
"""


FEATURED = {
    "Nebula": ("https://nebula-gamma-inky.vercel.app", "AI agent control center. Create, configure and monitor LLM agents across OpenAI and Gemini, with live token, latency and cost metrics.", "Next.js, Node/TypeScript, PostgreSQL, WebSocket, Docker"),
    "notioncraft-ai": ("https://notioncraft-ai.vercel.app", "A Notion-style document editor with an inline Gemini writing assistant and real-time collaboration.", "Next.js, Vercel AI SDK, Supabase, Drizzle, Yjs"),
    "PortaGen": ("https://porta-gen.vercel.app", "Portfolio generator with a live editor and a component-first architecture.", "Next.js, TypeScript, Drizzle, PostgreSQL"),
}


def main():
    ASSETS.mkdir(exist_ok=True)
    user, repos, cal = load_data()
    stars = sum(r["stargazerCount"] for r in repos)
    contribs = cal["totalContributions"]
    agg = Counter()
    for r in repos:
        agg.update(r["langs"])
    total = sum(agg.values()) or 1
    top_langs = [(l, round(100 * n / total)) for l, n in agg.most_common(6)]
    top_lang = top_langs[0][0] if top_langs else "n/a"

    # most recently pushed first so the launchpad shows current work
    repos.sort(key=lambda r: (r["name"] not in FEATURED, r["updatedAt"]), reverse=False)
    repos = sorted(repos, key=lambda r: (r["name"] not in FEATURED, r["name"]))

    art = ascii_art(user["avatar_url"])
    cards = {
        "portrait": portrait(user["avatar_url"]),
        "identity": identity(user, stars, contribs, longest_streak(cal)),
        "skills": skills(SKILL_GROUPS),
        "projects": projects(repos),
        "neofetch": neofetch(user, stars, contribs, top_lang, art),
        "activity": activity(cal),
        "footer": footer(),
    }
    for name, (w, h, content) in cards.items():
        (ASSETS / f"{name}.svg").write_text(content, encoding="utf-8")
        VERSIONS[name] = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]

    rows = "\n".join(
        f"| [**{n}**](https://github.com/{LOGIN}/{n}) ([live]({u})) | {d} | {s} |"
        for n, (u, d, s) in FEATURED.items()
    )
    (ROOT / "README.md").write_text(readme({k: (v[0], v[1]) for k, v in cards.items()}, top_langs, rows),
                                    encoding="utf-8")
    print("built", ", ".join(cards), "at", datetime.now(timezone.utc).isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
