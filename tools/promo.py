"""Build docs/scenes.png (a strip of every scene) and docs/social-preview.png (GitHub's 1280x640 card)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
A, D = ROOT / 'assets', ROOT / 'docs'
SCENES = [('night-idle', 30, 'night · idle'), ('night-done', 12, 'night · answered'), ('night-storm', 10, 'night · tool failed'),
          ('day-idle', 8, 'day · idle'), ('day-clear', 22, 'after the storm'), ('dusk', 14, 'dusk')]


def frame(name, k, size):
    g = Image.open(A / f'{name}.gif')
    g.seek(min(k, g.n_frames - 1))
    return g.convert('RGB').resize(size)


def font(px, bold=False):
    for f in (['segoeuib.ttf', 'arialbd.ttf'] if bold else ['segoeui.ttf', 'arial.ttf']):
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            pass
    return ImageFont.load_default()


def scenes():
    tw, th, gap = 400, 225, 12
    sheet = Image.new('RGB', (3 * tw + 4 * gap, 2 * th + 3 * gap + 2 * 34), (13, 17, 23))
    d = ImageDraw.Draw(sheet)
    for i, (n, k, label) in enumerate(SCENES):
        x, y = gap + (i % 3) * (tw + gap), gap + (i // 3) * (th + 34 + gap)
        sheet.paste(frame(n, k, (tw, th)), (x, y))
        d.text((x + 4, y + th + 6), label, fill=(200, 208, 220), font=font(20))
    sheet.save(D / 'scenes.png', optimize=True)


def social():
    img = frame('night-busy', 12, (1280, 640))
    shade = Image.new('RGB', img.size, (0, 0, 0))
    img = Image.blend(img, shade, 0.25)
    d = ImageDraw.Draw(img)
    d.text((80, 200), 'living-sky', fill=(245, 245, 255), font=font(110, True))
    d.text((84, 345), 'An animated sky behind Windows Terminal', fill=(215, 222, 240), font=font(40))
    d.text((84, 397), 'that reacts to Claude Code as it works.', fill=(215, 222, 240), font=font(40))
    d.text((84, 480), 'stars at night  ·  clouds by day  ·  meteors while it works  ·  a storm on errors  ·  sunrise when done',
           fill=(170, 180, 205), font=font(22))
    img.save(D / 'social-preview.png', optimize=True)


D.mkdir(exist_ok=True)
scenes()
social()
print('ok')
