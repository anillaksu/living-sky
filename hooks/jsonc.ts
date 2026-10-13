// Surgical edits to Windows Terminal's settings.json (JSON with comments).
// The file is never re-serialised: values are replaced, inserted or removed in
// place, so a person's comments, ordering and formatting survive every edit.

type Tok = { kind: 'str' | 'punct' | 'lit'; start: number; end: number; text: string }

export type Member = { key: string; start: number; valueStart: number; valueEnd: number }
export type Obj = { kind: 'obj'; open: number; close: number; members: Member[]; values: Map<string, Node> }
export type Arr = { kind: 'arr'; open: number; close: number; items: Node[] }
export type Leaf = { kind: 'leaf'; start: number; end: number; value: unknown }
export type Node = Obj | Arr | Leaf

function tokenize(src: string): Tok[] {
  const toks: Tok[] = []
  let i = 0
  while (i < src.length) {
    const c = src[i]!
    if (c === '﻿' || /\s/.test(c)) {
      i++
    } else if (c === '/' && src[i + 1] === '/') {
      while (i < src.length && src[i] !== '\n') i++
    } else if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2)
      i = end < 0 ? src.length : end + 2
    } else if (c === '"') {
      const start = i++
      while (i < src.length && src[i] !== '"') i += src[i] === '\\' ? 2 : 1
      i++
      toks.push({ kind: 'str', start, end: i, text: src.slice(start, i) })
    } else if ('{}[]:,'.includes(c)) {
      toks.push({ kind: 'punct', start: i, end: i + 1, text: c })
      i++
    } else {
      const start = i
      while (i < src.length && !/[\s{}\[\]:,"/]/.test(src[i]!)) i++
      if (i === start) throw new Error(`unexpected character at ${i}`)
      toks.push({ kind: 'lit', start, end: i, text: src.slice(start, i) })
    }
  }
  return toks
}

export function parse(src: string): Node {
  const toks = tokenize(src)
  let p = 0
  const peek = () => toks[p]
  const take = (text?: string): Tok => {
    const t = toks[p++]
    if (!t || (text !== undefined && t.text !== text)) throw new Error(`expected ${text ?? 'a value'} near ${t?.start ?? 'end'}`)
    return t
  }
  const value = (): Node => {
    const t = take()
    if (t.text === '{') {
      const members: Member[] = []
      const values = new Map<string, Node>()
      while (peek()?.text !== '}') {
        const k = take()
        if (k.kind !== 'str') throw new Error(`expected a key near ${k.start}`)
        take(':')
        const v = value()
        const key = JSON.parse(k.text) as string
        members.push({ key, start: k.start, valueStart: v.kind === 'leaf' ? v.start : v.open, valueEnd: v.kind === 'leaf' ? v.end : v.close + 1 })
        values.set(key, v)
        if (peek()?.text === ',') take(',')
      }
      return { kind: 'obj', open: t.start, close: take('}').start, members, values }
    }
    if (t.text === '[') {
      const items: Node[] = []
      while (peek()?.text !== ']') {
        items.push(value())
        if (peek()?.text === ',') take(',')
      }
      return { kind: 'arr', open: t.start, close: take(']').start, items }
    }
    return { kind: 'leaf', start: t.start, end: t.end, value: JSON.parse(t.text) }
  }
  const root = value()
  if (p !== toks.length) throw new Error('trailing content')
  return root
}

const normGuid = (g: string) => g.replace(/[{}]/g, '').toLowerCase()

function profileList(root: Node): Arr | undefined {
  if (root.kind !== 'obj') return undefined
  const profiles = root.values.get('profiles')
  const list = profiles?.kind === 'arr' ? profiles : profiles?.kind === 'obj' ? profiles.values.get('list') : undefined
  return list?.kind === 'arr' ? list : undefined
}

/** The profile in the list whose guid matches (braces and case aside), if any. */
export function listProfile(root: Node, guid: string): Obj | null {
  for (const item of profileList(root)?.items ?? []) {
    const g = item.kind === 'obj' ? item.values.get('guid') : undefined
    if (g?.kind === 'leaf' && typeof g.value === 'string' && normGuid(g.value) === normGuid(guid)) return item as Obj
  }
  return null
}

/**
 * The profile object to edit: the one `guid` names, and only that one, so a missing
 * profile never spills over onto every tab; with no guid, `profiles.defaults`. Null
 * when there is no such object, so the caller leaves the file alone.
 */
