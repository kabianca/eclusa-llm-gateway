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
    sh = sub.add_parser(
        "show", help="print a provision by document and locator, to check a citation"
    )
    sh.add_argument("doc_id", help="circular-3978-2020@v5, or just circular-3978-2020")
    sh.add_argument(
        "locator", nargs="?", help='"art. 10, caput"; omit to list the act\'s provisions'
    )
    sh.add_argument("--corpus", type=Path, default=Path("corpus"))
    s = sub.add_parser("search")
    s.add_argument("question")
    s.add_argument("--index", type=Path, default=Path("var/index"))
    s.add_argument("-k", type=int, default=8)
    args = parser.parse_args(argv)

    if args.command == "show":
        from eclusa.ingest.extract import load_paragraphs
        from eclusa.ingest.segment import segment

        manifest = manifest_mod.load(args.corpus / "manifest.json")
        docs = [d for d in manifest.documents if args.doc_id in (d.doc_id, d.act_id)]
        if not docs:
            print(f"no such document: {args.doc_id}")
            return 1
        for doc in docs:
            segments = segment(doc.doc_id, load_paragraphs(args.corpus / doc.text_path))
            print(f"\n=== {doc.doc_id} — {doc.title} ({doc.status.value})")
            if args.locator is None:
                print("   ", ", ".join(s.citation for s in segments if s.kind == "caput"))
                continue
            wanted = [s for s in segments if s.citation and s.citation.startswith(args.locator)]
            if not wanted:
                print(f"    (nada em {args.locator})")
            for s in wanted:
                print(f"\n[{s.citation}]  {s.text}")
        return 0
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
