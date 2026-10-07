# ADR 0001: Shared DRF infrastructure lives in apps/core/api
Status: accepted
Context: A top-level `apps/api` would sit above every module in the import layering, but each module's `api/` package needs its base classes.
Decision: Shared DRF base classes live in `apps/core/api/`; the URL aggregator is `config/api_urls.py`.
Consequences: Layer contract stays acyclic; modules own their API surface.
