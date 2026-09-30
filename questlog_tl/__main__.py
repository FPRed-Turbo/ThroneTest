"""Command line entry point: ``python -m questlog_tl <command>``."""

from __future__ import annotations

import argparse
import json

from .datasets import BY_NAME


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="questlog_tl",
                                description="Collect Throne and Liberty data from questlog.gg and "
                                            "turn it into a knowledge pack for Claude.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scrape", help="download data from questlog.gg into DATA/raw")
    s.add_argument("--out", default="data", help="data directory (default: data)")
    s.add_argument("--language", default="en")
    s.add_argument("--datasets", nargs="+", choices=sorted(BY_NAME), help="only these databases")
    s.add_argument("--details", choices=["build", "all", "none"], default="build",
                   help="which entities get their full record fetched: build-relevant ones "
                        "(default), every entity (~30k requests), or none")
    s.add_argument("--workers", type=int, default=4, help="parallel requests (default 4)")
    s.add_argument("--delay", type=float, default=0.25,
                   help="minimum seconds between requests, across all workers (default 0.25)")
    s.add_argument("--refresh", action="store_true", help="re-download detail files that already exist")
    s.add_argument("--no-builder", action="store_true", help="skip character/skill builder datasets")
    s.add_argument("--no-community", action="store_true",
                   help="skip guides, patch notes and community player builds")
    s.add_argument("--build-pages", type=int, default=1,
                   help="pages (18 builds each) of most-popular builds per weapon combo (default 1)")
    s.add_argument("--min-likes", type=int, default=3,
                   help="ignore community builds with fewer likes (default 3)")

    e = sub.add_parser("export", help="build the Claude knowledge pack from DATA/raw")
    e.add_argument("--out", default="data", help="data directory (default: data)")
    e.add_argument("--min-grade", type=int, default=31,
                   help="lowest gear grade to detail: 11 common, 21 uncommon, 31 rare (default), 41 epic")
    e.add_argument("--max-builds", type=int, default=4,
                   help="gear sets shown per community character, featured first (0 = all; default 4)")
    e.add_argument("--max-file-kb", type=int, default=900,
                   help="split knowledge files larger than this (default 900 KB)")

    a = sub.add_parser("all", help="scrape then export")
    a.add_argument("--out", default="data")
    a.add_argument("--details", choices=["build", "all", "none"], default="build")

    args = p.parse_args(argv)

    if args.command in ("scrape", "all"):
        from .scraper import scrape
        manifest = scrape(args.out, language=getattr(args, "language", "en"),
                          datasets=getattr(args, "datasets", None), detail_mode=args.details,
                          workers=getattr(args, "workers", 4), min_interval=getattr(args, "delay", 0.25),
                          refresh=getattr(args, "refresh", False),
                          include_builder=not getattr(args, "no_builder", False),
                          include_community=not getattr(args, "no_community", False),
                          build_pages=getattr(args, "build_pages", 1),
                          min_likes=getattr(args, "min_likes", 3))
        print(json.dumps({k: v for k, v in manifest["datasets"].items()}, indent=1))
    if args.command in ("export", "all"):
        from .export import export
        for path in export(args.out, max_file_kb=getattr(args, "max_file_kb", 900),
                           min_grade=getattr(args, "min_grade", 31),
                           max_builds=getattr(args, "max_builds", 4)):
            print(path)


if __name__ == "__main__":
    main()
