// living-sky: a living sky behind Windows Terminal that follows Claude Code.
//
//   idle   calm sky (stars around the moon by night, clouds past the sun by day)
//   busy   a turn is running: meteor shower / racing clouds
//   storm  a tool failed, or the turn ended in an error: lightning and rain
//   clear  after the storm: the clouds part, the sun (or the stars) come back
//   done   a turn answered: a golden comet by night, a sun flare and birds by day
//   dawn / dusk  the clock passes the hour you set: the sun rises or sets
//
// Windows Terminal sets a background per profile, never per tab, so living-sky adds a
// profile of its own ("Claude Code", which starts claude) and paints that one alone:
// every other tab keeps its own look. Only three backgroundImage* keys of that profile
// are ever written, in place, and they are cleared again when the session ends.

import type { EngineInterface, Register } from 'claude-code'

import { addProfile, parse, listProfile, setProfileKeys } from './jsonc'

type Phase = 'day' | 'night'
type Activity = 'idle' | 'busy' | 'storm' | 'clear' | 'done'
type Mode = 'auto' | 'day' | 'night' | 'off'
type Hours = { day: number; night: number }

export const PROFILE_GUID = '{d909991b-4fa0-42d3-955b-720d7342c425}'
const KEYS = ['backgroundImage', 'backgroundImageOpacity', 'backgroundImageStretchMode'] as const
// how long each passing scene stays, then where the sky goes next
const NEXT: Partial<Record<Activity, [number, Activity]>> = {
  storm: [4000, 'clear'],
  clear: [3600, 'idle'], // the one-shot GIFs run ~3-3.7 s and rest on their last frame
  done: [3400, 'idle'],
}
const TWILIGHT_MS = 4000
// tuned with tools/review.py so text stays legible over every scene (keep them in step)
const OPACITY: Record<string, number> = {
  'night-idle': 0.75, 'night-busy': 0.75, 'night-storm': 0.55, 'night-clear': 0.75, 'night-done': 0.75,
  'day-idle': 0.32, 'day-busy': 0.32, 'day-storm': 0.4, 'day-clear': 0.32, 'day-done': 0.32,
  dawn: 0.5, dusk: 0.5,
}
// How one scene hands over to the next:
//   cut   drawn to meet (a storm runs into its clear, a clear or a done ends on the first
//         frame of the calm sky, the night's idle, busy and done share one sky): swap at once
//   soft  the same time of day: a shallow dip
//   fade  day and night meet, or a twilight: a full dip through the terminal's colour
const CUT = new Set(['storm>clear', 'clear>idle', 'clear>busy', 'done>idle', 'done>busy'])
const NIGHT_SKY = ['idle', 'busy', 'done']
export function handover(from: string, to: string): 'cut' | 'soft' | 'fade' {
  const [fp, fa] = from.split('-')
  const [tp, ta] = to.split('-')
  if (!fa || !ta || fp !== tp) return 'fade'
  if (CUT.has(`${fa}>${ta}`)) return 'cut'
  if (fp === 'night' && NIGHT_SKY.includes(fa) && NIGHT_SKY.includes(ta)) return 'cut'
  return 'soft'
}
// Packaged (Store) stable, Preview, then an unpackaged install
const SETTINGS = [
  'Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json',
  'Packages/Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe/LocalState/settings.json',
  'Microsoft/Windows Terminal/settings.json',
]

let settingsPath: string | null = null
let ours = false // this session runs in living-sky's own profile
let assets = ''
let mode: Mode = 'auto'
let hours: Hours = { day: 7, night: 19 }
let activity: Activity = 'idle'
let twilight: 'dawn' | 'dusk' | null = null
let lastPhase: Phase | null = null
let twilightTimer: { cancel(): void } | null = null
let working = false
let shown = '' // the scene last written
let timer: { cancel(): void } | null = null
let queue: Promise<unknown> = Promise.resolve()

