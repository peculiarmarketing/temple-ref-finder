"""Report the Temples TO DO queue: what each folder needs before it can move to READY."""

import argparse
import json

from common import (
    TODO_DIR,
    canonical_name,
    count_existing_refs,
    find_refs_dir,
    is_placeholder,
    is_starred,
    list_ref_images,
    load_temples,
)


def scan() -> tuple[list[dict], int]:
    if not TODO_DIR.is_dir():
        raise SystemExit(
            f"Temples TO DO not found at {TODO_DIR}; check the folder still exists."
        )
    temples = load_temples()
    rows: list[dict] = []
    placeholders = 0
    for folder in sorted(TODO_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        if is_placeholder(folder.name):
            placeholders += 1
            continue
        canon = canonical_name(folder.name)
        starred = is_starred(folder.name)
        name = folder.name.strip()
        marker = name[len(name.rstrip("*")):]  # "", "*", or "**"
        refs_dir = find_refs_dir(folder)
        _, icloud = list_ref_images(refs_dir)
        count = count_existing_refs(refs_dir)
        if canon not in temples:
            action = "unmapped"
        elif marker == "**":
            # Announced with no render last time; recheck the Official section.
            action = "starred-complete" if count > 0 else "render-recheck"
        elif starred:
            action = "starred-complete" if count > 0 else "render-only"
        elif count >= 5:
            action = "already-complete"
        else:
            action = "top-up"
        rows.append(
            {
                "folder": folder.name,
                "canonical": canon,
                "starred": starred,
                "marker": marker,
                "slug": temples.get(canon, {}).get("slug"),
                "refs_dir": refs_dir.name if refs_dir else None,
                "existing_images": count,
                "icloud_placeholders": icloud,
                "action": action,
            }
        )
    return rows, placeholders


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()

    rows, placeholders = scan()

    if args.json:
        print(json.dumps({"queue": rows, "placeholders_skipped": placeholders}, indent=2))
    else:
        if not rows:
            print("Queue is empty: no named temple folders in Temples TO DO.")
        for r in rows:
            star = r["marker"] or "  "
            refs = r["refs_dir"] or "none (will create refs/)"
            icloud_note = (
                f" ({len(r['icloud_placeholders'])} iCloud-evicted)"
                if r["icloud_placeholders"]
                else ""
            )
            print(
                f"{r['folder']:<20} {star} refs: {refs:<24} "
                f"images: {r['existing_images']}{icloud_note:<22} action: {r['action']}"
            )
        print(f"\nPlaceholders skipped: {placeholders}")

    unmapped = [r["folder"] for r in rows if r["action"] == "unmapped"]
    if unmapped:
        raise SystemExit(
            "Unmapped folders (not in temples.json): "
            + ", ".join(unmapped)
            + ". Verify each temple's official name and slug on "
            "churchofjesuschristtemples.org, add entries to temples.json, then rerun."
        )


if __name__ == "__main__":
    main()
