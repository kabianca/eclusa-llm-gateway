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
    rec = sub.add_parser("record", help="run the generation cases live, once (ECLUSA_LIVE=1)")
    rec.add_argument("--corpus", type=Path, default=Path("corpus"))
    rec.add_argument("--index", type=Path, default=Path("var/index"))
    rec.add_argument("--out", type=Path, default=Path("eval/generation"))
    rec.add_argument("--ceiling-usd", type=float, default=0.02, help="per request, hard stop")
    rec.add_argument(
        "--max-total-usd", type=float, default=0.50, help="per run, worst cases summed"
    )
    rec.add_argument(
        "--only",
        nargs="+",
        metavar="CASE_ID",
        help="record just these cases; the cassette is append-only, so spend one call first",
    )
    dri = sub.add_parser(
        "drift", help="run the frozen cases against the live model and report the distance"
    )
    dri.add_argument("--corpus", type=Path, default=Path("corpus"))
    dri.add_argument("--index", type=Path, default=Path("var/index"))
    dri.add_argument("--out", type=Path, default=Path("eval/generation"))
    dri.add_argument("--report", type=Path, default=None, help="write the report as JSON")
    dri.add_argument("--ceiling-usd", type=float, default=0.02)
    rev = sub.add_parser("review", help="print the recorded answers in a readable form, to grade")
    rev.add_argument("--out", type=Path, default=Path("eval/generation"))
    rev.add_argument("--only", nargs="+", metavar="CASE_ID")
    gen = sub.add_parser(
        "generation", help="replay the generation cases in recorded mode (the gate)"
    )
    gen.add_argument("--corpus", type=Path, default=Path("corpus"))
    gen.add_argument("--index", type=Path, default=Path("var/index"))
    gen.add_argument("--out", type=Path, default=Path("eval/generation"))
    args = parser.parse_args(argv)

    if args.command == "review":
        return _review(args)
    if args.command in ("record", "generation", "drift"):
        return _generation(args)

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
                ("amendment", res.amendment_text_reachable),
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


def _review(args) -> int:
    """What the author reads to grade: the question, why the case exists, and the answer."""
    import json
    import textwrap

    from eclusa.eval import generation as gen_mod

    cases = gen_mod.load_cases().cases
    if args.only:
        cases = [c for c in cases if c.id in set(args.only)]
    for case in cases:
        path = args.out / "responses" / f"{case.id}.json"
        if not path.exists():
            print(f"\n## {case.id} — not recorded")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        response = payload["response"]
        print("\n" + "=" * 98)
        print(
            f"## {case.id}  [{case.kind}]  esperado={case.expected.outcome}  "
            f"veio={response['outcome']}  (audit={payload['audit_outcome']})"
        )
        print(f"P: {case.question}")
        print(textwrap.fill(f"porquê do caso: {case.why}", 98, subsequent_indent="   "))
        if response.get("refusal_reason"):
            note = response.get("refusal_note") or ""
            print(f"RECUSA ({response['refusal_reason']}): {note}"[:400])
        draft = response.get("draft")
        if draft:
            for i, s in enumerate(draft["statements"], 1):
                print("\n" + textwrap.fill(f"[{i}] {s['text']}", 98, subsequent_indent="    "))
                for c in s["citations"]:
                    print(f"     -> {c['doc_id']}  {c['locator']}")
            for g in draft.get("gaps", []):
                print("\n" + textwrap.fill(f"LACUNA: {g['text']}", 98, subsequent_indent="    "))
                print(f"     onde: {g.get('where')}")
    return 0


def _generation(args) -> int:
    import json
    from datetime import date

    from eclusa.eval import generation as gen_mod
    from eclusa.eval.record import NotLive, record
    from eclusa.service.ask import Gateway
    from eclusa.service.audit import AuditLog
    from eclusa.service.budget import Budget
    from eclusa.service.prompts import Prompt
    from eclusa.service.provider import provider_from_env

    manifest = manifest_mod.load(args.corpus / "manifest.json")
    # The drift run must never touch the cassette the gate replays: it asks the live model
    # on purpose, and its answers are evidence of today, not the recordings of that day.
    trails = {
        "record": "audit-record.jsonl",
        "generation": "audit-gate.jsonl",
        "drift": "audit-drift.jsonl",
    }
    cassette = args.out / (
        "drift/cassette.jsonl" if args.command == "drift" else "recordings.jsonl"
    )
    trail = args.out / trails[args.command]
    gateway = Gateway(
        manifest=manifest,
        manifest_path=args.corpus / "manifest.json",
        corpus_dir=args.corpus,
        index=IndexStore.load(args.index),
        embedder=Embedder.pinned(threads=4),
        provider=provider_from_env(cassette),
        budget=Budget(getattr(args, "ceiling_usd", 0.02)),
        audit=AuditLog(trail),
        prompt=Prompt.load("answer-v1"),
    )
    cases = gen_mod.load_cases()
    if args.command == "drift":
        from datetime import date as _date

        from eclusa.eval.drift import run as drift_run
        from eclusa.service.provider import RecordingProvider

        if not isinstance(gateway.provider, RecordingProvider):
            print("the drift monitor only runs live: set ECLUSA_LIVE=1 and OPENAI_API_KEY")
            return 1
        report = drift_run(cases, gateway, args.out, _date.today())
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        for r in report["results"]:
            flags = []
            if r["recorded_outcome"] != r["live_outcome"]:
                flags.append(f"outcome {r['recorded_outcome']} -> {r['live_outcome']}")
            if set(r["recorded_citations"]) != set(r["live_citations"]):
                flags.append("citations moved")
            if r["recorded_audit"] != r["live_audit"]:
                flags.append(f"audit {r['recorded_audit']} -> {r['live_audit']}")
            print(f"{'MOVED' if flags else 'same ':5s} {r['case_id']:24s} {'; '.join(flags)}")
        print(
            f"\n{report['cases']} cases, {report['moved']} moved, "
            f"recordings {report['recordings_age_days']} days old, US$ {report['cost_usd']}"
        )
        # Never gates: drift is information to observe, not a reason to fail a build.
        return 0
    if getattr(args, "only", None):
        chosen = [c for c in cases.cases if c.id in set(args.only)]
        missing = set(args.only) - {c.id for c in chosen}
        if missing:
            print(f"no such case: {', '.join(sorted(missing))}")
            return 1
        cases = cases.model_copy(update={"cases": tuple(chosen)})
    if args.command == "record":
        try:
            done = record(cases, gateway, args.out, args.max_total_usd, date.today())
        except NotLive as exc:
            print(exc)
            return 1
        total = sum(d.cost_usd for d in done)
        violations = sum(d.audit_outcome == "contract_violation" for d in done)
        for d in done:
            print(
                f"{d.case_id:24s} {d.outcome:9s} audit={d.audit_outcome:18s} US$ {d.cost_usd:.5f}"
            )
        print(
            f"{len(done)} cases, US$ {total:.4f}, {violations} contract violations "
            f"-> grade in {args.out}/grades.json"
        )
        return 0
    results = gen_mod.gate(cases, gateway, args.out)
    bad = ungraded = 0
    for r in results:
        bad += not r.ok
        ungraded += r.needs_grade and (r.grade is None or r.grade.verdict is None)
        detail = "; ".join(r.comparison.mismatches)
        print(f"{r.status:9s} {r.case_id:24s} audit={r.audit_outcome} {detail}")
        if r.grade and r.grade.notes:
            print(f"          note: {r.grade.notes}")
    print(f"{len(results)} cases, {bad} failing, {ungraded} awaiting a verdict")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
