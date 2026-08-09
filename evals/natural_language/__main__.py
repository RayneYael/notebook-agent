"""CLI for explicit paid live evaluations."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import Settings
from .runner import (
    EvalConfig,
    EvalPreflightError,
    EvalTeardownError,
    LiveEvaluator,
    write_preflight_failure,
    write_report,
)
from .schema import CatalogError, load_catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.natural_language")
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ("validate-catalog", "preflight", "prepare-fixtures", "smoke", "all"):
        mode.add_argument(f"--{flag}", action="store_true")
    mode.add_argument("--case", action="append", dest="case_ids")
    mode.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--results-dir", type=Path)
    return parser


async def _live(args, catalog) -> int:
    config = EvalConfig.from_environment()
    repeat = args.repeat if args.repeat is not None else config.repeat
    threshold = args.threshold if args.threshold is not None else config.threshold
    if not 1 <= repeat <= 20 or (threshold is not None and not 0 < threshold <= 1):
        raise EvalPreflightError("repeat or threshold is out of bounds")
    config = EvalConfig(config.enabled, config.user_id, args.results_dir or config.results_dir, repeat, threshold, config.ingest_timeout_seconds)
    settings = Settings()
    evaluator = LiveEvaluator(catalog, settings, config)
    results = None
    try:
        await evaluator.__aenter__()
    except EvalTeardownError:
        target = write_preflight_failure(
            config, catalog, settings, error_code="teardown_failed",
            failure_stage="infrastructure",
        )
        print(f"sanitized teardown report: {target}", file=sys.stderr)
        raise
    except Exception:
        target = write_preflight_failure(config, catalog, settings, error_code="preflight_unavailable")
        print(f"sanitized preflight report: {target}", file=sys.stderr)
        raise EvalPreflightError("live evaluation preflight failed") from None
    try:
        if args.preflight:
            print("preflight ok: full stack and full MCP profile ready")
            return 0
        try:
            fixtures = await evaluator.prepare()
        except Exception:
            target = write_preflight_failure(config, catalog, settings, error_code="fixture_unavailable", failure_stage="fixture")
            print(f"sanitized fixture report: {target}", file=sys.stderr)
            raise EvalPreflightError("live evaluation fixture failed") from None
        if args.prepare_fixtures:
            print("fixtures ready and retained")
            return 0
        cases = _select(args, catalog.cases)
        if not cases:
            raise EvalPreflightError("no catalog cases matched")
        results = await evaluator.run(cases, repeat=repeat, threshold=threshold)
        failed = sum(value.status == "fail" for value in results)
    finally:
        try:
            await evaluator.__aexit__(None, None, None)
        except EvalTeardownError:
            target = write_preflight_failure(
                config,
                catalog,
                settings,
                error_code="teardown_failed",
                failure_stage="infrastructure",
            )
            print(f"sanitized teardown report: {target}", file=sys.stderr)
            raise
    # A success/model-result report is authoritative only after the temporary
    # grant is revoked and the MCP subprocess + stderr tempfile are closed.
    assert results is not None
    target = write_report(evaluator, results)
    print(f"{sum(value.status == 'pass' for value in results)} pass / {failed} fail / {sum(value.status == 'skip' for value in results)} skip")
    print(f"sanitized report: {target}")
    return 1 if failed else 0


def _select(args, cases):
    if args.all:
        return list(cases)
    if args.smoke:
        return [case for case in cases if case.smoke]
    if args.case_ids:
        requested = set(args.case_ids)
        found = [case for case in cases if case.id in requested]
        if requested - {case.id for case in found}:
            raise EvalPreflightError("unknown case id")
        return found
    if args.categories:
        return [case for case in cases if case.category in set(args.categories)]
    return []


def main() -> None:
    args = _parser().parse_args()
    try:
        catalog = load_catalog(args.catalog)
        if args.validate_catalog:
            print(f"catalog {catalog.version}: {len(catalog.cases)} cases valid")
            return
        raise SystemExit(asyncio.run(_live(args, catalog)))
    except (CatalogError, EvalPreflightError, EvalTeardownError, RuntimeError) as exc:
        print(f"natural-language eval unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except Exception:
        print(
            "natural-language eval unavailable: bounded infrastructure failure",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
