from __future__ import annotations

import argparse

from critiq.repository.store import IndexCache, build_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="critiq-index")
    parser.add_argument("repo", help="Path to a repository checkout")
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Directory to cache the built index (JSON)",
    )
    parser.add_argument(
        "--key",
        default=None,
        help="Cache key (e.g. owner/repo@headsha); defaults to repo basename",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.cache_dir:
        key = args.key or "local"
        index = IndexCache(args.cache_dir).get_or_build(key, args.repo)
        print(f"Loaded/built index for key {key} "
              f"({index.file_count} files, {index.total_lines} lines)")
    else:
        index = build_index(args.repo)
        print(f"Built index for {args.repo} "
              f"({index.file_count} files, {index.total_lines} lines)")

    for path in sorted(index.modules)[:5]:
        print(f"  {path}: {len(index.symbols_for(path))} symbols")


if __name__ == "__main__":
    main()
