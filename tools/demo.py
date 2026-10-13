"""Build docs/demo.gif: one Claude turn as the "Claude Code" tab shows it.

Not a screen recording: every frame is rendered with review.py's model of Windows
Terminal (uniformToFill, blended with the background at the scene's opacity), and the
scenes follow the plugin's own timings and handovers (register.ts NEXT, CUT, fadePlan).

    python tools/demo.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

from review import BG, OPACITY, A, font

ROOT = Path(__file__).resolve().parent.parent
SIZE = (800, 450)
TICK = 100  # ms per demo frame

PROMPT = [('PS C:\\Users\\you> claude', (204, 204, 204)), ('> fix the failing test', (204, 204, 204))]
THINK = [('* Thinking...', (215, 119, 87))]
FAIL = [('  Bash(npm test)', (150, 150, 150)), ('    2 failed, 12 passed', (231, 72, 86))]
EDIT = [('  Edit(src/date.ts)', (150, 150, 150))]
PASS = [('  Bash(npm test)', (150, 150, 150)), ('    14 passed, 0 failed', (19, 161, 14))]
ANSWER = [('* Fixed: the date parser ignored the time zone.', (204, 204, 204)), ('> _', (204, 204, 204))]

# scene, how long it shows (ms), the event that brought it, the terminal text
STAGES = [
    ('night-idle', 2000, 'idle: stars around the moon', PROMPT),
    ('night-busy', 3000, 'turn.start: a meteor shower', PROMPT + THINK),
    ('night-storm', 4000, 'a tool fails: the storm', PROMPT + THINK + FAIL),
    ('night-clear', 3600, 'the clouds part', PROMPT + THINK + FAIL + EDIT),
    ('night-busy', 1500, 'still working', PROMPT + THINK + FAIL + EDIT + PASS),
    ('night-done', 3400, 'Claude answers: a golden comet', PROMPT + FAIL + EDIT + PASS + ANSWER),
    ('night-idle', 2000, 'calm again', PROMPT + FAIL + EDIT + PASS + ANSWER),
]
LOOPING = {'night-idle', 'night-busy', 'night-storm'}
# register.ts: night idle/busy/done and storm>clear, clear>busy are cuts; busy>storm dips halfway
SOFT = {('night-busy', 'night-storm')}
DIP_STEPS = 5


class Gif:
    def __init__(self, name):
        self.g = Image.open(A / f'{name}.gif')
        self.times = []
        t = 0
        for i in range(self.g.n_frames):
            self.g.seek(i)
            self.times.append(t)
            t += self.g.info.get('duration', 100)
        self.length = t
        self.loops = name in LOOPING

    def at(self, ms):
        if self.loops:
            ms %= self.length
        k = max(i for i, t in enumerate(self.times) if t <= ms)
        self.g.seek(k)
        return self.g.convert('RGB')


def terminal(img, opacity, text, caption):
    W, H = SIZE
    s = max(W / img.width, H / img.height)
    big = img.resize((round(img.width * s), round(img.height * s)))
    x, y = (big.width - W) // 2, (big.height - H) // 2
    out = Image.blend(Image.new('RGB', SIZE, BG), big.crop((x, y, x + W, y + H)), opacity)
    d = ImageDraw.Draw(out)
    f = font(15)
    for i, (line, col) in enumerate(text):
        d.text((12, 10 + i * 21), line, fill=col, font=f)
    c = font(16)
    w = d.textlength(caption, font=c)
    d.rounded_rectangle((W - w - 34, H - 42, W - 14, H - 14), radius=8, fill=(20, 22, 30))
    d.text((W - w - 24, H - 37), caption, fill=(235, 225, 190), font=c)
    return out


def build():
    gifs = {name: Gif(name) for name, *_ in STAGES}
    frames = []
    prev = None
    for name, ms, caption, text in STAGES:
        g, to = gifs[name], OPACITY[name]
        start = len(frames)
        if prev and (prev[0], name) in SOFT:
            # the old sky dips halfway, the new one comes up from there
            for i in range(1, DIP_STEPS + 1):
                frames.append(terminal(gifs[prev[0]].at(prev[1]), prev[2] * (1 - 0.5 * i / DIP_STEPS), prev[3], caption))
            for i in range(1, DIP_STEPS + 1):
                frames.append(terminal(g.at(i * TICK), to * (0.5 + 0.5 * i / DIP_STEPS), text, caption))
        ease_from = prev[2] if prev and (prev[0], name) not in SOFT else to
        for t in range(0, ms - (len(frames) - start) * TICK, TICK):
            k = min(t // TICK + 1, DIP_STEPS)
            op = ease_from + (to - ease_from) * k / DIP_STEPS
            frames.append(terminal(g.at(t), op, text, caption))
        prev = (name, ms, to, text)
    return frames


if __name__ == '__main__':
    frames = build()
    pal = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f in frames]
    out = ROOT / 'docs' / 'demo.gif'
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=TICK, loop=0, optimize=True)
    print(f'{out.name}: {len(frames)} frames, {len(frames) * TICK / 1000:.1f} s, {out.stat().st_size / 1e6:.2f} MB')
