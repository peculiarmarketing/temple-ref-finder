"""Fetch candidate reference images from churchofjesuschristtemples.org.

Subcommands:
  list   show gallery candidates for a temple (Gallery / Official / Construction)
  sheet  build labeled contact sheets from thumbnails for fast visual triage
  pull   download full-size images into staging, enforcing the pixel floor
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import (
    HTML_HEADERS,
    IMAGE_HEADERS,
    SITE,
    image_dims,
    resolve_folder,
    staging_for,
    temple_entry,
)

SECTIONS = ("Gallery", "Official", "Construction")
DOWNLOAD_SLEEP = 1.0  # be polite; total volume is trivial

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/gif": ".gif",
}


def fetch_candidates(slug: str) -> list[dict]:
    """Parse the photographs page into candidate dicts."""
    url = f"{SITE}/{slug}/photographs/"
    resp = requests.get(url, headers=HTML_HEADERS, timeout=30)
    if resp.status_code != 200:
        raise SystemExit(
            f"Photographs page for {slug} returned HTTP {resp.status_code}; "
            f"check the slug or the site, then rerun."
        )
    soup = BeautifulSoup(resp.text, "html.parser")
    candidates, seen = [], set()
    for anchor in soup.find_all("a", attrs={"data-fancybox": True}):
        section = anchor.get("data-fancybox")
        if section not in SECTIONS:
            continue
        href = anchor.get("href")
        if not href:
            continue
        full_url = urljoin(url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        img = anchor.find("img")
        thumb_url = urljoin(url, img["src"]) if img and img.get("src") else None
        caption_html = anchor.get("data-caption") or ""
        caption = BeautifulSoup(caption_html, "html.parser").get_text(" ", strip=True)
        basename = Path(full_url).name
        stem = Path(basename).stem
        image_id = stem.removeprefix(f"{slug}-") if stem.startswith(f"{slug}-") else stem
        candidates.append(
            {
                "id": image_id,
                "section": section,
                "url": full_url,
                "thumb": thumb_url,
                "caption": caption,
                "filename": basename,
            }
        )
    if not candidates:
        raise SystemExit(
            f"No fancybox images found on {url}; the page layout may have changed. "
            "Inspect the page before rerunning."
        )
    return candidates


def download(url: str, dest: Path, min_long: int, min_short: int, what: str) -> Path | None:
    """Download one image; reject and delete it if under the pixel floor."""
    resp = requests.get(url, headers=IMAGE_HEADERS, timeout=60)
    if resp.status_code != 200:
        print(f"  SKIP {what}: HTTP {resp.status_code} from {url}")
        return None
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
    if not ctype.startswith("image/"):
        print(f"  SKIP {what}: content type {ctype or 'unknown'}, not an image ({url})")
        return None
    if dest.suffix == "":
        dest = dest.with_suffix(CONTENT_TYPE_EXT.get(ctype, ".jpg"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    try:
        width, height = image_dims(dest)
    except Exception as e:
        dest.unlink()
        print(f"  SKIP {what}: downloaded file is not a readable image ({e})")
        return None
    long_edge, short_edge = max(width, height), min(width, height)
    if long_edge < min_long or short_edge < min_short:
        dest.unlink()
        print(
            f"  REJECT {what}: {width}x{height} is under the floor "
            f"(long >= {min_long}, short >= {min_short})"
        )
        return None
    print(f"  OK {dest.name}: {width}x{height}")
    return dest


def resolve_slug(temple_arg: str) -> str:
    try:
        folder = resolve_folder(temple_arg)
    except SystemExit:
        # The folder may already have moved to READY (e.g. clean after placement);
        # temples.json can still resolve the slug from the name alone.
        return temple_entry(temple_arg)["slug"]
    return temple_entry(folder.name)["slug"]


def cmd_list(args: argparse.Namespace) -> None:
    slug = resolve_slug(args.temple)
    candidates = fetch_candidates(slug)
    if args.json:
        print(json.dumps(candidates, indent=2))
        return
    counts = {s: 0 for s in SECTIONS}
    for c in candidates:
        counts[c["section"]] += 1
    for c in candidates:
        print(f"{c['section']:<12} {c['id']:<28} {c['caption'][:80]}")
    print(f"\n{slug}: " + ", ".join(f"{s} {n}" for s, n in counts.items()))


def cmd_sheet(args: argparse.Namespace) -> None:
    from PIL import Image, ImageDraw, ImageFont

    slug = resolve_slug(args.temple)
    candidates = fetch_candidates(slug)
    wanted = SECTIONS if args.section == "all" else (args.section,)
    picks = [c for c in candidates if c["section"] in wanted and c["thumb"]][: args.max]
    if not picks:
        raise SystemExit(
            f"No candidates in section {args.section} for {slug}; "
            "run gallery.py list to see what exists."
        )

    thumbs_dir = staging_for(slug) / "thumbs"
    sheets_dir = staging_for(slug) / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    print(f"Downloading {len(picks)} thumbnails for {slug}...")
    for c in picks:
        dest = thumbs_dir / f"{c['id']}{Path(c['thumb']).suffix}"
        if not dest.exists():
            path = download(c["thumb"], dest, min_long=1, min_short=1, what=c["id"])
            time.sleep(0.3)
        else:
            path = dest
        if path:
            downloaded.append((c, path))

    if not downloaded:
        raise SystemExit(
            f"No thumbnails downloaded for {slug}; check the network and rerun."
        )

    cell_w, cell_h, label_h = 380, 320, 36
    cols, rows_per_sheet = 4, 5
    per_sheet = cols * rows_per_sheet
    try:
        font = ImageFont.load_default(size=22)
    except TypeError:
        font = ImageFont.load_default()

    sheet_paths = []
    for sheet_idx in range(0, len(downloaded), per_sheet):
        batch = downloaded[sheet_idx : sheet_idx + per_sheet]
        rows_needed = (len(batch) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cell_w, rows_needed * cell_h), "white")
        draw = ImageDraw.Draw(sheet)
        for i, (c, path) in enumerate(batch):
            x = (i % cols) * cell_w
            y = (i // cols) * cell_h
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((cell_w - 8, cell_h - label_h - 8))
                sheet.paste(im, (x + (cell_w - im.width) // 2, y + 4))
            label = f"{c['id']} [{c['section'][0]}]"
            draw.rectangle(
                [x, y + cell_h - label_h, x + cell_w, y + cell_h], fill="black"
            )
            draw.text(
                (x + 10, y + cell_h - label_h + 6), label, fill="white", font=font
            )
        n = sheet_idx // per_sheet + 1
        out = sheets_dir / f"sheet-{args.section}-{n}.png"
        sheet.save(out)
        sheet_paths.append(out)
        print(f"Sheet {n}: {out} ({len(batch)} images)")

    print(f"\n{len(downloaded)} thumbnails on {len(sheet_paths)} sheet(s).")


def cmd_pull(args: argparse.Namespace) -> None:
    slug = resolve_slug(args.temple)
    full_dir = staging_for(slug) / "full"

    jobs: list[tuple[str, Path, str]] = []  # (url, dest, label)
    if args.ids:
        by_id = {c["id"]: c for c in fetch_candidates(slug)}
        for image_id in [i.strip() for i in args.ids.split(",") if i.strip()]:
            if image_id in by_id:
                c = by_id[image_id]
                jobs.append((c["url"], full_dir / c["filename"], image_id))
            else:
                url = f"{SITE}/assets/img/temples/{slug}/{slug}-{image_id}.jpg"
                jobs.append((url, full_dir / f"{slug}-{image_id}.jpg", image_id))
    if args.url:
        if not args.name:
            raise SystemExit("--url needs --name to label the file (e.g. --name web-1).")
        ext = Path(args.url.split("?")[0]).suffix
        dest = full_dir / (f"{args.name}{ext}" if ext else args.name)
        jobs.append((args.url, dest, args.name))
    if not jobs:
        raise SystemExit("Nothing to pull: pass --ids or --url (see --help).")

    if args.report_only:
        print(f"Would pull {len(jobs)} image(s) into {full_dir}:")
        for url, dest, _ in jobs:
            print(f"  {dest.name}  <-  {url}")
        return

    kept = 0
    for url, dest, label in jobs:
        if dest.exists():
            width, height = image_dims(dest)
            print(f"  HAVE {dest.name}: {width}x{height} (already in staging)")
            kept += 1
            continue
        if download(url, dest, args.min_long, args.min_short, label):
            kept += 1
        time.sleep(DOWNLOAD_SLEEP)
    print(f"\n{kept} of {len(jobs)} image(s) in staging at {full_dir}")


def cmd_clean(args: argparse.Namespace) -> None:
    slug = resolve_slug(args.temple)
    target = staging_for(slug)
    if not target.exists():
        print(f"Nothing to clean: {target} does not exist.")
        return
    shutil.rmtree(target)
    print(f"Removed {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="show gallery candidates for a temple")
    p_list.add_argument("--temple", required=True, help="TO DO folder name, e.g. 'Cedar City'")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_sheet = sub.add_parser("sheet", help="build labeled contact sheets from thumbnails")
    p_sheet.add_argument("--temple", required=True)
    p_sheet.add_argument("--section", default="Gallery", choices=[*SECTIONS, "all"])
    p_sheet.add_argument("--max", type=int, default=60)
    p_sheet.set_defaults(func=cmd_sheet)

    p_pull = sub.add_parser("pull", help="download full-size images into staging")
    p_pull.add_argument("--temple", required=True)
    p_pull.add_argument("--ids", help="comma-separated image ids from list/sheet")
    p_pull.add_argument("--url", help="direct image URL (web-search fallback)")
    p_pull.add_argument("--name", help="label for --url downloads, e.g. web-1-hillside")
    p_pull.add_argument("--min-long", type=int, default=1200)
    p_pull.add_argument("--min-short", type=int, default=800)
    p_pull.add_argument("--report-only", action="store_true")
    p_pull.set_defaults(func=cmd_pull)

    p_clean = sub.add_parser("clean", help="wipe a temple's staging folder")
    p_clean.add_argument("--temple", required=True)
    p_clean.set_defaults(func=cmd_clean)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
