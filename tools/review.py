"""Look at every scene the way Windows Terminal will show it.

Windows Terminal scales the image to cover the window (uniformToFill), crops what
spills over (centred), and blends it with the profile's background colour at the
scene's opacity. This renders that, for several window shapes, with terminal text
on top, so composition (is the moon cut off?) and legibility can be judged.

    python tools/review.py            # writes docs/review/*.png
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
A, OUT = ROOT / 'assets', ROOT / 'docs' / 'review'
BG = (12, 12, 12)  # Windows Terminal's default (Campbell) background

# window shapes people really use, in pixels
WINDOWS = {
    'full 16:9': (1920, 1040),
    'wide, short': (1117, 409),   # a terminal docked under an editor
    'split pane': (960, 1040),
    'ultrawide': (2560, 1080),
    'laptop': (1366, 700),
}
OPACITY = {
    'night-idle': 0.75, 'night-busy': 0.75, 'night-storm': 0.55, 'night-clear': 0.75,
    'night-done': 0.75, 'day-idle': 0.32, 'day-busy': 0.32, 'day-storm': 0.4, 'day-clear': 0.32, 'day-done': 0.32,
    'dawn': 0.5, 'dusk': 0.5,
}
TEXT = [
    ('PS C:\\Users\\you> claude', (204, 204, 204)),
    ('* Coalescing... (3s . thinking)', (215, 119, 87)),
    ('  Read(src/app.ts)  Bash(npm test)', (150, 150, 150)),
    ('  14 passed, 0 failed', (19, 161, 14)),
    ('> _', (204, 204, 204)),
]


def font(px):
    for f in ('consola.ttf', 'cour.ttf'):
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            pass
    return ImageFont.load_default()


def frame(scene, k):
    g = Image.open(A / f'{scene}.gif')
    g.seek(min(k, g.n_frames - 1) if k >= 0 else g.n_frames - 1)
    return g.convert('RGB')


def as_terminal(img, size, opacity):
    W, H = size
    s = max(W / img.width, H / img.height)  # uniformToFill: cover, then crop centred
    big = img.resize((round(img.width * s), round(img.height * s)))
    x, y = (big.width - W) // 2, (big.height - H) // 2
    shown = Image.blend(Image.new('RGB', size, BG), big.crop((x, y, x + W, y + H)), opacity)
    d = ImageDraw.Draw(shown)
    f = font(max(12, H // 40))
    for i, (line, col) in enumerate(TEXT):
        d.text((12, 10 + i * (f.size + 6)), line, fill=col, font=f)
    return shown


def sheet(scenarios, path, tile=(480, 270)):
    cols = 3
    rows = (len(scenarios) + cols - 1) // cols
    lab = 22
    out = Image.new('RGB', (cols * (tile[0] + 10) + 10, rows * (tile[1] + lab + 10) + 10), (30, 30, 36))
    d = ImageDraw.Draw(out)
    for i, (label, scene, k, win) in enumerate(scenarios):
        size = WINDOWS[win]
        img = as_terminal(frame(scene, k), size, OPACITY[scene])
        img.thumbnail(tile)
        x, y = 10 + (i % cols) * (tile[0] + 10), 10 + (i // cols) * (tile[1] + lab + 10)
        out.paste(img, (x, y))
        d.text((x, y + img.height + 3), f'{i + 1}. {label}  [{win}]', fill=(220, 220, 230), font=font(15))
    out.save(path)
    print(path.name)


def luminance(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def legibility(scene, k, win):
    # text ends up anywhere as output scrolls: measured against the brightest tenth of
    # the whole window (the sun's own disc may be brighter; it is that small).
    # WCAG asks 4.5 of body text and 3.0 of secondary text; Claude's dim lines are secondary.
    W, H = WINDOWS[win]
    img = as_terminal(frame(scene, k), (W, H), OPACITY[scene]).resize((160, 90))
    px = sorted(img.get_flattened_data() if hasattr(img, 'get_flattened_data') else img.getdata(), key=luminance)
    bright = px[int(len(px) * 0.9)]
    return contrast((204, 204, 204), bright), contrast((150, 150, 150), bright)


def seam(a, b):
    from PIL import ImageChops, ImageStat
    x, y = frame(a, -1), frame(b, 0)
    if x.size != y.size:
        y = y.resize(x.size)
    return sum(ImageStat.Stat(ImageChops.difference(x, y)).mean) / 3


SEAMS = [('night-clear', 'night-idle'), ('night-done', 'night-idle'), ('day-clear', 'day-idle'), ('day-done', 'day-idle')]


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    from scenarios import SCENARIOS  # noqa: E402  (tools/scenarios.py: the list under review)
    for n, chunk in enumerate([SCENARIOS[i:i + 9] for i in range(0, len(SCENARIOS), 9)], 1):
        sheet(chunk, OUT / f'review-{n}.png')
    print('\nlegibility (WCAG contrast; body text needs 4.5, dim secondary text 3.0):')
    low = 0
    for label, scene, k, win in SCENARIOS:
        body, dim = legibility(scene, k, win)
        ok = body >= 4.5 and dim >= 3.0
        low += not ok
        print(f'  body {body:5.2f}  dim {dim:5.2f}  {"ok " if ok else "LOW"}  {label} [{win}]')
    print(f'  {len(SCENARIOS) - low}/{len(SCENARIOS)} pass')
    print('\nseams (mean difference /255 where the plugin cuts without a fade):')
    for a, b in SEAMS:
        print(f'  {seam(a, b):5.2f}  {a} -> {b}')
    # busy starts where idle starts
    for p in ('night', 'day'):
        from PIL import ImageChops, ImageStat
        x, y = frame(f'{p}-idle', 0), frame(f'{p}-busy', 0)
        print(f'  {sum(ImageStat.Stat(ImageChops.difference(x, y)).mean) / 3:5.2f}  {p}-idle[0] ~ {p}-busy[0]')
