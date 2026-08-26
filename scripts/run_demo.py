#!/usr/bin/env python3
"""Run both offline demos and build their workbook presentation artifacts."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-workbooks",
        action="store_true",
        help="generate canonical JSON/CSV/Markdown/JSONL only",
    )
    return parser.parse_args()


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    rendered = " ".join(command)
    print("$ %s" % rendered, flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    args = parse_args()
    python_env = os.environ.copy()
    source_path = str(ROOT / "src")
    current_python_path = python_env.get("PYTHONPATH")
    python_env["PYTHONPATH"] = (
        source_path if not current_python_path else source_path + os.pathsep + current_python_path
    )
    python_env["PYTHONDONTWRITEBYTECODE"] = "1"

    extract_dir = ROOT / "outputs" / "extract"
    diff_dir = ROOT / "outputs" / "diff"
    extract_dir.mkdir(parents=True, exist_ok=True)
    diff_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            "-m",
            "regulated_workflow",
            "extract",
            "samples/new",
            "--output-dir",
            str(extract_dir),
        ],
        env=python_env,
    )
    run(
        [
            sys.executable,
            "-m",
            "regulated_workflow",
            "diff",
            "samples/old",
            "samples/new",
            "--output-dir",
            str(diff_dir),
        ],
        env=python_env,
    )

    if not args.skip_workbooks:
        node = os.environ.get("REGULATED_WORKFLOW_NODE") or shutil.which("node")
        if not node:
            raise SystemExit(
                "Node.js is required for XLSX export. Set REGULATED_WORKFLOW_NODE or use --skip-workbooks."
            )
        verification_root = ROOT / "artifacts" / "verification"
        run(
            [
                node,
                "scripts/build_workbooks.mjs",
                "--kind",
                "evidence",
                "--input",
                str(extract_dir / "evidence.json"),
                "--audit",
                str(extract_dir / "audit.jsonl"),
                "--output",
                str(extract_dir / "evidence.xlsx"),
                "--verify-dir",
                str(verification_root / "evidence"),
            ]
        )
        run(
            [
                node,
                "scripts/build_workbooks.mjs",
                "--kind",
                "changes",
                "--input",
                str(diff_dir / "changes.json"),
                "--audit",
                str(diff_dir / "audit.jsonl"),
                "--output",
                str(diff_dir / "changes.xlsx"),
                "--verify-dir",
                str(verification_root / "changes"),
            ]
        )

    print("Demo outputs are ready under %s" % (ROOT / "outputs"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
