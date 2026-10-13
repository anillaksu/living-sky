# AGENTS.md — living-sky

Rules for any coding agent working in this repository (Claude Code, Codex, OpenCode…).
The owner is Anıl Aksu (GitHub `anillaksu`). He writes in Turkish; answer in Turkish.

## The one principle: claims follow measurements

Every number or claim that leaves this repository (README, release notes, posts, commit messages) must come from a
measurement made on the code being published. Mark anything not measured as such. Two grades, as in an audit file:

- **Measured**: produced by a command in this repo on this commit (tests, `tools/review.py`, a timing).
- **Declared**: the owner's or someone's statement, not checked here. Say so in the text, or leave it out.

If a measurement changes, update the claim in the same commit. Never round up, never keep an old number.

## Before every push

Run all of these from the repository root and read the output. Stop if any fails.

```
claude plugin validate .            # must end with "Validation passed"
claude plugin test .                # every test passes, 0 fail
python tools/review.py              # "24/24 pass" (or n/n) and every seam under 2.0/255
git status                          # nothing unexpected staged; docs/review/ stays untracked
```

Then check the README's "Built to look right" numbers against the `review.py` output just printed.
They must match. If scenes were regenerated (`python tools/generate.py`), run `review.py` again before trusting them.

## Pushing and releasing

- **Ask the owner before `git push`, before creating a tag and before publishing a release.** These are public and
  hard to take back. A yes for one push is not a yes for the next.
- Never `git push --force` to `main`. Never rewrite published history.
- Author identity is set in this repo's `.git/config`: `anillaksu <118369438+anillaksu@users.noreply.github.com>`.
  Keep the noreply address; never commit with the owner's personal e-mail.
- Versions follow semver. Bump `version` in `.claude-plugin/plugin.json` in the release commit, then tag `vX.Y.Z`.
- No secrets, tokens, machine paths, customer or business data. This is a public repo: nothing from the owner's other
  projects or businesses appears in it, not even their names. Before each push, search the tracked files for the
  names of the owner's private projects and for `C:\Users\` paths other than the test fixtures.
- Commit messages say what changed and why, in English, short subject line.

## How the code is laid out

| Path | What it is |
|---|---|
| `hooks/register.ts` | the plugin: events → scene → settings write, `/sky` command, fades |
| `hooks/jsonc.ts` | in-place edits of Windows Terminal's settings.json (comments survive) |
| `hooks/*.test.ts` | behaviour tests, run by `claude plugin test .` |
| `tools/generate.py` | draws the twelve scenes into `assets/` (seeded, reproducible) |
| `tools/review.py`, `tools/scenarios.py` | renders scenes as the terminal shows them and measures legibility and seams |
| `tools/promo.py` | `docs/scenes.png` and `docs/social-preview.png` |

Rules the code depends on (each has a test; keep it green):
- living-sky paints **only its own profile** (GUID `{d909991b-4fa0-42d3-955b-720d7342c425}`). A GUID that is not in the
  list must never fall back to `profiles.defaults`: that would paint every tab.
- `settings.json` is never re-serialised. Only the three `backgroundImage*` keys of that profile are written.
- Focal elements (moon, sun, horizon) stay inside the safe zone x 26–74 %, y 20–80 % and away from the top left.
- Opacities in `register.ts` and `tools/review.py` are the same numbers. Change both or neither.

## Open work (as of 2026-10-13)

- [ ] Demo GIF (`docs/demo.gif`, ~10 s: working → storm → clear → done), replace the DEMO comment in README and
      attach it to the release.
- [ ] Upload the social preview (`docs/social-preview.png`) in the repository settings (web only).
- [ ] Not yet measured: whether Windows Terminal shows every intermediate step of a fade (the owner saw it as smooth),
      light terminal themes, monitors above 1080p.
- [ ] v0.2: real weather via Open-Meteo (`/sky city`).
