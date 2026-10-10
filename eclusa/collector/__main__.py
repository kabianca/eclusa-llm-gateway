"""``python -m eclusa.collector``: refresh the corpus snapshot from the plan.

Exit status is non-zero when any document drifted or failed, so a scheduled run
cannot pass silently while the snapshot and the source disagree.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from eclusa.collector import plan as plan_mod
from eclusa.collector.bcb import IncompleteRun, Outcome, collect, polite_fetcher, reextract
from eclusa.corpus import manifest as manifest_mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eclusa.collector", description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    parser.add_argument(
        "--refresh",
        nargs="*",
        default=[],
        metavar="DOC_ID",
        help="replace the captured bytes of these documents even if they drifted",
    )
    parser.add_argument(
        "--reextract",
        action="store_true",
        help="no network: rebuild corpus/text from corpus/raw with the current extractor",
    )
    args = parser.parse_args(argv)

    plan = plan_mod.load(args.corpus / "plan.json")
    manifest_path = args.corpus / "manifest.json"
    manifest = manifest_mod.load(manifest_path) if manifest_path.exists() else None
    if args.reextract:
        if manifest is None:
            print("nothing to re-extract: no manifest")
            return 1
        new_manifest, outcomes = reextract(manifest, args.corpus)
        manifest_path.write_text(
            new_manifest.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
        )
        _report(outcomes)
        return 0
    try:
        new_manifest, outcomes = collect(
            plan,
            manifest,
            args.corpus,
            polite_fetcher(args.delay),
            date.today(),
            frozenset(args.refresh),
        )
    except IncompleteRun as exc:
        _report(exc.outcomes)
        print(f"manifest not written: {exc}")
        return 1
    manifest_path.write_text(
        new_manifest.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
    )
    return _report(outcomes)


def _report(outcomes: list[Outcome]) -> int:
    for outcome in outcomes:
        print(f"{outcome.action:9s} {outcome.doc_id}  {outcome.detail}")
        for warning in outcome.warnings:
            print(f"          ! {warning}")
    bad = [o for o in outcomes if o.action in ("drift", "error")]
    print(f"{len(outcomes)} documents: {len(bad)} drifted or failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
