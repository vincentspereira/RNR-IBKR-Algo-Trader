"""No-stubs / no-damaged-code repository policy enforcement.

Enforces the binding rule defined in docs/QUANT_TRADING_MASTER_PLAN.md sections
10.4-10.6: no commented-out code blocks, no stubs, no placeholders, no
.fixed_attempt / .backup cruft outside .archive/.

Exit code:
    0 -- no violations
    1 -- one or more violations

Run as pre-commit hook (per .pre-commit-config.yaml) or standalone:
    python tools/check_no_stubs.py [path ...]

If no paths are passed, scans the entire repository (excluding .archive/, .git/,
.venv/, node_modules/, __pycache__/, graphify-out/).

Configuration thresholds live at the top of this file; adjust there, not via
CLI flags. Keeping rules in code (not config) ensures everyone sees them when
they trip a violation.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

MAX_COMMENTED_RATIO = 0.20

SKIP_DIRS = {
    ".archive",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "graphify-out",
    ".fleetview",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".tox",
}

CRUFT_SUFFIXES = (".fixed_attempt", ".backup", ".bak", ".old")

FORBIDDEN_MARKERS = (
    re.compile(r"^\s*raise\s+NotImplementedError", re.MULTILINE),
    re.compile(r"#\s*TODO\b", re.IGNORECASE),
    re.compile(r"#\s*FIXME\b", re.IGNORECASE),
    re.compile(r"#\s*XXX\b"),
    re.compile(r"#\s*HACK\b", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"\bSTUB\b"),
    re.compile(r"ROADMAP MARKER"),
)

BROKER_EXCEPTION_FILES = {
    "core_trading/adapters/brokers/alpaca.py",
    "core_trading/adapters/brokers/binance.py",
    "core_trading/adapters/brokers/coinbase.py",
    "core_trading/adapters/brokers/fxcm.py",
    "core_trading/adapters/brokers/oanda.py",
    "core_trading/adapters/brokers/trading212.py",
    "core_trading/adapters/brokers/interactive_brokers.py",
    "core_trading/adapters/brokers/factory.py",
    "core_trading/adapters/brokers/websocket_streaming.py",
    "core_trading/adapters/brokers/config_validation.py",
    "core_trading/adapters/brokers/error_handling.py",
    "core_trading/adapters/brokers/health_monitoring.py",
    "core_trading/adapters/brokers/rate_limiting.py",
    "core_trading/adapters/brokers/security.py",
}

EXEMPT_FROM_COMMENT_RATIO = {
    "tools/check_no_stubs.py",
}

ABC_DECORATORS = {"abstractmethod", "abc.abstractmethod"}


@dataclass
class Violation:
    path: Path
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"  [{self.kind}] {self.path.as_posix()} -- {self.detail}"


@dataclass
class Report:
    cruft: list[Violation] = field(default_factory=list)
    commented_ratio: list[Violation] = field(default_factory=list)
    forbidden_markers: list[Violation] = field(default_factory=list)
    not_implemented: list[Violation] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.cruft)
            + len(self.commented_ratio)
            + len(self.forbidden_markers)
            + len(self.not_implemented)
        )

    def by_category(self) -> dict[str, list[Violation]]:
        return {
            "cruft files (.fixed_attempt / .backup outside .archive/)": self.cruft,
            f"files with >{int(MAX_COMMENTED_RATIO * 100)}% commented-out code": self.commented_ratio,
            "forbidden markers (TODO/FIXME/XXX/HACK/placeholder/STUB/ROADMAP)": self.forbidden_markers,
            "NotImplementedError outside @abstractmethod": self.not_implemented,
        }


def is_skipped_dir(name: str) -> bool:
    return name in SKIP_DIRS


def iter_repo_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not is_skipped_dir(d)]
            for fn in files:
                yield Path(root) / fn


def relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def check_cruft(path: Path, report: Report) -> None:
    name = path.name
    if not any(name.endswith(suffix) for suffix in CRUFT_SUFFIXES):
        return
    rel = relative_to_repo(path)
    if rel.startswith(".archive/"):
        return
    report.cruft.append(
        Violation(path=path, kind="CRUFT", detail=f"move to .archive/ or delete (suffix={path.suffix})")
    )


def count_commented_code_lines(source: str) -> tuple[int, int]:
    """Return (commented_code_lines, total_code_lines).

    A "commented code line" is a non-empty stripped line that starts with `#`
    *and* is not a shebang. Pure prose comments still count -- the policy is
    that production code does not need >20% comment ratio either way; if you
    need that much explanation, the docstring is the right home.

    Total code lines = non-empty, non-pure-whitespace lines.
    """
    commented = 0
    total = 0
    for raw in source.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        total += 1
        if stripped.startswith("#") and not stripped.startswith("#!"):
            commented += 1
    return commented, total


def check_commented_ratio(path: Path, source: str, report: Report) -> None:
    rel = relative_to_repo(path)
    if rel in EXEMPT_FROM_COMMENT_RATIO:
        return
    commented, total = count_commented_code_lines(source)
    if total < 20:
        return
    ratio = commented / total
    if ratio > MAX_COMMENTED_RATIO:
        report.commented_ratio.append(
            Violation(
                path=path,
                kind="COMMENT_RATIO",
                detail=f"{ratio:.0%} commented ({commented}/{total} non-empty lines); max {int(MAX_COMMENTED_RATIO * 100)}%",
            )
        )


def line_of_match(source: str, match: re.Match[str]) -> int:
    return source.count("\n", 0, match.start()) + 1


def check_forbidden_markers(path: Path, source: str, report: Report) -> None:
    rel = relative_to_repo(path)
    if rel in BROKER_EXCEPTION_FILES:
        return
    if rel == "tools/check_no_stubs.py":
        return
    for pattern in FORBIDDEN_MARKERS:
        for match in pattern.finditer(source):
            if pattern.pattern.startswith(r"^\s*raise"):
                continue
            line = line_of_match(source, match)
            report.forbidden_markers.append(
                Violation(
                    path=path,
                    kind="FORBIDDEN_MARKER",
                    detail=f"line {line}: '{match.group(0).strip()}'",
                )
            )


def function_has_abstract_decorator(node: ast.AST) -> bool:
    decorators = getattr(node, "decorator_list", [])
    for dec in decorators:
        if isinstance(dec, ast.Name) and dec.id in ABC_DECORATORS:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
            return True
        if isinstance(dec, ast.Call):
            inner = dec.func
            if isinstance(inner, ast.Name) and inner.id in ABC_DECORATORS:
                return True
            if isinstance(inner, ast.Attribute) and inner.attr == "abstractmethod":
                return True
    return False


def check_not_implemented(path: Path, source: str, report: Report) -> None:
    rel = relative_to_repo(path)
    if rel in BROKER_EXCEPTION_FILES:
        return
    if rel == "tools/check_no_stubs.py":
        return
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_abstract = False
            self.violations: list[int] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_func(node)

        def _visit_func(self, node: ast.AST) -> None:
            prev = self.in_abstract
            if function_has_abstract_decorator(node):
                self.in_abstract = True
            self.generic_visit(node)
            self.in_abstract = prev

        def visit_Raise(self, node: ast.Raise) -> None:
            if self.in_abstract:
                return
            exc = node.exc
            name: str | None = None
            if isinstance(exc, ast.Call):
                inner = exc.func
                if isinstance(inner, ast.Name):
                    name = inner.id
                elif isinstance(inner, ast.Attribute):
                    name = inner.attr
            elif isinstance(exc, ast.Name):
                name = exc.id
            elif isinstance(exc, ast.Attribute):
                name = exc.attr
            if name == "NotImplementedError":
                self.violations.append(node.lineno)
            self.generic_visit(node)

    v = Visitor()
    v.visit(tree)
    for lineno in v.violations:
        report.not_implemented.append(
            Violation(
                path=path,
                kind="NOT_IMPLEMENTED",
                detail=f"line {lineno}: raise NotImplementedError outside @abstractmethod",
            )
        )


def check_file(path: Path, report: Report) -> None:
    check_cruft(path, report)
    if path.suffix != ".py":
        return
    rel_parts = path.parts
    if ".archive" in rel_parts:
        return
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    check_commented_ratio(path, source, report)
    check_forbidden_markers(path, source, report)
    check_not_implemented(path, source, report)


def main(argv: list[str]) -> int:
    if argv:
        paths = [Path(a).resolve() for a in argv]
    else:
        paths = [REPO_ROOT]

    report = Report()
    for path in iter_repo_files(paths):
        check_file(path, report)

    if report.total == 0:
        print("[no_stubs] OK -- no violations detected")
        return 0

    print(f"[no_stubs] FAIL -- {report.total} violation(s)")
    print()
    for category, items in report.by_category().items():
        if not items:
            continue
        print(f"=== {len(items)} {category} ===")
        for v in items[:25]:
            print(str(v))
        if len(items) > 25:
            print(f"  ... and {len(items) - 25} more")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
