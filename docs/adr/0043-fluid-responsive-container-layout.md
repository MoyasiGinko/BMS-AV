# ADR 0043: Fluid Responsive Main Container Layout Across All Screen Sizes
Status: accepted | Date: 2026-10-23
Context: The main body container was previously capped at `--content-max: 1400px`, creating artificial dead margin on modern 1080p (1920px), 1440p (2560px), and ultrawide monitors and squishing dense ERP data tables.
Decision: Set `--content-max: 100%` in `tokens.css` and expose a `{% block container_class %}` hook in `templates/layouts/app.html`, enabling fully fluid, edge-to-edge responsiveness with clean 16-32px gutters across all screen widths.
Consequences: Data tables, charts, POS, and dashboards expand fluidly to fill wide viewports with optimal data density; narrow pages (such as auth and settings) maintain their own internal container max-width without visual regression.
