# temple-ref-finder

Finds reference photos for new temple line drawings. Sweeps `../Temples TO DO/` for temple folders that need references, pulls candidates from churchofjesuschristtemples.org (web search fallback), and Claude judges each one in-session against the quality bar. Passing images land in the folder's `refs/`, images that need cleanup get a Nano Banana Pro edit prompt in `refs/edits/{image}/`, and the folder moves to `../Temples READY/` for Evan's review. From READY, Evan moves folders to `../Temples/` and runs the temple-product-generator sweep.

Read `docs/decisions.md` before changing behavior. Driven by the `temple-ref-finder` skill ("run the refs sweep").

## Setup

```
uv python install 3.12.8
uv venv --python 3.12.8 --seed .venv.nosync
./.venv.nosync/bin/pip install -r requirements.txt
```

The `.nosync` suffix keeps iCloud from syncing the interpreter. No API keys needed.

## Commands

All from the repo root with `./.venv.nosync/bin/python`.

| Task | Command |
|---|---|
| Queue report | `scan.py` (`--json` for machine-readable) |
| List a temple's gallery | `gallery.py list --temple "Cedar City"` |
| Contact sheets for triage | `gallery.py sheet --temple "Cedar City" [--section Gallery\|Official\|Construction\|all] [--max 60]` |
| Pull full-size candidates | `gallery.py pull --temple "Cedar City" --ids 12345,67890 [--report-only]` |
| Pull from a web URL | `gallery.py pull --temple X --url https://... --name web-1-hillside` |
| Wipe a temple's staging | `gallery.py clean --temple X` |
| Place refs and move to READY | `place.py --temple "Cedar City" [--report-only]` |

## Quality bar

- Resolution (script-enforced at pull): long edge >= 1200 px and short edge >= 800 px. Prefer >= 1600 long. Starred-folder renders may drop to `--min-long 1000` when there is no choice.
- Framing (Claude judgment): the whole temple in frame; any image with part of the building cut off by the frame edge fails.
- Angle (Claude judgment): 3/4 view showing two wall planes in two-point perspective, spire visible top to bottom. Front elevations, telephoto flattening, and drone top-downs fail.
- Obstruction (Claude judgment): minor occluders pass clean; moderate occlusion or weak background contrast passes with an NB Pro edit prompt; heavy occlusion fails unless secondary detail refs can cover the hidden parts and nothing better exists.

## Layout of a processed folder

```
{Temple}/refs/
  {site filename}.jpg              clean refs
  edits/{image stem}/              one per image needing NB Pro work
    {image}.jpg + nb-prompt.txt + detail-*.jpg
  report (auto).md                 verdicts, credits, shortfall notes
```

`selection.json` (written by Claude into `staging/{slug}/`, consumed by `place.py`):

```json
{
  "clean": ["cedar-city-utah-temple-12345.jpg"],
  "edits": [{"image": "...jpg", "prompt_file": "nb-prompt-12345.txt", "details": ["...jpg"]}],
  "verdicts": [{"file": "...", "verdict": "PASS", "reason": "...", "url": "...", "credit": "..."}],
  "shortfall_note": null,
  "note": null,
  "mark": null
}
```

`mark` is null (keep the folder name), `"*"` (under construction or announced with verified official render), or `"**"` (announced, no render released). place.py replaces any existing trailing asterisks with the mark when moving the folder to READY.

## Hard rules

- Never overwrite existing files in a temple folder. Never rename Evan's folders or files, except the trailing asterisk markers, which place.py updates via the selection's `mark` field.
- Existing markers stay through the move to READY unless the marker rules in SKILL.md say to update them.
- Renders must be verified official and corroborated as THIS temple's render (see SKILL.md); a shortfall note beats a wrong render.
- All file operations in Python via pathlib/shutil, never shell (folder names contain spaces and literal `*`).
- Images are private drawing references. Never publish or redistribute them; reports keep the photographer credit lines.
- No em dashes in any generated text.
