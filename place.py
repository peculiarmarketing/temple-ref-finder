"""Place selected reference images into a temple folder and move it to Temples READY.

Reads staging/{slug}/selection.json (written by Claude during the sweep), validates it,
copies images into the folder's refs layout, writes "report (auto).md", moves the folder
to Temples READY, and appends a line to run-log.md.
"""

import argparse
import datetime
import json
import shutil
from pathlib import Path

from common import (
    READY_DIR,
    append_run_log,
    count_existing_refs,
    existing_ref_names,
    find_refs_dir,
    image_dims,
    is_starred,
    resolve_folder,
    staging_for,
    temple_entry,
)

# Sanity net only; the real floor was enforced at pull time.
SANITY_LONG, SANITY_SHORT = 1000, 600


def load_selection(staging: Path) -> dict:
    selection_path = staging / "selection.json"
    if not selection_path.exists():
        raise SystemExit(
            f"No selection.json in {staging}; write the selection first "
            "(SKILL.md step 7)."
        )
    try:
        sel = json.loads(selection_path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"{selection_path} is not valid JSON (line {e.lineno}: {e.msg}); "
            "fix it and rerun."
        )
    sel.setdefault("clean", [])
    sel.setdefault("edits", [])
    sel.setdefault("verdicts", [])
    sel.setdefault("shortfall_note", None)
    sel.setdefault("note", None)
    sel.setdefault("mark", None)
    return sel


def target_name(folder_name: str, mark: str | None) -> str:
    """Destination folder name in READY. A mark of '*' (built status: under
    construction or announced with render) or '**' (announced, no render) replaces
    any existing trailing asterisks; None keeps the name exactly as it is."""
    if mark is None:
        return folder_name
    return folder_name.strip().rstrip("*").strip() + mark


def validate(folder: Path, staging: Path, sel: dict) -> tuple[Path, list, list]:
    full_dir = staging / "full"
    problems = []

    def staged_image(name: str) -> Path | None:
        p = full_dir / name
        if not p.is_file():
            problems.append(f"{name} is not in {full_dir}")
            return None
        try:
            width, height = image_dims(p)
        except Exception as e:
            problems.append(f"{name} is not a readable image ({e})")
            return None
        if max(width, height) < SANITY_LONG or min(width, height) < SANITY_SHORT:
            problems.append(f"{name} is {width}x{height}, under the sanity floor")
        return p

    clean_paths = []
    for name in sel["clean"]:
        p = staged_image(name)
        if p:
            clean_paths.append(p)

    edit_paths = []
    for name in sel["edits"]:
        if not isinstance(name, str):
            problems.append(
                f"edits entries are plain image filenames since 2026-08-25: {name!r}"
            )
            continue
        p = staged_image(name)
        if p:
            edit_paths.append(p)

    # No duplicates within the selection itself: repeated names, or a file
    # listed as both clean and edit.
    clean_names = [p.name for p in clean_paths]
    edit_names = [p.name for p in edit_paths]
    dupes = {n for n in clean_names if clean_names.count(n) > 1}
    dupes |= {n for n in edit_names if edit_names.count(n) > 1}
    dupes |= set(clean_names) & set(edit_names)
    if dupes:
        problems.append(
            "selection lists the same image more than once: " + ", ".join(sorted(dupes))
        )

    if sel["mark"] not in (None, "*", "**"):
        problems.append(f'mark must be null, "*", or "**", not {sel["mark"]!r}')
        sel["mark"] = None

    refs_dir = find_refs_dir(folder) or (folder / "refs")
    existing_dir = refs_dir if refs_dir.is_dir() else None
    total = count_existing_refs(existing_dir) + len(clean_paths) + len(edit_paths)
    # A mark set by the sweep means the temple is not built; the starred rules apply
    # even before the folder name carries the asterisks.
    starred = is_starred(folder.name) or sel["mark"] in ("*", "**")

    if starred:
        if total < 1 and not sel["shortfall_note"]:
            problems.append(
                "starred folder with zero refs needs a shortfall_note explaining why "
                "(e.g. no official render released yet)"
            )
    else:
        if total > 10:
            problems.append(
                f"total refs would be {total}; trim the selection to keep the 5-10 target"
            )
        if total < 5 and not sel["shortfall_note"]:
            problems.append(
                f"total refs would be {total} (under 5) and there is no shortfall_note"
            )

    # Zero overwrites of anything already in the temple folder. existing_ref_names
    # also covers iCloud-evicted files (".name.icloud") and existing edit stems,
    # which a bare .exists() check would miss.
    taken = existing_ref_names(existing_dir)
    for p in clean_paths:
        if p.name in taken or (refs_dir / p.name).exists():
            problems.append(f"refs/{p.name} already exists; never overwrite existing refs")
    for p in edit_paths:
        if (
            p.name in taken
            or p.stem in taken
            or (refs_dir / "edits" / p.name).exists()
            or (refs_dir / "edits" / p.stem).exists()
        ):
            problems.append(f"edits/{p.name} already exists; never overwrite existing refs")

    dest_name = target_name(folder.name, sel["mark"])
    if (READY_DIR / dest_name).exists():
        problems.append(f'"{dest_name}" already exists in Temples READY; resolve that first')
    if not READY_DIR.is_dir():
        problems.append(f"Temples READY not found at {READY_DIR}")

    if problems:
        raise SystemExit("Selection is not placeable:\n  - " + "\n  - ".join(problems))
    return refs_dir, clean_paths, edit_paths