export function phaseAt(hour: number, h: Hours): Phase {
  return h.day <= h.night ? (hour >= h.day && hour < h.night ? 'day' : 'night') : hour >= h.night && hour < h.day ? 'night' : 'day'
}

export function sceneFor(phase: Phase, a: Activity, tw: 'dawn' | 'dusk' | null = null): string {
  // a storm and its clearing outrank the twilight; the twilight outranks the rest
  return tw && a !== 'storm' && a !== 'clear' ? tw : `${phase}-${a}`
}

const sameGuid = (a: string | undefined, b: string) => !!a && a.replace(/[{}]/g, '').toLowerCase() === b.replace(/[{}]/g, '').toLowerCase()

async function currentPhase($: EngineInterface): Promise<Phase> {
  if (mode === 'day' || mode === 'night') return mode
  return phaseAt(new Date(await $.clock.now()).getHours(), hours)
}

// one edit at a time: hooks fire close together and every edit reads the file fresh
function serial<T>(fn: () => Promise<T>): Promise<T> {
  const run = queue.then(fn, fn)
  queue = run.catch(() => undefined)
  return run
}

function edit($: EngineInterface, changes: Record<string, unknown>): Promise<boolean> {
  return serial(async () => {
    if (!settingsPath) return false
    const src = await $.fs.read(settingsPath)
    const out = setProfileKeys(src, PROFILE_GUID, changes)
    if (out === null) return false
    if (out !== src) await $.fs.write(settingsPath, out)
    return true
  })
}

// Windows Terminal swaps a background image in one frame. A cut that hard reads as a
// glitch, so a change dips through the terminal's own background colour instead: the
// old sky fades out, the new image goes in unseen, then fades in. Scenes drawn to meet
// (SEAMLESS) swap at once and only ease the opacity. Each step is one small settings
// write; a newer change cancels the rest of an older one.
const STEPS = 5
const STEP_MS = 60
let fadeGen = 0
let opacityNow = 0 // the backgroundImageOpacity last written

const round = (x: number) => Math.round(x * 1000) / 1000

// depth: how far the dip goes, 1 = all the way to the terminal's colour
export function fadePlan(from: number, to: number, image: string, depth = 1): Record<string, unknown>[] {
  const low = 1 - depth
  const out = Array.from({ length: STEPS - 1 }, (_, i) => ({ backgroundImageOpacity: round(from * (1 - (depth * (i + 1)) / STEPS)) }))
  const swap = { backgroundImage: image, backgroundImageOpacity: round(to * low), backgroundImageStretchMode: 'uniformToFill' }
  const fadeIn = Array.from({ length: STEPS }, (_, i) => ({ backgroundImageOpacity: round(to * (low + (depth * (i + 1)) / STEPS)) }))
  return [...out, swap, ...fadeIn]
}

export function cutPlan(from: number, to: number, image: string): Record<string, unknown>[] {
  const swap = { backgroundImage: image, backgroundImageOpacity: from, backgroundImageStretchMode: 'uniformToFill' }
  if (from === to) return [swap]
  return [swap, ...Array.from({ length: STEPS }, (_, i) => ({ backgroundImageOpacity: round(from + ((to - from) * (i + 1)) / STEPS) }))]
}

function run($: EngineInterface, plan: Record<string, unknown>[], gen: number, i = 0): void {
  if (gen !== fadeGen || i >= plan.length) return
  const step = plan[i]!
  void edit($, step).then(() => {
    if (gen === fadeGen) opacityNow = step.backgroundImageOpacity as number
  })
  if (i + 1 < plan.length) $.clock.after(STEP_MS, () => run($, plan, gen, i + 1))
}

