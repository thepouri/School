# Data analysis command line:  python -m skool.analyze
#
# Pipeline: load data (postgres or CSV) → filter → run analyses
# → print output + write report.md / report.json / charts/*.png

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

log = logging.getLogger("skool.analyze")

DEPS_HINT = (
    "Data analysis requires the pandas / numpy / matplotlib packages.\n"
    "    Install:  uv pip install -e '.[analyze]'    or    pip install pandas numpy matplotlib"
)


def _missing_deps() -> list[str]:
    missing: list[str] = []
    for name in ("pandas", "numpy"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    return missing


# ──────────────── execution engine ────────────────


def run_analysis(
    *,
    data: Any = None,
    from_csv: str | Path | None = None,
    limit: int | None = None,
    out_dir: str | Path = "analysis_out",
    charts: bool = True,
    chart_format: str = "png",
    dpi: int = 140,
    top: int = 20,
    min_group: int = 5,
    only: Sequence[str] | None = None,
    skip: Sequence[str] | None = None,
    groups: Sequence[str] | None = None,
    detailed_only: bool = False,
    paid_only: bool = False,
    public_only: bool = False,
    min_members: int | None = None,
    categories: Sequence[str] | None = None,
    languages: Sequence[str] | None = None,
    since: str | None = None,
    dump_csv: str | Path | None = None,
    write_reports: bool = True,
    csv_tables: bool = False,
    progress: bool = True,
) -> dict[str, Any]:
    """Runs all analyses and returns the output.

    If `data` is provided, the database is not read (test/notebook path).
    """
    missing = _missing_deps()
    if missing:
        raise RuntimeError("Missing package(s): " + ", ".join(missing) + "\n" + DEPS_HINT)

    from . import analyses as _analyses  # noqa: F401  — registers analyses
    from . import charts as charts_module
    from . import loader, report as report_module
    from .registry import Context, all_metrics, run_analyses

    # 1) data
    if data is None:
        if from_csv:
            log.info("Reading data from CSV: %s", from_csv)
            data = loader.load_from_csv(from_csv)
        else:
            log.info("Reading data from postgres…")
            data = asyncio.run(loader.load_from_db(limit=limit))

    if dump_csv:
        written = loader.dump_csv(data, dump_csv)
        log.info("CSV snapshot written: %s files to %s", len(written), dump_csv)

    # 2) filters
    data = loader.apply_filters(
        data,
        detailed_only=detailed_only,
        paid_only=paid_only,
        public_only=public_only,
        min_members=min_members,
        categories=categories,
        languages=languages,
        since=since,
    )
    info = data.info()
    if info["groups"] == 0:
        raise RuntimeError(
            "No groups left to analyze. Run the scraper first or loosen the filters."
        )
    log.info(
        "Data ready: %s groups (%s paid), %s users",
        f"{info['groups']:,}",
        f"{info['paid_groups']:,}",
        f"{info['users']:,}",
    )

    # 3) chart maker
    target = Path(out_dir)
    charts_enabled = bool(charts)
    if charts_enabled and not charts_module.MATPLOTLIB_OK:
        log.warning("matplotlib is not installed — analyses will run without charts.")
        charts_enabled = False
    maker = charts_module.ChartMaker(
        target / "charts",
        enabled=charts_enabled,
        dpi=dpi,
        image_format=chart_format,
    )

    # 4) run
    ctx = Context(data=data, charts=maker, top=top, min_group=min_group)

    def on_result(result: Any) -> None:
        if not progress:
            return
        state = "ERROR" if result.error else ("EMPTY" if not (result.lines or result.tables) else "OK")
        log.info(
            "  [%s] %s — %s (%.2fs)",
            state,
            result.key,
            f"{len(result.tables)} tables, {len(result.charts)} charts",
            result.duration,
        )

    results = run_analyses(ctx, only=only, skip=skip, only_groups=groups, on_result=on_result)
    if not results:
        raise RuntimeError("No analyses matched the --only/--groups/--skip filters.")

    # 5) output
    console = report_module.render_console(results, info)
    paths: dict[str, Any] = {}
    if write_reports:
        target.mkdir(parents=True, exist_ok=True)
        paths["markdown"] = report_module.write_markdown(results, target, info)
        paths["json"] = report_module.write_json(results, target, info)
        text_path = target / "report.txt"
        text_path.write_text(console + "\n", encoding="utf-8")
        paths["text"] = text_path
        if csv_tables:
            paths["tables"] = report_module.write_tables(results, target / "tables")
    if maker.made:
        paths["charts"] = list(maker.made)

    failed = [result.key for result in results if result.error]
    if failed:
        log.warning("Analyses with errors: %s", ", ".join(failed))

    return {
        "results": results,
        "info": info,
        "console": console,
        "paths": paths,
        "failed": failed,
        "metrics": all_metrics(results),
    }


# ───────────────── arguments ────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m skool.analyze",
        description="Exploratory analysis of Skool data: price, members, engagement, owners, content, and charts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m skool.analyze                       # run all analyses from the database\n"
            "  python -m skool.analyze --list                # list analyses\n"
            "  python -m skool.analyze --only price_distribution price_vs_members\n"
            "  python -m skool.analyze --groups Price --no-charts\n"
            "  python -m skool.analyze --detailed-only --min-members 100\n"
            "  python -m skool.analyze --dump-csv snapshot     # take a snapshot\n"
            "  python -m skool.analyze --from-csv snapshot     # analyze without the database\n"
        ),
    )

    picker = parser.add_argument_group("analysis selection")
    picker.add_argument("--list", action="store_true", help="only print the list of available analyses")
    picker.add_argument("--only", nargs="+", metavar="KEY", help="run only these analyses")
    picker.add_argument("--skip", nargs="+", metavar="KEY", help="do not run these analyses")
    picker.add_argument(
        "--groups",
        nargs="+",
        metavar="TOKEN",
        help="only specific groups (group number or part of its name, e.g.: Price)",
    )

    source = parser.add_argument_group("data source")
    source.add_argument("--from-csv", metavar="DIR", help="read groups.csv/users.csv/user_groups.csv from a folder")
    source.add_argument("--dump-csv", metavar="DIR", help="write a raw data snapshot to this folder")
    source.add_argument("--limit", type=int, help="maximum number of rows read from the database (for a quick test)")

    filters = parser.add_argument_group("data filters")
    filters.add_argument("--detailed-only", action="store_true", help="only groups whose about.json has been fetched")
    filters.add_argument("--paid-only", action="store_true", help="only paid groups")
    filters.add_argument("--public-only", action="store_true", help="only public groups")
    filters.add_argument("--min-members", type=int, metavar="N", help="minimum number of members")
    filters.add_argument("--category", nargs="+", metavar="SLUG", help="only these categories")
    filters.add_argument("--language", nargs="+", metavar="LANG", help="only these languages")
    filters.add_argument("--since", metavar="DATE", help="only groups created after this date (e.g. 2024-01-01)")

    output = parser.add_argument_group("output")
    output.add_argument("--out-dir", default="analysis_out", metavar="DIR", help="output folder (default: analysis_out)")
    output.add_argument("--no-charts", action="store_true", help="do not draw charts (text and tables only)")
    output.add_argument("--no-report", action="store_true", help="do not write report.md/report.json")
    output.add_argument("--csv-tables", action="store_true", help="also write all tables as CSV")
    output.add_argument("--chart-format", default="png", choices=("png", "svg", "pdf"), help="image format for charts")
    output.add_argument("--dpi", type=int, default=140, help="image quality of charts")
    output.add_argument("--top", type=int, default=20, help="number of rows in the 'top' tables")
    output.add_argument("--min-group", type=int, default=5, help="minimum row count for a group to appear in tables")
    output.add_argument("--quiet", action="store_true", help="do not print the report to the terminal (files only)")
    output.add_argument("--log-level", default="INFO", help="DEBUG / INFO / WARNING / ERROR")
    return parser


