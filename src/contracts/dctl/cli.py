"""Command line entry point: dctl validate | generate | diff | check-breaking."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from dctl import __version__
from dctl.diff import DiffReport, diff
from dctl.generators import render_all
from dctl.model import Contract
from dctl.target import Target
from dctl.validate import Finding, contract_files, load_contracts, validate_document, validate_file

DEFAULT_CONTRACTS = Path("contracts")
DEFAULT_OUT = Path("generated")


def _annotate(level: str, file: Path | str, message: str) -> None:
    """Print a GitHub Actions annotation when running in a workflow."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} file={file}::{message}")


def _report_findings(problems: dict[Path, list[Finding]]) -> None:
    for path, findings in problems.items():
        for finding in findings:
            print(f"FAIL {path}: {finding}")
            _annotate("error", path, str(finding))


def cmd_validate(args: argparse.Namespace) -> int:
    contracts, problems = load_contracts(args.paths or [DEFAULT_CONTRACTS])
    for contract in contracts:
        print(f"ok   {contract.source}  {contract.id} {contract.version}")
    _report_findings(problems)
    print(f"{len(contracts)} valid, {sum(len(f) for f in problems.values())} finding(s)")
    return 1 if problems else 0


def _target(args: argparse.Namespace) -> Target:
    return Target(args.catalog, args.storage_account, args.internal_container, args.shared_container)


def cmd_generate(args: argparse.Namespace) -> int:
    contracts, problems = load_contracts([args.contracts])
    if problems:
        _report_findings(problems)
        return 1
    files = render_all(contracts, _target(args))
    out: Path = args.out
    if args.check:
        stale = [p for p, text in files.items() if not (out / p).is_file() or (out / p).read_text("utf-8") != text]
        existing = {p.relative_to(out) for p in out.rglob("*") if p.is_file()} if out.is_dir() else set()
        orphans = sorted(existing - files.keys())
        for path in stale:
            print(f"stale  {out / path}")
            _annotate("error", out / path, "out of date, run dctl generate")
        for path in orphans:
            print(f"orphan {out / path}")
        if stale or orphans:
            print("generated files are out of date: run `dctl generate` and commit the result")
            return 1
        print(f"{len(files)} generated files up to date")
        return 0
    for path, text in files.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} files to {out}")
    return 0


def _print_report(report: DiffReport, where: str) -> int:
    print(f"{where}: {report.contract_id} {report.old_version} -> {report.new_version}")
    if not report.changes:
        print("  no change")
    for change in report.changes:
        print(f"  {change}")
    errors = report.gate_errors()
    for error in errors:
        print(f"  BLOCKED {error}")
        _annotate("error", where, error)
    return 1 if errors else 0


def _load_base(text: str | None, label: str) -> Contract | None:
    doc = yaml.safe_load(text) if text else None
    if not isinstance(doc, dict):
        return None
    contract, findings = validate_document(doc)
    for finding in findings:
        print(f"FAIL {label}: {finding}")
    return contract


def cmd_diff(args: argparse.Namespace) -> int:
    old, old_findings = validate_file(args.old)
    new, new_findings = validate_file(args.new)
    for label, findings in ((args.old, old_findings), (args.new, new_findings)):
        for finding in findings:
            print(f"FAIL {label}: {finding}")
    if old is None or new is None:
        return 2
    return _print_report(diff(old, new), str(args.new))


def _git_show(ref: str, path: Path) -> str | None:
    result = subprocess.run(["git", "show", f"{ref}:{path.as_posix()}"], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def _git_ls(ref: str, directory: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-tree", "--name-only", f"{ref}:{directory.as_posix()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [directory / name for name in result.stdout.split() if name.endswith((".yaml", ".yml"))]


def cmd_check_breaking(args: argparse.Namespace) -> int:
    directory: Path = args.contracts
    current = {p.as_posix() for p in contract_files([directory])} if directory.is_dir() else set()
    base = {p.as_posix() for p in _git_ls(args.base_ref, directory)}
    status = 0
    for gone in sorted(base - current):
        message = "contract deleted, set status: deprecated in a release first"
        print(f"{gone}: BLOCKED {message}")
        _annotate("error", gone, message)
        status = 1
    for path_text in sorted(current):
        path = Path(path_text)
        new, findings = validate_file(path)
        if new is None:
            _report_findings({path: findings})
            status = 1
            continue
        if path_text not in base:
            print(f"{path}: new contract {new.id} {new.version}")
            continue
        old = _load_base(_git_show(args.base_ref, path), f"{args.base_ref}:{path}")
        if old is None:
            print(f"{path}: base version does not validate, compared as new")
            continue
        status |= _print_report(diff(old, new), str(path))
    print("breaking change gate: " + ("passed" if status == 0 else "failed"))
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dctl", description=__doc__)
    parser.add_argument("--version", action="version", version=f"dctl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate contracts against the JSON schema and the semantic rules")
    p.add_argument("paths", nargs="*", type=Path, help="files or directories, default contracts/")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("generate", help="render expectations, DDL, TMDL and docs")
    p.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--check", action="store_true", help="fail when the files on disk differ, write nothing")
    defaults = Target()
    p.add_argument("--catalog", default=defaults.catalog)
    p.add_argument("--storage-account", default=defaults.storage_account)
    p.add_argument("--internal-container", default=defaults.internal_container)
    p.add_argument("--shared-container", default=defaults.shared_container)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("diff", help="classify the changes between two versions of a contract")
    p.add_argument("old", type=Path)
    p.add_argument("new", type=Path)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("check-breaking", help="compare every contract with a git ref, the CI gate")
    p.add_argument("--base-ref", required=True, help="for example origin/main")
    p.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS)
    p.set_defaults(func=cmd_check_breaking)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
