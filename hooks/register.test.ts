import { expect, mock, test } from 'claude-code/testing'

import { listProfile, parse, readKeys, setProfileKeys } from './jsonc'
import { cutPlan, fadePlan, handover, phaseAt, PROFILE_GUID } from './register'

const PS = '{61c54bbd-c2c6-5271-96e7-009a87ff44bf}'
const LOCAL = 'C:\\Users\\T\\AppData\\Local'
const FILE = 'C:/Users/T/AppData/Local/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json'
// a person's own file: comments, their PowerShell tab with its own background
const MINE = `{
    // mine
    "profiles": {
        "defaults": {},
        "list": [
            {
                "guid": "${PS}",
                "name": "PowerShell",
                "backgroundImage": "C:\\\\me\\\\cat.png"
            }
        ]
    }
}
`

type On = Parameters<Parameters<typeof test>[1]>[1]

function terminal(on: On, file: { text: string }, env: Record<string, string>) {
  mock.env(on, env)
  mock.store(on)
  on('fs.stat', (_$, e) => {
    if (e.path.split('\\').join('/') !== FILE) throw new Error(`ENOENT ${e.path}`)
    return { value: { kind: 'file', size: file.text.length, mtimeMs: 1, isLink: false } }
  })
  on('fs.read', () => ({ value: file.text }))
  on('fs.write', (_$, e) => {
    file.text = e.text
    return { value: undefined }
  })
  on('command.register', (_$, e) => ({ value: { command: e.name } }))
  on('ui.toast', () => ({ value: undefined }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.end', () => ({ sessionId: 's' }))
  on('turn.start', () => ({ turnId: 't' }))
  on('turn.complete', () => ({ text: '' }))
  on('classic.PostToolUseFailure', () => ({}))
  on('command.run', () => ({}))
}

const sky = (text: string) => readKeys(listProfile(parse(text), PROFILE_GUID)!, ['backgroundImage', 'backgroundImageOpacity'])
const scene = (text: string) => /([a-z-]+)\.gif$/.exec(String(sky(text).backgroundImage))?.[1]
const psBackground = (text: string) => readKeys(listProfile(parse(text), PS)!, ['backgroundImage']).backgroundImage
const start = ($: Parameters<Parameters<typeof test>[1]>[0]) => $.session.start({ cwd: 'C:/x', surface: 'terminal' } as never)

test('day and night follow the hours, across midnight too', async () => {
  expect(phaseAt(10, { day: 7, night: 19 })).toBe('day')
  expect(phaseAt(19, { day: 7, night: 19 })).toBe('night')
  expect(phaseAt(3, { day: 7, night: 19 })).toBe('night')
  expect(phaseAt(16, { day: 7, night: 15 })).toBe('night')
  expect(phaseAt(23, { day: 22, night: 6 })).toBe('day')
})

test('first run adds its own "Claude Code" profile and leaves every other tab alone', async ($, on) => {
  const file = { text: MINE }
  mock.clock(on, { now: new Date(2026, 9, 13, 22, 0).getTime() })
  terminal(on, file, { WT_SESSION: 'x', LOCALAPPDATA: LOCAL, WT_PROFILE_ID: PS })
  await start($)
  const own = listProfile(parse(file.text), PROFILE_GUID)!
  expect(readKeys(own, ['name', 'commandline'])).toEqual({ name: 'Claude Code', commandline: 'powershell.exe -NoLogo -NoExit -Command claude' })
  expect(file.text).toContain('// mine')
  // this session runs in PowerShell: nothing is painted, PowerShell keeps its cat
  await $.turn.start({} as never)
  expect(sky(file.text).backgroundImage).toBeUndefined()
  expect(psBackground(file.text)).toBe('C:\\me\\cat.png')
  const said = await $.command.run({ command: 'sky', args: '' } as never)
  expect(String((said as { text?: string }).text)).toContain('not painting this tab')
})

test('a deleted profile stays deleted until /sky profile', async ($, on) => {
  const file = { text: MINE }
  mock.clock(on, { now: 0 })
  terminal(on, file, { WT_SESSION: 'x', LOCALAPPDATA: LOCAL, WT_PROFILE_ID: PS })
  await start($)
  file.text = MINE // the person removes it
  await start($)
  expect(listProfile(parse(file.text), PROFILE_GUID)).toBeNull()
  await $.command.run({ command: 'sky', args: 'profile' } as never)
  expect(listProfile(parse(file.text), PROFILE_GUID)).not.toBeNull()
})

test('in its own tab the sky follows a turn: busy, storm, clear, done, calm; then clears', async ($, on) => {
  const file = { text: MINE }
  const clock = mock.clock(on, { now: new Date(2026, 9, 13, 22, 0).getTime() })
  const settle = () => clock.advance(1000)
  terminal(on, file, { WT_SESSION: 'x', LOCALAPPDATA: LOCAL, WT_PROFILE_ID: PROFILE_GUID })

  await start($)
  expect(scene(file.text)).toBe('night-idle')

  await $.turn.start({} as never)
  await settle()
  expect(scene(file.text)).toBe('night-busy')

  await $.classic.PostToolUseFailure({ tool_name: 'Bash', tool_input: {}, tool_use_id: 'u', error: 'boom' } as never)
  await settle()
  expect(scene(file.text)).toBe('night-storm')
  expect(sky(file.text).backgroundImageOpacity).toBe(0.55)
  await clock.advance(3000) // 4 s of storm, then the clouds part
  await settle()
  expect(scene(file.text)).toBe('night-clear')
  expect(sky(file.text).backgroundImageOpacity).toBe(0.75) // eased up from the storm's 0.55
  await clock.advance(3600)
  await settle()
  expect(scene(file.text)).toBe('night-busy') // still working: back to busy

  await $.turn.complete({ reason: 'answer' } as never)
  await settle()
  expect(scene(file.text)).toBe('night-done')
  await clock.advance(3400)
  await settle()
  expect(scene(file.text)).toBe('night-idle')

  // an interrupted turn is not celebrated, a turn that errors brings the storm
  await $.turn.start({} as never)
  await $.turn.complete({ reason: 'aborted' } as never)
  await settle()
  expect(scene(file.text)).toBe('night-idle')
  await $.turn.start({} as never)
  await $.turn.complete({ reason: 'error' } as never)
  await settle()
  expect(scene(file.text)).toBe('night-storm')

  await $.session.end({ reason: 'exit' } as never)
  expect(sky(file.text)).toEqual({})
  expect(psBackground(file.text)).toBe('C:\\me\\cat.png')
})

test('/sky picks a sky, sets the hours, and off goes plain at once', async ($, on) => {
  const file = { text: MINE }
  const clock = mock.clock(on, { now: new Date(2026, 9, 13, 10, 0).getTime() })
  const settle = () => clock.advance(1000)
  terminal(on, file, { WT_SESSION: 'x', LOCALAPPDATA: LOCAL, WT_PROFILE_ID: PROFILE_GUID })
  await start($)
  expect(scene(file.text)).toBe('day-idle')

  await $.command.run({ command: 'sky', args: 'hours 7 9' } as never)
  await settle()
  expect(scene(file.text)).toBe('dusk') // moving the hour past now sets the sun, as the clock would
  await clock.advance(4000)
  await settle()
  expect(scene(file.text)).toBe('night-idle')
  await $.command.run({ command: 'sky', args: 'gunduz' } as never)
  await settle()
  expect(scene(file.text)).toBe('day-idle')
  const off = await $.command.run({ command: 'sky', args: 'off' } as never)
  expect(sky(file.text)).toEqual({})
  expect(String((off as { text?: string }).text)).toContain('/sky auto')
})

test('outside Windows Terminal it touches nothing', async ($, on) => {
  const file = { text: MINE }
  mock.clock(on, { now: 0 })
  terminal(on, file, { LOCALAPPDATA: LOCAL })
  await start($)
  await $.turn.start({} as never)
  await $.session.end({ reason: 'exit' } as never)
  expect(file.text).toBe(MINE)
})

test('a fade dips to nothing and swaps unseen; a seamless pair swaps at once and eases', async () => {
  const fade = fadePlan(0.75, 0.25, 'C:\\a\\day-idle.gif')
  expect(fadePlan(0.4, 0.4, 'x', 0.5).map(p => p.backgroundImageOpacity)).toEqual([0.36, 0.32, 0.28, 0.24, 0.2, 0.24, 0.28, 0.32, 0.36, 0.4])
  expect(fade.map(p => p.backgroundImageOpacity)).toEqual([0.6, 0.45, 0.3, 0.15, 0, 0.05, 0.1, 0.15, 0.2, 0.25])
  expect(fade.filter(p => 'backgroundImage' in p).map(p => p.backgroundImageOpacity)).toEqual([0])
  const cut = cutPlan(0.55, 0.75, 'C:\\a\\night-clear.gif')
  expect(cut[0]).toEqual({ backgroundImage: 'C:\\a\\night-clear.gif', backgroundImageOpacity: 0.55, backgroundImageStretchMode: 'uniformToFill' })
  expect(cut.at(-1)).toEqual({ backgroundImageOpacity: 0.75 })
  expect(cutPlan(0.75, 0.75, 'x')).toHaveLength(1)
})

test('scenes drawn to meet cut, the same time of day dips softly, day and night fade', async () => {
  expect(handover('night-storm', 'night-clear')).toBe('cut')
  expect(handover('day-clear', 'day-busy')).toBe('cut')
  expect(handover('day-done', 'day-idle')).toBe('cut')
  expect(handover('night-idle', 'night-busy')).toBe('cut')
  expect(handover('night-busy', 'night-done')).toBe('cut')
  expect(handover('day-idle', 'day-busy')).toBe('soft')
  expect(handover('day-busy', 'day-storm')).toBe('soft')
  expect(handover('day-idle', 'dusk')).toBe('fade')
  expect(handover('dusk', 'night-idle')).toBe('fade')
  expect(handover('day-busy', 'night-busy')).toBe('fade')
})

test('another tab of the profile ends and clears the sky: this one paints it again within a minute', async ($, on) => {
  const file = { text: MINE }
  const clock = mock.clock(on, { now: new Date(2026, 9, 13, 22, 0).getTime() })
  terminal(on, file, { WT_SESSION: 'x', LOCALAPPDATA: LOCAL, WT_PROFILE_ID: PROFILE_GUID })
  await start($)
  expect(scene(file.text)).toBe('night-idle')
  // what the other tab's session.end writes
  file.text = setProfileKeys(file.text, PROFILE_GUID, { backgroundImage: undefined, backgroundImageOpacity: undefined, backgroundImageStretchMode: undefined })!
  expect(sky(file.text)).toEqual({})
  await clock.advance(60_000)
  await clock.advance(1000)
  expect(scene(file.text)).toBe('night-idle')
  expect(psBackground(file.text)).toBe('C:\\me\\cat.png')
})

test('when the clock passes the hour the sun sets once, then the night', async ($, on) => {
  const file = { text: MINE }
  const clock = mock.clock(on, { now: new Date(2026, 9, 13, 18, 59, 30).getTime() })
  terminal(on, file, { WT_SESSION: 'x', LOCALAPPDATA: LOCAL, WT_PROFILE_ID: PROFILE_GUID })
  await start($)
  expect(scene(file.text)).toBe('day-idle')
  await clock.advance(60_000) // the minute tick after 19:00
  await clock.advance(1000)
  expect(scene(file.text)).toBe('dusk')
  await clock.advance(4000)
  await clock.advance(1000)
  expect(scene(file.text)).toBe('night-idle')
})
