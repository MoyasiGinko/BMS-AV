"""Django command to pause execution until the database is available."""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError
from psycopg import OperationalError as PsycopgOperationalError


class Command(BaseCommand):
    help = "Waits for the database to become available before continuing."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--timeout",
            type=int,
            default=60,
            help="Maximum seconds to wait for database before exiting (default: 60)",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Polling interval in seconds (default: 1.0)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        timeout = options["timeout"]
        interval = options["interval"]
        self.stdout.write("Waiting for database connection...")

        start_time = time.monotonic()
        connected = False

        while not connected:
            if time.monotonic() - start_time > timeout:
                self.stderr.write(self.style.ERROR(f"Database unavailable after {timeout} seconds. Exiting."))
                raise SystemExit(1)
            try:
                connection.ensure_connection()
                connected = True
            except OperationalError, PsycopgOperationalError:
                self.stdout.write("Database unavailable, waiting 1 second...")
                time.sleep(interval)

        self.stdout.write(self.style.SUCCESS("Database is available!"))
