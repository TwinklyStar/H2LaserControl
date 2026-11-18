"""Offline conversion of recorded BMPs (``NNNNNN_HHMMSS.bmp``) to ROOT and/or PNG."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .images import save_rgb_png
from .recorder import read_bmp_rgb
from .root_export import export_root


def frame_index(path: str | Path) -> int:
    """Photo number: the leading digits of ``NNNNNN_HHMMSS.bmp`` (0 if there are none)."""
    head = Path(path).stem.split("_")[0]
    return int(head) if head.isdigit() else 0


def list_frames(
    run_dir: str | Path,
    frame_range: tuple[int, int] | None = None,
    recursive: bool = False,
) -> list[Path]:
    """BMP files of a folder sorted by photo number; frame_range=(a, b) keeps a..b inclusive.

    recursive=True also descends into sub-folders (e.g. every burst of a day folder).
    """
    found = Path(run_dir).rglob("*.bmp") if recursive else Path(run_dir).glob("*.bmp")
    files = sorted(found, key=lambda f: (str(f.parent), frame_index(f), f.name))
    if frame_range is not None:
        a, b = frame_range
        files = [f for f in files if a <= frame_index(f) <= b]
    return files


def _convert_one(args: tuple[str, str, bool, bool]) -> str:
    bmp, out_dir, root, png = args
    bmp_p = Path(bmp)
    frame = read_bmp_rgb(bmp_p)
    stem = Path(out_dir) / bmp_p.stem
    if png:
        save_rgb_png(frame, stem.with_suffix(".png"))
    if root:
        hB = frame[:, :, 2]
        zeros = np.zeros_like(hB)
        export_root(frame[:, :, 0], frame[:, :, 1], hB, zeros, stem.with_suffix(".root"))
    return bmp_p.name


def convert_run(
    run_dir: str | Path,
    *,
    root: bool = False,
    png: bool = False,
    out_dir: str | Path | None = None,
    frame_range: tuple[int, int] | None = None,
    workers: int = 1,
    progress=None,
    recursive: bool = False,
) -> int:
    """Convert frames of *run_dir*.  Returns the number of frames converted.

    With recursive=True every sub-folder is included; when out_dir is given the
    sub-folder structure is mirrored below it.

    ROOT files hold hR/hG/hB plus an all-zero hB_sub (what the Ref/ ROOT macros expect).
    """
    files = list_frames(run_dir, frame_range, recursive)
    return convert_files(files, root=root, png=png, out_dir=out_dir, workers=workers,
                         progress=progress, base_dir=run_dir if recursive else None)


def convert_path(
    path: str | Path,
    *,
    root: bool = True,
    png: bool = False,
    out_dir: str | Path | None = None,
    frame_range: tuple[int, int] | None = None,
    workers: int = 1,
    progress=None,
    recursive: bool = False,
) -> int:
    """Convert one .bmp file, or every .bmp in a folder (and its sub-folders if recursive)."""
    path = Path(path)
    if path.is_dir():
        return convert_run(path, root=root, png=png, out_dir=out_dir, frame_range=frame_range,
                           workers=workers, progress=progress, recursive=recursive)
    if not path.is_file():
        raise FileNotFoundError(path)
    return convert_files([path], root=root, png=png, out_dir=out_dir, workers=1, progress=progress)


def convert_files(
    files: list[Path],
    *,
    root: bool = False,
    png: bool = False,
    out_dir: str | Path | None = None,
    workers: int = 1,
    progress=None,
    base_dir: str | Path | None = None,
) -> int:
    """Convert the given BMP files; outputs go next to each file unless out_dir is given.

    With out_dir and base_dir, each file's folder path relative to base_dir is mirrored
    below out_dir.
    """
    jobs = []
    for f in files:
        out = Path(out_dir) if out_dir is not None else f.parent
        if out_dir is not None and base_dir is not None:
            out = out / f.parent.relative_to(base_dir)
        out.mkdir(parents=True, exist_ok=True)
        jobs.append((str(f), str(out), root, png))
    if not (root or png):
        return 0
    done = 0
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for _ in ex.map(_convert_one, jobs):
                done += 1
                if progress:
                    progress(done, len(jobs))
    else:
        for j in jobs:
            _convert_one(j)
            done += 1
            if progress:
                progress(done, len(jobs))
    return done
