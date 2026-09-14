"""``python -m eclusa.index build|search``: build the index from the corpus, or query it.

``build`` is what the image build runs; ``search`` is a development tool to look at
what retrieval returns before any model is asked anything.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from eclusa.corpus import manifest as manifest_mod
from eclusa.index.embedding import Embedder
from eclusa.index.store import IndexStore, build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eclusa.index", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--corpus", type=Path, default=Path("corpus"))
    b.add_argument("--out", type=Path, default=Path("var/index"))
    b.add_argument("--threads", type=int, default=1, help="1 keeps the build reproducible")
    s = sub.add_parser("search")
    s.add_argument("question")
    s.add_argument("--index", type=Path, default=Path("var/index"))
    s.add_argument("-k", type=int, default=8)
    args = parser.parse_args(argv)

    if args.command == "build":
        started = time.monotonic()
        manifest_path = args.corpus / "manifest.json"
        store = build(
            manifest_mod.load(manifest_path),
            args.corpus,
            Embedder.pinned(threads=args.threads),
            manifest_path,
        )
        store.save(args.out)
        print(
            f"{store.meta['chunks']} chunks from {store.meta['documents']} documents in "
            f"{time.monotonic() - started:.0f}s -> {args.out}"
        )
        return 0

    store = IndexStore.load(args.index)
    embedder = Embedder.pinned()
    for hit in store.search(embedder.embed_query(args.question), k=args.k):
        c = hit.chunk
        print(f"{hit.score:.4f} {c.doc_id} {c.citation or '(notice)'} | {c.text[:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