export function findProfile(root: Node, guid: string | undefined): Obj | null {
  if (guid) return listProfile(root, guid)
  const profiles = root.kind === 'obj' ? root.values.get('profiles') : undefined
  const defaults = profiles?.kind === 'obj' ? profiles.values.get('defaults') : undefined
  return defaults?.kind === 'obj' ? defaults : null
}

export function readKeys(obj: Obj, keys: readonly string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const k of keys) {
    const v = obj.values.get(k)
    if (v?.kind === 'leaf') out[k] = v.value
  }
  return out
}

function lineIndent(src: string, at: number): string {
  const lineStart = src.lastIndexOf('\n', at - 1) + 1
  return /^[ \t]*/.exec(src.slice(lineStart))![0]
}

type Edit = { start: number; end: number; text: string }

function applyEdits(src: string, edits: Edit[]): string {
  return edits.sort((a, b) => b.start - a.start).reduce((s, e) => s.slice(0, e.start) + e.text + s.slice(e.end), src)
}

/**
 * Sets (value) or removes (undefined) each key of the profile `guid` names,
 * touching nothing else. Returns the new text, or null when there is no
 * profile to edit or the file does not parse.
 */
export function setProfileKeys(src: string, guid: string | undefined, changes: Record<string, unknown>): string | null {
  let obj: Obj | null
  try {
    obj = findProfile(parse(src), guid)
  } catch {
    return null
  }
  if (!obj) return null
  const edits: Edit[] = []
  const inserts: string[] = []
  const ms = obj.members
  const removing = new Set(Object.keys(changes).filter(k => changes[k] === undefined && obj!.values.has(k)))
  const kept = ms.filter(m => !removing.has(m.key))

  for (const [key, value] of Object.entries(changes)) {
    if (value === undefined) continue
    const m = ms.find(x => x.key === key)
    if (m) edits.push({ start: m.valueStart, end: m.valueEnd, text: JSON.stringify(value) })
    else inserts.push(`${JSON.stringify(key)}: ${JSON.stringify(value)}`)
  }

  const closeIndent = lineIndent(src, obj.close)
  const indent = ms[0] ? lineIndent(src, ms[0].start) : closeIndent + '    '
  const body = inserts.map(s => `${indent}${s}`).join(',\n')

  if (!kept.length) {
    // nothing of the object's own is left: its inside becomes the inserts, or empty
    if (inserts.length || removing.size) {
      edits.push({ start: obj.open + 1, end: obj.close, text: inserts.length ? `\n${body}\n${closeIndent}` : '' })
    }
    return applyEdits(src, edits)
  }

  // a removed member with a kept one after it goes together with its separator
  const last = kept.at(-1)!
  const lastIdx = ms.indexOf(last)
  ms.forEach((m, i) => {
    if (removing.has(m.key) && i < lastIdx) edits.push({ start: m.start, end: ms[i + 1]!.start, text: '' })
  })
  // the removed ones after the last kept member go as one span, from its end;
  // the inserts take their place there
  const tailEnd = lastIdx < ms.length - 1 ? ms.at(-1)!.valueEnd : last.valueEnd
  if (inserts.length || tailEnd !== last.valueEnd) {
    edits.push({ start: last.valueEnd, end: tailEnd, text: inserts.length ? `,\n${body}` : '' })
  }

  return applyEdits(src, edits)
}

/**
 * Adds a profile to `profiles.list` (or the legacy `profiles` array) unless one with
 * its guid is there already, matching the list's own indentation. Returns the new
 * text, the same text when the profile exists, or null when there is no list.
 */
export function addProfile(src: string, entry: { guid: string } & Record<string, unknown>): string | null {
  let root: Node
  try {
    root = parse(src)
  } catch {
    return null
  }
  if (listProfile(root, entry.guid)) return src
  const list = profileList(root)
  if (!list) return null
  const last = list.items.at(-1)
  const closeIndent = lineIndent(src, list.close)
  const indent = last ? lineIndent(src, last.kind === 'leaf' ? last.start : last.open) : closeIndent + '    '
  const unit = indent.length > closeIndent.length ? indent.slice(closeIndent.length) : '    '
  const body = JSON.stringify(entry, null, unit).split('\n').map((l, i) => (i ? indent + l : l)).join('\n')
  if (!last) return src.slice(0, list.open + 1) + `\n${indent}${body}\n${closeIndent}` + src.slice(list.close)
  const end = last.kind === 'leaf' ? last.end : last.close + 1
  return src.slice(0, end) + `,\n${indent}${body}` + src.slice(end)
}
