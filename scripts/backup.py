#!/usr/bin/env python3
"""Cross-platform database backup utility for Business OS.

Dumps PostgreSQL database, compresses via gzip, and calculates SHA256 integrity hash.
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
    parser = argparse.ArgumentParser(description="Backup Business OS PostgreSQL database.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("backups"),
        help="Directory where backup file will be saved (default: ./backups)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate backup operations without executing pg_dump",
    )
    return parser.parse_args()


def get_db_config() -> dict[str, str]:
    db_url = os.environ.get("DATABASE_URL", "")
    return {
        "url": db_url,
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
        "db": os.environ.get("POSTGRES_DB", "bos"),
    }


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    backup_file = args.output_dir / f"bos_backup_{timestamp}.sql.gz"
    checksum_file = args.output_dir / f"bos_backup_{timestamp}.sql.gz.sha256"

    print(f"==> [{datetime.datetime.now().isoformat()}] Starting Business OS database backup...")
    print(f"    Target archive:  {backup_file}")
    print(f"    Checksum file:   {checksum_file}")

    if args.dry_run:
        print("==> [DRY RUN] Simulating backup execution...")
        with gzip.open(backup_file, "wt", encoding="utf-8") as f:
            f.write("-- Business OS Dry Run Backup\n")
        digest = compute_sha256(backup_file)
        checksum_file.write_text(f"{digest}  {backup_file.name}\n", encoding="utf-8")
        print(f"==> [DRY RUN] Completed simulation. SHA256: {digest}")
        return

    # Check pg_dump availability
    pg_dump_bin = shutil.which("pg_dump")
    if not pg_dump_bin:
        print("ERROR: pg_dump executable was not found in PATH.", file=sys.stderr)
        sys.exit(1)

    cfg = get_db_config()
    env = os.environ.copy()
    if cfg["password"]:
        env["PGPASSWORD"] = cfg["password"]

    if cfg["url"]:
        cmd = [pg_dump_bin, cfg["url"], "--no-owner", "--no-privileges"]
    else:
        cmd = [
            pg_dump_bin,
            "-h",
            cfg["host"],
            "-p",
            cfg["port"],
            "-U",
            cfg["user"],
            "-d",
            cfg["db"],
            "--no-owner",
            "--no-privileges",
        ]

    print(f"==> Executing: {' '.join(cmd)}")
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:  # noqa: S603
        with gzip.open(backup_file, "wb", compresslevel=9) as gz_out:
            shutil.copyfileobj(proc.stdout, gz_out)  # type: ignore[arg-type]
        _, stderr_data = proc.communicate()
        if proc.returncode != 0:
            print(f"ERROR: pg_dump failed with exit code {proc.returncode}:", file=sys.stderr)
            print(stderr_data.decode("utf-8", errors="replace"), file=sys.stderr)
            if backup_file.exists():
                backup_file.unlink()
            sys.exit(proc.returncode)

    digest = compute_sha256(backup_file)
    checksum_file.write_text(f"{digest}  {backup_file.name}\n", encoding="utf-8")

    size_mb = backup_file.stat().st_size / (1024 * 1024)
    print(f"==> SUCCESS: Database backup complete! Size: {size_mb:.2f} MB")
    print(f"    SHA256: {digest}")


if __name__ == "__main__":
    main()
