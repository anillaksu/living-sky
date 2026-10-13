"""Generate living-sky's animated backgrounds (assets/*.gif).

Every scene is procedural and seeded, so the output is reproducible:

    pip install pillow
    python tools/generate.py            # all scenes
    python tools/generate.py night-done # one scene

Scenes
    night-idle   twinkling stars around the moon, a slow shooting star or two
    night-busy   Claude is working: faster twinkle, a meteor shower
    night-storm  a tool failed: clouds roll in, lightning, rain
    night-clear  after the storm: the clouds part, the rain stops, the stars come back
    night-done   a turn finished: a golden comet crosses and the stars flare
    day-idle     clouds drift past the sun
    day-busy     Claude is working: the same clouds, racing
    day-storm    a tool failed: grey sky, lightning, rain
    day-clear    after the storm: the clouds part and the sun climbs back
    day-done     a turn finished: the sun flares and a flock of birds flies by
    dawn         night turns to day (at the hour you set): the sun rises over the hills
    dusk         day turns to night: the sun sets and the first stars appear

Composition rules (checked by tools/review.py)
    Windows Terminal crops the image to the window (uniformToFill), so anything that
    matters sits in the SAFE zone that survives every common window shape, from a
    split pane (crops the sides) to a wide, short panel (crops top and bottom), and
    away from the top-left, where the terminal's text is. The moon and the sun live at
    FOCAL, upper right of the safe zone.

    The one-shot scenes (clears, dones, dawn, dusk) hold their last frame instead of
    looping. Each clear and each done ends on exactly the first frame of its calm
    scene, and busy starts where idle starts, so the plugin cuts between them with no
    seam.
"""

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / 'assets'
TAU = 2 * math.pi
SAFE = (0.26, 0.20, 0.74, 0.80)  # x0, y0, x1, y1 as fractions
FOCAL = (0.64, 0.32)
HOLD = 60_000  # ms a one-shot scene rests on its last frame


# ---------- shared pieces ----------

def gradient(w, h, top, bottom):
    img = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=lerp_rgb(top, bottom, t))
    return img


