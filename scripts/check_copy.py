"""CI script to audit translatable UI copy strings against AGENTS.md rules.

Fails on forbidden buzzwords, marketing filler, jargon, and repeated-word typos.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

FORBIDDEN_WORDS = [
    "seamless",
    "effortless",
    "powerful",
    "robust",
    "comprehensive",
    "supercharge",
    "streamline",
    "enterprise-grade",
    "all-in-one",
    "at a glance",
    "in one place",
    "great news!",
    "let's get started",
    "please note that",
    "in order to",
]

REPEATED_WORDS = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
TRANS_TAG = re.compile(r'{%\s*trans\s+["\'](.*?)["\']\s*%}')
GETTEXT_CALL = re.compile(r'_\(["\'](.*?)["\']\)')

ALLOWLIST = {
    # System legal or technical requirements
    "PostgreSQL",
    "Redis",
    # Theme manager explicit unlocking action
    "Unlock & Edit in Custom",
    'id="unlock-custom-sidebar-btn"',
}


def scan_file(file_path: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return found

    if file_path.suffix == ".html":
        for m in TRANS_TAG.findall(content):
            found.append((str(file_path), m))
    elif file_path.suffix == ".py":
        for m in GETTEXT_CALL.findall(content):
            found.append((str(file_path), m))
    return found


def audit_strings(found_strings: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    violations: list[tuple[str, str, str]] = []
    for filepath, text in found_strings:
        if text in ALLOWLIST:
            continue
        lower = text.lower()
        for word in FORBIDDEN_WORDS:
            if word in lower:
                violations.append((filepath, text, f"Forbidden word '{word}'"))
        rep = REPEATED_WORDS.search(text)
        if rep:
            violations.append((filepath, text, f"Repeated word '{rep.group(0)}'"))
    return violations


def main() -> int:
    found_strings: list[tuple[str, str]] = []
    ignore_dirs = {".venv", ".git", "node_modules", "brain", "docs/archive"}

    for root, _dirs, files in os.walk("."):
        if any(x in root for x in ignore_dirs):
            continue
        for f in files:
            if f.endswith(".html") or (f.endswith(".py") and not f.startswith("test_")):
                p = Path(root) / f
                found_strings.extend(scan_file(p))

    violations = audit_strings(found_strings)
    if violations:
        print(f"FAILED: Found {len(violations)} copy rule violation(s):", file=sys.stderr)
        for filepath, text, reason in violations:
            print(f'  {filepath}: {reason} -> "{text}"', file=sys.stderr)
        return 1

    print(f"PASSED: Audited {len(found_strings)} translatable UI strings. 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
