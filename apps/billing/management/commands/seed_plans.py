"""Management command to seed default billing tiers and functional modules."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.billing.services import seed_default_plans


class Command(BaseCommand):
    help = "Seeds default billing plans (Starter, Growth, Business, Enterprise) and functional modules."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write("Seeding modules and default plans...")
        plans = seed_default_plans()
        for slug, plan in plans.items():
            self.stdout.write(self.style.SUCCESS(f"  - Plan '{plan.name}' ({slug}) ready."))
        self.stdout.write(self.style.SUCCESS(f"Done! {len(plans)} plans successfully seeded."))