def _print_catalog() -> None:
    from . import analyses as _analyses  # noqa: F401
    from .registry import catalog, groups_of_analyses

    grouped = groups_of_analyses()
    print(f"Total of {len(catalog())} analyses in {len(grouped)} groups:\n")
    for index, (name, specs) in enumerate(grouped.items(), start=1):
        print(f"[{index}] {name}")
        for spec in specs:
            needs = "" if spec.needs == ("groups",) else f"  (needs: {', '.join(spec.needs)})"
            print(f"    - {spec.key:<22} {spec.title}{needs}")
        print()
    print("e.g.:  python -m skool.analyze --only price_distribution")
    print("      python -m skool.analyze --groups 2 3")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - not needed on some platforms
            pass

    missing = _missing_deps()
    if missing:
        print("Missing package(s): " + ", ".join(missing), file=sys.stderr)
        print(DEPS_HINT, file=sys.stderr)
        return 2

    if args.list:
        _print_catalog()
        return 0

    try:
        outcome = run_analysis(
            from_csv=args.from_csv,
            limit=args.limit,
            out_dir=args.out_dir,
            charts=not args.no_charts,
            chart_format=args.chart_format,
            dpi=args.dpi,
            top=args.top,
            min_group=args.min_group,
            only=args.only,
            skip=args.skip,
            groups=args.groups,
            detailed_only=args.detailed_only,
            paid_only=args.paid_only,
            public_only=args.public_only,
            min_members=args.min_members,
            categories=args.category,
            languages=args.language,
            since=args.since,
            dump_csv=args.dump_csv,
            write_reports=not args.no_report,
            csv_tables=args.csv_tables,
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    except KeyError as exc:
        log.error("%s", exc)
        log.error("List of valid keys:  python -m skool.analyze --list")
        return 1

    if not args.quiet:
        print(outcome["console"])

    paths = outcome["paths"]
    if paths.get("markdown"):
        log.info("Markdown report: %s", paths["markdown"])
    if paths.get("json"):
        log.info("JSON output: %s", paths["json"])
    if paths.get("charts"):
        log.info("Charts created: %s", len(paths["charts"]))
    if paths.get("tables"):
        log.info("CSV tables: %s files", len(paths["tables"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
