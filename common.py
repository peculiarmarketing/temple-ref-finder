"""Shared paths, constants, and helpers for temple-ref-finder."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BASE_DIR = PROJECT_ROOT.parent.parent  # "1. Peculiar People"
TODO_DIR = BASE_DIR / "Temples TO DO"
READY_DIR = BASE_DIR / "Temples READY"
STAGING_DIR = PROJECT_ROOT / "staging"
RUN_LOG = PROJECT_ROOT / "run-log.md"
TEMPLES_JSON = PROJECT_ROOT / "temples.json"

SITE = "https://churchofjesuschristtemples.org"

# The site returns 406 Not Acceptable to non-browser clients.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTML_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
IMAGE_HEADERS = {"User-Agent": USER_AGENT, "Accept": "image/*"}

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".tif", ".tiff",
    ".heic", ".heif",
}


def load_temples() -> dict:
    if not TEMPLES_JSON.exists():
        raise SystemExit(
            f"temples.json is missing at {TEMPLES_JSON}; restore it before running."
        )
    try:
        return json.loads(TEMPLES_JSON.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"temples.json is not valid JSON (line {e.lineno}: {e.msg}); "
            "fix the syntax and rerun."
        )


def canonical_name(folder_name: str) -> str:
    """Folder names may carry a trailing * (under construction or announced). Strip it."""
    return folder_name.strip().rstrip("*").strip()


def is_starred(folder_name: str) -> bool:
    return folder_name.rstrip().endswith("*")


def is_placeholder(folder_name: str) -> bool:
    return folder_name.lower().startswith("untitled folder")


def find_refs_dir(folder: Path) -> Path | None:
    """Return the folder's existing refs dir (refs/ or legacy References/), or None."""
    for name in ("refs", "References", "references", "Refs"):
        candidate = folder / name
        if candidate.is_dir():
            return candidate
    return None


def list_ref_images(refs_dir: Path | None) -> tuple[list[Path], list[str]]:
    """Top-level image files in a refs dir. Returns (real files, iCloud-evicted names)."""
    if refs_dir is None or not refs_dir.is_dir():
        return [], []
    images, icloud = [], []
    for p in sorted(refs_dir.iterdir()):
        if p.name.startswith("."):
            if p.suffix == ".icloud":
                # An evicted file shows up as ".{name}.icloud"; count it as present.
                real = p.name[1:].removesuffix(".icloud")
                if Path(real).suffix.lower() in IMAGE_EXTS:
                    icloud.append(real)
            continue
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            images.append(p)
    return images, icloud


def existing_ref_names(refs_dir: Path | None) -> set[str]:
    """Every ref name already present: real files, iCloud-evicted files, and edit stems."""
    images, icloud = list_ref_images(refs_dir)
    names = {p.name for p in images} | set(icloud)
    if refs_dir is not None:
        edits = refs_dir / "edits"
        if edits.is_dir():
            names |= {d.name for d in edits.iterdir() if d.is_dir()}
    return names


def count_existing_refs(refs_dir: Path | None) -> int:
    """Refs counting toward the 3-5 target: top-level images (evicted included) plus
    one per edits/ subfolder (edit-pending images are passing refs too)."""
    images, icloud = list_ref_images(refs_dir)
    count = len(images) + len(icloud)
    if refs_dir is not None:
        edits = refs_dir / "edits"
        if edits.is_dir():
            count += sum(1 for d in edits.iterdir() if d.is_dir())
    return count


def resolve_folder(temple_arg: str) -> Path:
    """Find the TO DO folder for a --temple argument, tolerating a missing trailing *."""
    exact = TODO_DIR / temple_arg
    if exact.is_dir():
        return exact
    starred = TODO_DIR / (temple_arg + "*")
    if starred.is_dir():
        return starred
    raise SystemExit(
        f'No folder named "{temple_arg}" in Temples TO DO; run scan.py to see the queue.'
    )


def temple_entry(folder_name: str) -> dict:
    temples = load_temples()
    canon = canonical_name(folder_name)
    if canon not in temples:
        raise SystemExit(
            f'"{canon}" is not in temples.json; verify its official name and slug on '
            "churchofjesuschristtemples.org, add the entry, then rerun."
        )
    return temples[canon]


def staging_for(slug: str) -> Path:
    return STAGING_DIR / slug


def image_dims(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.size  # (width, height)


def append_run_log(line: str) -> None:
    if not RUN_LOG.exists():
        RUN_LOG.write_text("# temple-ref-finder run log\n\n")
    with RUN_LOG.open("a") as f:
        f.write(line.rstrip() + "\n")
