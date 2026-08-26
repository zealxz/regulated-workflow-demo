from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .errors import WorkflowError
from .leads import run_lead_assistant
from .v2ex_discovery import run_v2ex_discovery
from .workflows import run_diff, run_extract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regulated-workflow",
        description=(
            "Create offline evidence, version-change, and lead-draft review artifacts. "
            "All outputs require human approval."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser(
        "extract", help="extract a local evidence ledger from a file or directory"
    )
    extract_parser.add_argument("input", type=Path, help="input file or directory")
    extract_parser.add_argument(
        "--output-dir", type=Path, required=True, help="directory for review artifacts"
    )
    _add_remote_summary_flag(extract_parser)

    diff_parser = subparsers.add_parser(
        "diff", help="compare old and new local document versions"
    )
    diff_parser.add_argument("old", type=Path, help="old file or directory")
    diff_parser.add_argument("new", type=Path, help="new file or directory")
    diff_parser.add_argument(
        "--output-dir", type=Path, required=True, help="directory for review artifacts"
    )
    _add_remote_summary_flag(diff_parser)

    leads_parser = subparsers.add_parser(
        "leads",
        help="rank manually collected lead rows and generate review-only drafts",
    )
    leads_parser.add_argument("input", type=Path, help="manually collected lead CSV")
    leads_parser.add_argument(
        "--output-dir", type=Path, required=True, help="directory for ranked leads and drafts"
    )
    leads_parser.add_argument(
        "--as-of",
        help=(
            "timezone-aware ISO-8601 time used to calculate age from published_at; "
            "omit when age_hours is supplied"
        ),
    )

    v2ex_parser = subparsers.add_parser(
        "v2ex-discover",
        help="explicitly fetch one bounded public V2EX outsourcing page into lead CSV",
    )
    v2ex_parser.add_argument("output", type=Path, help="output CSV for the leads command")
    v2ex_parser.add_argument(
        "--max-topics",
        type=int,
        default=20,
        help="inspect at most this many topics from the single official response (1-20)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            paths = run_extract(args.input, args.output_dir, llm_summary=args.llm_summary)
        elif args.command == "diff":
            paths = run_diff(
                args.old,
                args.new,
                args.output_dir,
                llm_summary=args.llm_summary,
            )
        elif args.command == "leads":
            paths = run_lead_assistant(
                args.input,
                args.output_dir,
                as_of=args.as_of,
            )
        else:
            path = run_v2ex_discovery(args.output, max_topics=args.max_topics)
    except (WorkflowError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    if args.command == "v2ex-discover":
        print("Saved bounded public lead discovery CSV to %s" % path)
    else:
        print("Generated %d local review artifacts in %s" % (len(paths), args.output_dir))
    return 0


def _add_remote_summary_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llm-summary",
        action="store_true",
        help=(
            "explicitly send aggregate counts (never source text or values) to an "
            "environment-configured OpenAI-compatible endpoint"
        ),
    )