def lerp_rgb(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def save_gif(frames, name, ms, hold_last=0, dither=False):
    # one palette for the whole loop, sampled across it: a palette taken from the
    # first frame alone has no room for a lightning flash or a rising sun
    step = max(1, len(frames) // 24)
    sample = [f.resize((f.width // 4, f.height // 4)) for f in frames[::step]] + [frames[-1].resize((frames[-1].width // 4, frames[-1].height // 4))]
    sheet = Image.new('RGB', (sample[0].width * len(sample), sample[0].height))
    for i, f in enumerate(sample):
        sheet.paste(f, (i * f.width, 0))
    palette = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    # soft day gradients band into rings without dithering; the night's dark ones do not
    gif = [f.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE) for f in frames]
    durations = [ms] * len(gif)
    if hold_last:
        durations[-1] = hold_last
    path = OUT / f'{name}.gif'
    gif[0].save(path, save_all=True, append_images=gif[1:], duration=durations, loop=0, optimize=True)
    print(f'{name:12} {len(frames):3} frames  {path.stat().st_size // 1024:5} KB')


def cloud_mask(w, h, seed, count, scale, top=0.05, bottom=0.7, pad=0, blur=14, lo=150, hi=220):
    rnd = random.Random(seed)
    m = Image.new('L', (w + 2 * pad, h), 0)
    d = ImageDraw.Draw(m)
    for _ in range(count):
        cx, cy = rnd.uniform(0, w + 2 * pad), rnd.uniform(h * top, h * bottom)
        for _ in range(9):
            rx, ry = rnd.uniform(30, 80) * scale, rnd.uniform(15, 35) * scale
            x, y = cx + rnd.uniform(-90, 90) * scale, cy + rnd.uniform(-18, 18) * scale
            d.ellipse([x - rx, y - ry, x + rx, y + ry], fill=rnd.randint(lo, hi))
    return m.filter(ImageFilter.GaussianBlur(blur))


def rain(img, k, frames, seed, n, color, length):
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img)
    w, h = img.size
    for _ in range(n):
        x0, y0, v = rnd.uniform(-60, w), rnd.uniform(0, h), rnd.choice((1, 2))
        y = (y0 + h * v * k / frames) % h  # whole laps per loop keeps the GIF seamless
        x = x0 + 0.25 * (y - y0)
        d.line([(x, y), (x + length * 0.25, y + length)], fill=color, width=1)


def glow(size, x, y, r, blur):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).ellipse([x - r, y - r, x + r, y + r], fill=255)
    return m.filter(ImageFilter.GaussianBlur(blur))


def hills(size, horizon):
    w, h = size
    m = Image.new('L', size, 0)
    pts = [(x, h * horizon + h * 0.025 * math.sin(x / w * 9) + h * 0.015 * math.sin(x / w * 23)) for x in range(0, w + 1, 8)]
    ImageDraw.Draw(m).polygon([(0, h)] + pts + [(w, h)], fill=255)
    return m


# ---------- night (full HD: only stars change between frames, so it compresses well) ----------

W, H = 1920, 1080
MOON = (int(W * FOCAL[0]), int(H * FOCAL[1]))


def night_base(seed=7):
    rnd = random.Random(seed)
    img = gradient(W, H, (3, 6, 20), (14, 24, 52))
    haze = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(haze)
    for _ in range(260):  # the milky way: a faint diagonal band
        x = rnd.uniform(0, W)
        y = H * 0.85 - x * 0.55 + rnd.gauss(0, 70)
        r = rnd.uniform(30, 90)
        d.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(6, 16))
    img = Image.composite(Image.new('RGB', (W, H), (70, 80, 130)), img, haze.filter(ImageFilter.GaussianBlur(40)))
    mx, my = MOON
    img = Image.composite(Image.new('RGB', (W, H), (60, 70, 110)), img, glow((W, H), mx, my, 90, 60))  # moonlight
    moon = Image.new('L', (W, H), 0)
    dm = ImageDraw.Draw(moon)
    dm.ellipse([mx - 62, my - 62, mx + 62, my + 62], fill=240)
    dm.ellipse([mx - 28, my - 78, mx + 96, my + 46], fill=0)
    img.paste((238, 234, 212), mask=moon.filter(ImageFilter.GaussianBlur(1.2)))
    return img


def star_field(seed=7):
    rnd = random.Random(seed * 31)
    stars = []
    while len(stars) < 900:
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        if math.hypot(x - MOON[0], y - MOON[1]) < 110:  # no star in front of the moon
            continue
        stars.append({'x': x, 'y': y, 'p': rnd.random() ** 3, 'phase': rnd.uniform(0, TAU), 'twinkles': rnd.random() < 0.6,
                      'tone': rnd.choice([(1, 1, 1), (0.92, 0.95, 1), (1, 0.95, 0.88)])})
    bright = []
    while len(bright) < 30:
        x, y = rnd.uniform(30, W - 30), rnd.uniform(30, H - 30)
        if math.hypot(x - MOON[0], y - MOON[1]) > 140:
            bright.append({'x': x, 'y': y, 'phase': rnd.uniform(0, TAU)})
    return stars, bright


def draw_stars(img, k, frames, stars, bright, speed, reveal=1.0, boost=0.0):
    # reveal < 1 lights the stars one by one (each has its own moment), as after a storm;
    # boost > 0 makes every star flare, as when a comet passes
    d = ImageDraw.Draw(img)
    a = TAU * speed * k / frames
    for s in stars:
        lum = (110 + 145 * s['p']) * min(1.0, max(0.0, (reveal - s['phase'] / TAU * 0.8) / 0.2))
        if lum <= 0:
            continue
        if s['twinkles']:
            lum *= 0.2 + 0.8 * (0.5 + 0.5 * math.sin(a + s['phase'])) ** 2
        lum = min(255, lum * (1 + boost))
        r = (0.6 + 1.6 * s['p']) * (1 + 0.5 * boost)
        d.ellipse([s['x'] - r, s['y'] - r, s['x'] + r, s['y'] + r], fill=tuple(int(min(255, lum * c)) for c in s['tone']))
    for b in bright:  # pulsing stars with a cross-shaped glint
        if reveal < 1 and reveal < 0.4 + b['phase'] / TAU * 0.6:
            continue
        n = min(1.0, (0.5 + 0.5 * math.sin(a + b['phase'])) ** 2 + boost)
        c = int(150 + 105 * n)
        r = 1.5 + 1.5 * n
        d.ellipse([b['x'] - r, b['y'] - r, b['x'] + r, b['y'] + r], fill=(c, c, 255))
        arm = 4 + 14 * n
        col = (int(70 + 120 * n), int(75 + 120 * n), int(110 + 130 * n))
        d.line([(b['x'] - arm, b['y']), (b['x'] + arm, b['y'])], fill=col)
        d.line([(b['x'], b['y'] - arm), (b['x'], b['y'] + arm)], fill=col)


def meteor(img, t, x0, y0, dx, dy, trail=24, width=3, color=(255, 255, 255)):
    d = ImageDraw.Draw(img)
    x, y = x0 + dx * t, y0 + dy * t
    sx, sy = dx / max(abs(dx), 1) * 11, dy / max(abs(dx), 1) * 11
    for i in range(trail):
        a = (1 - i / trail) * (1 - 0.5 * t)
        c = tuple(int(v * a) for v in color)
        d.line([(x - i * sx, y - i * sy), (x - (i + 1) * sx, y - (i + 1) * sy)], fill=c, width=width if i < 4 else max(1, width - 1))


class Night:
    def __init__(self):
        self.base = night_base()
        self.stars, self.bright = star_field()

    def frame(self, k, frames=48, speed=1, reveal=1.0, boost=0.0):
        img = self.base.copy()
        draw_stars(img, k, frames, self.stars, self.bright, speed, reveal, boost)
        return img


def night_loop(frames, ms, meteors, speed, name):
    n = Night()
    out = []
    for k in range(frames):
        img = n.frame(k, frames, speed)
        for start, dur, x0, y0, dx, dy in meteors:
            if start <= k <= start + dur:
                meteor(img, (k - start) / dur, x0, y0, dx, dy)
        out.append(img)
    save_gif(out, name, ms)


def night_idle():
    # the meteors cross the lower half, clear of the text at the top left
    night_loop(48, 110, [(6, 9, 600, 520, 640, 280), (28, 9, 1150, 300, 420, 200)], 1, 'night-idle')


def night_busy():
    rnd = random.Random(3)
    shower = [(2 + i * 4 + rnd.randint(0, 2), 6, rnd.uniform(350, 1400), rnd.uniform(160, 560),
               rnd.uniform(420, 620), rnd.uniform(180, 280)) for i in range(9)]
    night_loop(40, 90, shower, 2, 'night-busy')


def night_done():
    # a golden comet rises across the safe zone while every star flares, then all
    # settles back to night-idle's first frame
    n = Night()
    frames = 28
    out = []
    for k in range(frames):
        t = k / (frames - 1)
        boost = 0.8 * math.sin(math.pi * t) ** 2
        img = n.frame(0, reveal=1.0, boost=boost) if k < frames - 1 else n.frame(0)
        if k < frames - 1:
            ct = ease(t / 0.85)
            hx, hy = W * (0.30 + 0.62 * ct), H * (0.72 - 0.42 * ct)
            halo = glow((W, H), hx, hy, 26, 22)
            img = Image.composite(Image.new('RGB', (W, H), (255, 214, 140)), img, halo.point(lambda v: int(v * (1 - 0.7 * ct))))
            meteor(img, 0, hx, hy, W * 0.62, -H * 0.42, trail=34, width=5, color=(255, 226, 160))
        out.append(img)
    save_gif(out, 'night-done', 110, hold_last=HOLD)


# ---------- day (960x540: soft shapes, scaled up by the terminal) ----------

w, h = 960, 540
SUN = (int(w * FOCAL[0]), int(h * FOCAL[1]))
DAY_PAD = 160


class Day:
    def __init__(self):
        self.sky = gradient(w, h, (40, 110, 190), (132, 182, 226))
        self.far = cloud_mask(w, h, 5, 8, 0.7, top=0.15, bottom=0.8, pad=DAY_PAD)
        self.near = cloud_mask(w, h, 11, 7, 1.0, top=0.25, bottom=0.85, pad=DAY_PAD)
        # clouds a pale blue rather than white: bright enough to read as clouds, not so
        # bright that they fight the terminal's text (tools/review.py measures it)
        self.white = Image.new('RGB', (w, h), (200, 220, 240))
        self.warm = Image.new('RGB', (w, h), (255, 236, 186))

    def frame(self, a, amp_far=24, amp_near=50, clouds=1.0, sun_y=None, flare=0.0):
        sx, sy = SUN[0], SUN[1] if sun_y is None else sun_y
        img = self.sky.copy()
        r = 34 + 4 * math.sin(a) + 30 * flare
        img = Image.composite(self.warm, img, glow((w, h), sx, sy, r * 2.2, 40).point(lambda v: int(v * 0.6)))
        if flare:  # slow-turning rays
            rays = Image.new('L', (w, h), 0)
            d = ImageDraw.Draw(rays)
            for i in range(12):
                ang = TAU * i / 12 + flare * 0.6
                d.polygon([(sx, sy), (sx + 320 * math.cos(ang - 0.05), sy + 320 * math.sin(ang - 0.05)),
                           (sx + 320 * math.cos(ang + 0.05), sy + 320 * math.sin(ang + 0.05))], fill=int(60 * flare))
            img = Image.composite(self.warm, img, rays.filter(ImageFilter.GaussianBlur(8)))
        img = Image.composite(self.warm, img, glow((w, h), sx, sy, 26 + 6 * flare, 3))
        for layer, amp, alpha in ((self.far, amp_far, 0.45), (self.near, amp_near, 0.7)):
            dx = int(DAY_PAD + amp * math.sin(a))
            img = Image.composite(self.white, img, layer.crop((dx, 0, dx + w, h)).point(lambda v: int(v * alpha * clouds)))
        return img


def day_loop(frames, ms, amp_far, amp_near, name):
    d = Day()
    save_gif([d.frame(TAU * k / frames, amp_far, amp_near) for k in range(frames)], name, ms, dither=True)


def day_idle():
    day_loop(32, 140, 24, 50, 'day-idle')


def day_busy():
    # the same clouds as idle, swinging wider and faster: frame 0 is idle's frame 0
    day_loop(24, 90, 70, 140, 'day-busy')


def birds(img, t, n=5):
    d = ImageDraw.Draw(img)
    for i in range(n):
        x = -60 + (w + 160) * t - i * 26 - (i % 2) * 10
        y = h * 0.52 - i * 7 + (i % 2) * 14 + 4 * math.sin(t * 30 + i)
        flap = 5 * math.sin(t * 40 + i * 1.7)
        d.line([(x - 9, y - flap), (x, y), (x + 9, y - flap)], fill=(30, 40, 60), width=2)


def day_done():
    d = Day()
    frames = 30
    out = []
    for k in range(frames):
        t = k / (frames - 1)
        if k == frames - 1:
            out.append(d.frame(0))
            break
        img = d.frame(0, flare=math.sin(math.pi * t) ** 2)
        birds(img, t)
        out.append(img)
    save_gif(out, 'day-done', 100, hold_last=HOLD, dither=True)


# ---------- storms and what comes after ----------

STORM_PAD = 60
STORMS = {
    'night': dict(top=(8, 10, 22), bottom=(22, 26, 44), cloud=(34, 38, 56), rain=(120, 130, 160), flash=(150, 160, 210)),
    'day': dict(top=(62, 70, 86), bottom=(110, 118, 132), cloud=(52, 58, 70), rain=(170, 180, 195), flash=(225, 230, 250)),
}


def storm_layers(kind, size=None):
    size = size or (w, h)
    c = STORMS[kind]
    mass = cloud_mask(w, h, 21, 14, 1.4, top=-0.1, bottom=0.55, pad=STORM_PAD, blur=18, lo=170, hi=245)
    return {
        'sky': gradient(*size, c['top'], c['bottom']),
        'mass': mass,  # wider than the frame by STORM_PAD each side: the storm sways in it
        'still': mass.crop((STORM_PAD, 0, STORM_PAD + w, h)).resize(size),
        'dark': Image.new('RGB', size, c['cloud']),
        'flash': Image.new('RGB', size, c['flash']),
        'rain': c['rain'],
    }


def storm(kind, name):
    frames = 24
    L = storm_layers(kind)
    rnd = random.Random(9)
    bolt = [(rnd.uniform(w * 0.5, w * 0.7), h * 0.08)]
    while bolt[-1][1] < h * 0.7:
        x, y = bolt[-1]
        bolt.append((x + rnd.uniform(-30, 30), y + rnd.uniform(22, 40)))
    out = []
    for k in range(frames):
        dx = int(STORM_PAD + 20 * math.sin(TAU * k / frames))
        img = Image.composite(L['dark'], L['sky'], L['mass'].crop((dx, 0, dx + w, h)))
        rain(img, k, frames, 4, 420, L['rain'], 16)
        if k in (5, 6, 15):  # the sky lights up and a bolt forks down
            img = Image.blend(img, L['flash'], 0.3 if k != 6 else 0.15)
            d = ImageDraw.Draw(img)
            d.line(bolt, fill=(255, 255, 240), width=3)
            d.line([(x + 1, y) for x, y in bolt[:6]], fill=(200, 210, 255), width=1)
        out.append(img)
    save_gif(out, name, 90)


def shift(img, dx):
    out = Image.new(img.mode, img.size, 0)
    out.paste(img, (dx, 0))
    return out


def parted(mass, t):
    # the cloud mass tears in two halves that drift apart and thin out; the tear is a
    # wide soft band, not a cut, so no straight edge ever shows
    W2, H2 = mass.size
    band = W2 * 0.18
    ramp = Image.new('L', (W2, 1))
    ramp.putdata([int(255 * min(1.0, max(0.0, (x - (W2 / 2 - band)) / (2 * band)))) for x in range(W2)])
    right_w = ramp.resize((W2, H2))
    split = int(W2 * 0.7 * ease(t))
    out = ImageChops.lighter(shift(ImageChops.multiply(mass, right_w.point(lambda v: 255 - v)), -split),
                             shift(ImageChops.multiply(mass, right_w), split))
    return out.point(lambda v: int(v * (1 - ease(t)) ** 0.8))


def clear(kind, size, target, name, frames=34, ms=100, dither=False):
    # storm -> calm: the clouds part, the rain eases off, the calm sky comes through
    L = storm_layers(kind, size)
    out = []
    for k in range(frames):
        t = k / (frames - 1)
        calm = target(t)
        if k == frames - 1:
            out.append(calm)  # the calm scene's own first frame: the plugin cuts here
            break
        sky = Image.blend(L['sky'], calm, ease(t * 1.3))
        img = Image.composite(L['dark'], sky, parted(L['still'], t))
        if t < 0.7:
            rain(img, k, frames, 4, int(420 * (1 - t / 0.7) * size[0] / w), L['rain'], 16)
        out.append(img)
    save_gif(out, name, ms, hold_last=HOLD, dither=dither)


def night_storm():
    storm('night', 'night-storm')


def day_storm():
    storm('day', 'day-storm')


def day_clear():
    d = Day()
    # the sun climbs from low in the frame to its place; the white clouds gather last
    clear('day', (w, h), lambda t: d.frame(0, clouds=ease((t - 0.35) / 0.65), sun_y=h * 0.9 - (h * 0.9 - SUN[1]) * ease(t)), 'day-clear', dither=True)


def night_clear():
    n = Night()
    clear('night', (W, H), lambda t: n.frame(0, reveal=1.0 if t >= 1 else ease(t)), 'night-clear', frames=26, ms=120)


# ---------- twilight: the real change of day and night ----------

HORIZON = 0.74


def twilight(rising, name):
    frames = 34
    rnd = random.Random(12)
    stars = [(rnd.uniform(0, w), rnd.uniform(0, h * HORIZON), rnd.random()) for _ in range(160)]
    land = hills((w, h), HORIZON)
    out = []
    for k in range(frames):
        t = k / (frames - 1)
        u = t if rising else 1 - t  # u: 0 = night, 1 = day
        top = lerp_rgb((10, 14, 36), (22, 74, 140), ease(u))
        mid = lerp_rgb((40, 30, 70), (255, 170, 110), math.sin(math.pi * min(1.0, u * 1.15)) ** 1.2) if u < 0.9 else lerp_rgb((255, 170, 110), (96, 150, 205), (u - 0.9) / 0.1)
        img = gradient(w, h, top, mid)
        d = ImageDraw.Draw(img)
        for x, y, p in stars:  # stars fade as the light comes
            c = int((90 + 150 * p) * max(0.0, 1 - u * 2.2))
            if c > 0:
                d.point((x, y), fill=(c, c, c))
        sx = w * 0.56
        sy = h * (HORIZON + 0.12) - h * 0.46 * ease(u)
        img = Image.composite(Image.new('RGB', (w, h), (255, 222, 160)), img, glow((w, h), sx, sy, 80, 50).point(lambda v: int(v * min(1.0, u * 2))))
        img = Image.composite(Image.new('RGB', (w, h), (255, 244, 214)), img, glow((w, h), sx, sy, 30, 2))
        img = Image.composite(Image.new('RGB', (w, h), lerp_rgb((10, 10, 24), (34, 44, 46), ease(u))), img, land)
        out.append(img)
    save_gif(out, name, 110, hold_last=HOLD, dither=True)


def dawn():
    twilight(True, 'dawn')


def dusk():
    twilight(False, 'dusk')


SCENES = {
    'night-idle': night_idle, 'night-busy': night_busy, 'night-storm': night_storm, 'night-clear': night_clear,
    'night-done': night_done, 'day-idle': day_idle, 'day-busy': day_busy, 'day-storm': day_storm,
    'day-clear': day_clear, 'day-done': day_done, 'dawn': dawn, 'dusk': dusk,
}

if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    for name in sys.argv[1:] or SCENES:
        SCENES[name]()
