"""Convert recorded BMP photos to ROOT files (same format as the original workflow).

Each output .root holds four TH2D histograms: hR, hG, hB and an all-zero hB_sub,
exactly what the existing ROOT macros in Ref/ expect.

    # one photo  -> 002_160012/000007.root (next to the BMP)
    python tools/bmp_to_root.py data/camera/2026-11-16/002_160012/000007.bmp

    # every photo of a burst folder
    python tools/bmp_to_root.py data/camera/2026-11-16/002_160012

    # a whole day: every single photo AND every burst folder below it
    python tools/bmp_to_root.py data/camera/2026-11-16 --recursive

    # options: write elsewhere, only photos 100..200, use 4 processes
    python tools/bmp_to_root.py <path> --out converted --range 100:200 --workers 4

ROOT export takes ~0.75 s per photo per process, so use --workers for large bursts.
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert BMP photo(s) to .root (hR/hG/hB/hB_sub)")
    ap.add_argument("path", help="a .bmp file, or a folder containing .bmp files")
    ap.add_argument("--out", default=None, help="output folder (default: next to each BMP)")
    ap.add_argument("--range", default="", help="photo numbers A:B (inclusive), folders only")
    ap.add_argument("--workers", type=int, default=1, help="parallel processes (default 1)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="also convert .bmp files in all sub-folders (e.g. every burst of a day)")
    ap.add_argument("--png", action="store_true", help="also write a .png for each photo")
    args = ap.parse_args(argv)

    from h2lasercontrol.laserdaq.storage.convert import convert_path

    rng = None
    if args.range:
        a, _, b = args.range.partition(":")
        rng = (int(a or 0), int(b or 10**9))

    def progress(done: int, total: int) -> None:
        print(f"\rconverted {done}/{total}", end="", flush=True)

    try:
        n = convert_path(args.path, root=True, png=args.png, out_dir=args.out,
                         frame_range=rng, workers=args.workers, progress=progress,
                         recursive=args.recursive)
    except FileNotFoundError as e:
        print(f"Not found: {e}", file=sys.stderr)
        return 1
    print(f"\n{n} file(s) converted.")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