async function render($: EngineInterface): Promise<void> {
  if (!ours || mode === 'off') return
  const phase = await currentPhase($)
  if (lastPhase && phase !== lastPhase && mode === 'auto') {
    // the clock passed the hour: the sun rises or sets once, then the new sky
    twilight = phase === 'day' ? 'dawn' : 'dusk'
    twilightTimer?.cancel()
    twilightTimer = $.clock.after(TWILIGHT_MS, () => {
      twilight = null
      twilightTimer = null
      void render($)
    })
  }
  lastPhase = phase
  const scene = sceneFor(phase, activity, twilight)
  if (scene === shown) return
  const from = shown
  shown = scene
  const gen = ++fadeGen
  const image = `${assets}\\${scene}.gif`
  const to = OPACITY[scene]!
  if (!from) {
    // the session's first sky appears at once: there is nothing on screen to fade from
    opacityNow = to
    await edit($, { backgroundImage: image, backgroundImageOpacity: to, backgroundImageStretchMode: 'uniformToFill' })
    return
  }
  const how = handover(from, scene)
  run($, how === 'cut' ? cutPlan(opacityNow, to, image) : fadePlan(opacityNow, to, image, how === 'soft' ? 0.5 : 1), gen)
}

// Tabs of the profile share one sky, and the one that ends clears it. The others notice
// on the minute tick and paint it again.
async function tick($: EngineInterface): Promise<void> {
  if (ours && mode !== 'off' && shown && settingsPath) {
    try {
      const own = listProfile(parse(await $.fs.read(settingsPath)), PROFILE_GUID)
      if (own && !own.values.has('backgroundImage')) shown = ''
    } catch {
      // unreadable for now: try again next minute
    }
  }
  await render($)
}

function setActivity($: EngineInterface, a: Activity): Promise<void> {
  timer?.cancel()
  timer = null
  activity = a
  const next = NEXT[a]
  if (next) {
    const [ms, then] = next
    timer = $.clock.after(ms, () => {
      timer = null
      void setActivity($, working && then === 'idle' ? 'busy' : then)
    })
  }
  return render($)
}

async function clearSky($: EngineInterface): Promise<void> {
  fadeGen++ // a fade still running must not write over this
  await edit($, Object.fromEntries(KEYS.map(k => [k, undefined])))
  shown = ''
}

async function locateSettings($: EngineInterface): Promise<string | null> {
  if (!(await $.env.get('WT_SESSION'))) return null // not inside Windows Terminal
  const local = await $.env.get('LOCALAPPDATA')
  if (!local) return null
  for (const rel of SETTINGS) {
    const path = `${local.replace(/\\/g, '/')}/${rel}`
    try {
      if ((await $.fs.stat(path)).kind === 'file') return path
    } catch {
      // not this install
    }
  }
  return null
}

// Adds the "Claude Code" profile once. If the person deletes it, it stays deleted:
// `/sky profile` brings it back on request.
async function ensureProfile($: EngineInterface, force = false): Promise<boolean> {
  if (!settingsPath) return false
  if (!force && (await $.store.get('profileAdded'))) return true
  return serial(async () => {
    const src = await $.fs.read(settingsPath!)
    try {
      if (listProfile(parse(src), PROFILE_GUID)) {
        await $.store.set('profileAdded', true)
        return true
      }
    } catch {
      return false
    }
    const out = addProfile(src, {
      guid: PROFILE_GUID,
      name: 'Claude Code',
      commandline: 'powershell.exe -NoLogo -NoExit -Command claude',
      startingDirectory: '%USERPROFILE%',
      icon: `${assets}\\icon.png`,
      hidden: false,
    })
    if (out === null) return false
    await $.fs.write(settingsPath!, out)
    await $.store.set('profileAdded', true)
    return true
  })
}

const HELP = [
  '/sky            show the current sky',
  '/sky auto       day/night by the clock (default)',
  '/sky day|night  keep one sky',
  '/sky hours 7 19 day starts at 7, night at 19',
  '/sky off        a plain background until /sky auto',
  '/sky profile    add the "Claude Code" profile again',
].join('\n')

