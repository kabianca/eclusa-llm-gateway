"""``python -m eclusa.eval retrieval``: measure retrieval over the frozen cases."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from eclusa.corpus import manifest as manifest_mod
from eclusa.eval.retrieval import load_cases, run
from eclusa.index.embedding import Embedder
from eclusa.index.retrieve import retrieve
from eclusa.index.store import IndexStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eclusa.eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("retrieval")
    r.add_argument("--corpus", type=Path, default=Path("corpus"))
    r.add_argument("--index", type=Path, default=Path("var/index"))
    r.add_argument(
        "--out", type=Path, default=None, help="write summary and per-case results as JSON"
    )
    r.add_argument("--show", action="store_true", help="print the top-k of every case")
    r.add_argument(
        "--retrieval",
        choices=("raw", "version"),
        default="version",
        help="raw: the index alone (the baseline); version: the layer the gateway uses",
    )
    args = parser.parse_args(argv)

    manifest = manifest_mod.load(args.corpus / "manifest.json")
    store = IndexStore.load(args.index)
    embedder = Embedder.pinned(threads=4)
    cases = load_cases()
    search = None
    if args.retrieval == "version":

        def search(question: str):
            return retrieve(question, store, embedder, manifest, k=cases.k)

    summary, results = run(cases, store, embedder, manifest, search=search)
    summary["retrieval"] = {"raw": "index alone", "version": "eclusa.index.retrieve"}[
        args.retrieval
    ]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    for res in results:
        flags = " ".join(
            f"{name}={value}"
            for name, value in (
                ("hit", res.hit),
                ("in_force_first", res.in_force_first),
                ("mrr", res.mrr_in_force),
                ("revoked_below", res.revoked_below_current),
                ("notice", res.notice_with_revoked),
                ("named_first", res.named_first),
                ("superseded_reachable", res.superseded_reachable),
            )
            if value is not None
        )
        print(f"{res.id:26s} {flags}")
        if args.show:
            for line in res.top:
                print(f"    {line}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {**summary, "results": [asdict(x) for x in results]}
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