def write_report(
    refs_dir: Path, folder: Path, official: str, sel: dict,
    clean_paths: list, edit_paths: list, existing_count: int,
) -> Path:
    today = datetime.date.today().isoformat()
    lines = [
        f"# {official} reference report (auto)",
        "",
        f"Generated {today} by temple-ref-finder. This file is regenerated; do not edit.",
        "",
        f"- Folder: {folder.name}" + (" (starred: no top-up rule)" if is_starred(folder.name) else ""),
        f"- Existing images kept: {existing_count}",
        f"- Added: {len(clean_paths)} clean, {len(edit_paths)} needing cleanup (in edits/)",
    ]
    if sel["shortfall_note"]:
        lines.append(f"- Shortfall: {sel['shortfall_note']}")
    if sel["note"]:
        lines.append(f"- Note: {sel['note']}")
    if sel["verdicts"]:
        lines += ["", "## Verdicts", ""]
        for v in sel["verdicts"]:
            parts = [f"- {v.get('file', '?')}: {v.get('verdict', '?')}"]
            if v.get("reason"):
                parts.append(f"({v['reason']})")
            if v.get("url"):
                parts.append(f"Source: {v['url']}")
            if v.get("credit"):
                parts.append(f"Credit: {v['credit']}")
            lines.append(" ".join(parts))
    if edit_paths:
        lines += ["", "## Images in edits/ (cleanup needed; findings above)", ""]
        for p in edit_paths:
            lines.append(f"- edits/{p.name}")
    report = refs_dir / "report (auto).md"
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temple", required=True, help="TO DO folder name, e.g. 'Cedar City'")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    folder = resolve_folder(args.temple)
    entry = temple_entry(folder.name)
    staging = staging_for(entry["slug"])
    sel = load_selection(staging)
    refs_dir, clean_paths, edit_paths = validate(folder, staging, sel)
    existing_count = count_existing_refs(refs_dir if refs_dir.is_dir() else None)

    dest_name = target_name(folder.name, sel["mark"])
    plan = [f"refs dir: {refs_dir} (exists: {refs_dir.is_dir()})"]
    plan += [f"copy {p.name} -> {refs_dir.name}/" for p in clean_paths]
    plan += [f"copy {p.name} -> {refs_dir.name}/edits/" for p in edit_paths]
    plan.append(f"write {refs_dir.name}/report (auto).md")
    if dest_name != folder.name:
        plan.append(
            f'move "{folder.name}" -> Temples READY as "{dest_name}" '
            "(marker updated: temple not built yet)"
        )
    else:
        plan.append(f'move "{folder.name}" -> Temples READY')

    if args.report_only:
        print(f"Placement plan for {folder.name}:")
        for step in plan:
            print(f"  {step}")
        return

    refs_dir.mkdir(exist_ok=True)
    for p in clean_paths:
        shutil.copy2(p, refs_dir / p.name)
    if edit_paths:
        (refs_dir / "edits").mkdir(parents=True, exist_ok=True)
    for p in edit_paths:
        shutil.copy2(p, refs_dir / "edits" / p.name)

    write_report(
        refs_dir, folder, entry["official_name"], sel,
        clean_paths, edit_paths, existing_count,
    )

    dest = READY_DIR / dest_name
    shutil.move(str(folder), str(dest))

    summary_bits = []
    if clean_paths:
        summary_bits.append(f"{len(clean_paths)} clean")
    if edit_paths:
        summary_bits.append(f"{len(edit_paths)} needing cleanup")
    if existing_count:
        summary_bits.append(f"{existing_count} kept")
    if sel["shortfall_note"]:
        summary_bits.append("shortfall noted")
    if not summary_bits:
        summary_bits.append("no changes needed")
    if dest_name != folder.name:
        summary_bits.append(f'renamed to "{dest_name}"')
    today = datetime.date.today().isoformat()
    append_run_log(f"{today} | {dest_name} | {', '.join(summary_bits)} | moved to READY")

    print(f'Placed and moved "{dest_name}" to Temples READY ({", ".join(summary_bits)}).')


if __name__ == "__main__":
    main()
