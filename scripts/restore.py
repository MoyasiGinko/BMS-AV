#!/usr/bin/env python3
"""Cross-platform database restore utility for Business OS.

Verifies SHA256 checksum and restores PostgreSQL database from a compressed dump file.
Works seamlessly on Linux, macOS, and Windows.
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore Business OS PostgreSQL database from backup.")
    parser.add_argument(
        "file",
        type=Path,
        help="Path to the backup file (.sql.gz)",
    )
    parser.add_argument(
        "--skip-checksum",
        action="store_true",
        help="Skip SHA256 integrity verification before restore",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate restore verification without executing psql",
    )
    return parser.parse_args()


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_checksum(backup_file: Path) -> bool:
    checksum_file = backup_file.parent / f"{backup_file.name}.sha256"
    if not checksum_file.exists():
        print(f"WARNING: Checksum file '{checksum_file}' does not exist. Skipping verification.")
        return True

    expected = checksum_file.read_text(encoding="utf-8").split()[0].strip().lower()
    actual = compute_sha256(backup_file).lower()

    if expected != actual:
        print("ERROR: Checksum mismatch! Corrupt or altered backup file.", file=sys.stderr)
        print(f"       Expected: {expected}", file=sys.stderr)
        print(f"       Actual:   {actual}", file=sys.stderr)
        return False

    print("==> SHA256 checksum verification: OK!")
    return True


def get_db_config() -> dict[str, str]:
    return {
        "url": os.environ.get("DATABASE_URL", ""),
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
        "db": os.environ.get("POSTGRES_DB", "bos"),
    }


def main() -> None:
    args = parse_args()

    if not args.file.exists():
        print(f"ERROR: Backup file '{args.file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"==> [{datetime.datetime.now().isoformat()}] Starting database restore from {args.file}...")

    if not args.skip_checksum and not verify_checksum(args.file):
        sys.exit(1)

    if args.dry_run:
        print("==> [DRY RUN] Verify decompressed archive readable...")
        try:
            with gzip.open(args.file, "rt", encoding="utf-8", errors="replace") as gz_in:
                first_lines = [gz_in.readline() for _ in range(5)]
            print(f"==> [DRY RUN] Header verification successful ({len(first_lines)} lines read).")
            print("==> [DRY RUN] Restore simulation complete.")
            return
        except Exception as exc:
            print(f"ERROR: Decompressing archive failed: {exc}", file=sys.stderr)
            sys.exit(1)

    psql_bin = shutil.which("psql")
    if not psql_bin:
        print("ERROR: psql executable was not found in PATH.", file=sys.stderr)
        sys.exit(1)

    cfg = get_db_config()
    env = os.environ.copy()
    if cfg["password"]:
        env["PGPASSWORD"] = cfg["password"]

    if cfg["url"]:
        cmd = [psql_bin, cfg["url"], "--quiet"]
    else:
        cmd = [
            psql_bin,
            "-h",
            cfg["host"],
            "-p",
            cfg["port"],
            "-U",
            cfg["user"],
            "-d",
            cfg["db"],
            "--quiet",
        ]

    print(f"==> Executing restore via: {' '.join(cmd)}")
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, env=env) as proc:  # noqa: S603
        with gzip.open(args.file, "rb") as gz_in:
            shutil.copyfileobj(gz_in, proc.stdin)  # type: ignore[arg-type]
        proc.stdin.close()  # type: ignore[union-attr]
        proc.wait()

        if proc.returncode != 0:
            print(f"ERROR: Restore failed with return code {proc.returncode}.", file=sys.stderr)
            sys.exit(proc.returncode)

    print("==> SUCCESS: Database restore completed successfully!")


if __name__ == "__main__":
    main()