const ELSEWHERE =
  'living-sky paints its own Windows Terminal profile, so your other tabs keep their look. ' +
  'Open "Claude Code" from the new-tab menu (the ⌄ next to +) and the sky will be there.'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({ name: 'sky', description: 'Windows Terminal sky that follows Claude', argumentHint: '[auto|day|night|off|hours D N|profile]' })
    } catch {
      // the sky works without its command
    }
    assets = `${$.plugin.root}/assets`.replace(/\//g, '\\')
    mode = ((await $.store.get('mode')) as Mode | undefined) ?? 'auto'
    hours = ((await $.store.get('hours')) as Hours | undefined) ?? hours
    settingsPath = await locateSettings($)
    if (settingsPath) {
      await ensureProfile($)
      ours = sameGuid(await $.env.get('WT_PROFILE_ID'), PROFILE_GUID)
      if (ours) await render($)
      else if (!(await $.store.get('hinted'))) {
        $.ui.toast(ELSEWHERE)
        await $.store.set('hinted', true)
      }
    }
    // day turns to night by itself, even when nobody is typing
    $.clock.every(60_000, () => void tick($))
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    timer?.cancel()
    if (ours) await clearSky($)
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (!e.agentId) {
      working = true
      await setActivity($, 'busy')
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) {
      working = false
      // only an answer is celebrated; an interrupted or refused turn just calms down
      const reason = (e as { reason?: string }).reason
      await setActivity($, reason === 'answer' ? 'done' : reason === 'error' ? 'storm' : 'idle')
    }
    return next(e)
  })

  // the settings hooks' copies: awaiting next() inside tool.call would stall a long command
  on('classic.PostToolUse', async ($, e, next) => {
    const r = (e as { tool_response?: { is_error?: boolean; isError?: boolean } }).tool_response
    if (r?.is_error === true || r?.isError === true) await setActivity($, 'storm')
    return next(e)
  })
  on('classic.PostToolUseFailure', async ($, e, next) => {
    await setActivity($, 'storm')
    return next(e)
  })

  on('command.run', { command: 'sky' }, async ($, e) => {
    const [cmd = '', ...rest] = (e.args ?? '').trim().toLowerCase().split(/\s+/)
    if (!settingsPath) return { text: 'living-sky only paints Windows Terminal, and this session is not running in it.' }
    if (cmd === 'profile' || cmd === 'profil') {
      const ok = await ensureProfile($, true)
      return { text: ok ? `"Claude Code" is in your Windows Terminal profiles. ${ours ? '' : ELSEWHERE}` : 'Could not add the profile: settings.json has no profile list.' }
    }
    const alias: Record<string, Mode> = { auto: 'auto', day: 'day', gunduz: 'day', 'gündüz': 'day', night: 'night', gece: 'night', off: 'off', kapat: 'off' }
    if (cmd in alias) {
      mode = alias[cmd]!
      await $.store.set('mode', mode)
      if (mode === 'off') {
        if (ours) await clearSky($)
        return { text: 'The sky is off: a plain background. `/sky auto` brings it back.' }
      }
      await render($)
      const what = `Sky: ${mode === 'auto' ? `by the clock (day ${hours.day}:00, night ${hours.night}:00)` : mode}.`
      return { text: ours ? what : `${what} ${ELSEWHERE}` }
    }
    if (cmd === 'hours' || cmd === 'saat') {
      const [d, n] = rest.map(Number)
      if (!Number.isInteger(d) || !Number.isInteger(n) || d! < 0 || d! > 23 || n! < 0 || n! > 23 || d === n) {
        return { text: 'Usage: /sky hours <day start 0-23> <night start 0-23>, e.g. /sky hours 7 19' }
      }
      hours = { day: d!, night: n! }
      await $.store.set('hours', hours)
      await render($)
      return { text: `Day starts at ${d}:00, night at ${n}:00.` }
    }
    const phase = await currentPhase($)
    const where = ours ? `now ${shown || sceneFor(phase, activity)}` : 'not painting this tab'
    return { text: `Sky: ${mode}, ${where}.\n${HELP}` }
  })
}
