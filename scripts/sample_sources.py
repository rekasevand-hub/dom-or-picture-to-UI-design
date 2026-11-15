"""One lookup for the seven benchmark screenshots.

The samples arrived as pasted clipboard images and as WeChat temporary files.
WeChat empties ``RWTemp`` on its own schedule, so five of the seven paths in
``image_reference.json`` now point at nothing — as of 2026-11-15 only AtomGit
and review still resolve.  A replay that dies inside ``cv2.imread`` reports the
wrong thing: the picture is gone, the code is fine.

So the search lives here, in one place, and it names what it could not find:

    recorded path  ->  samples/image_screenshots/<tag>.{png,jpg,jpeg}

Adding a screenshot to that directory is what makes a sample replayable again,
independent of wherever the picture was pasted from.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Screenshots kept in the repo, named after their sample tag.
CORPUS = ROOT / "samples" / "image_screenshots"

#: Tried in order; the corpus keeps whatever format the picture arrived in.
SUFFIXES = (".png", ".jpg", ".jpeg")


class MissingScreenshot(FileNotFoundError):
    """No file on disk holds this sample's picture any more."""


def locate(tag: str, recorded: str | Path | None) -> Path:
    """The picture for ``tag``: where it was read from, else the repo copy."""
    if recorded:
        candidate = Path(recorded)
        if candidate.is_file():
            return candidate
    for suffix in SUFFIXES:
        candidate = CORPUS / f"{tag}{suffix}"
        if candidate.is_file():
            return candidate
    where = f"{recorded} " if recorded else ""
    raise MissingScreenshot(
        f"{tag}: screenshot not found (recorded at {where or '<no path>'}, "
        f"corpus {CORPUS}). Put the picture back as {tag}.png to replay it."
    )


def bind(tag: str, graph: dict, reference: dict) -> tuple[Path, dict, dict]:
    """Point the graph and the reference at one picture.

    Both documents carry the path and ``build_image_design`` prefers the
    graph's, so a fallback that only fixed the reference would be ignored.
    The recorded canvas size is the contract every coordinate in the graph was
    measured against; a different picture is a different sample.
    """
    recorded = (reference.get("input") or {}).get("path") or graph.get("image")
    path = locate(tag, recorded)
    graph = {**graph, "image": str(path)}
    input_block = {**(reference.get("input") or {}), "path": str(path)}
    reference = {**reference, "input": input_block}

    size = input_block.get("size")
    if size:
        from PIL import Image  # noqa: PLC0415 - only needed on a real replay

        actual = list(Image.open(path).size)
        expected = [int(value) for value in size]
        if actual != expected:
            raise ValueError(
                f"{tag}: {path.name} is {actual[0]}x{actual[1]}, "
                f"but the graph was measured on {expected[0]}x{expected[1]}"
            )
    return path, graph, reference
