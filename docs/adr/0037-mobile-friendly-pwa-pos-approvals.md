# 0037. Mobile-Friendly PWA Shell for POS and Approvals

Date: 2026-10-14

## Context
Backlog item P6-05 specifies a mobile-friendly Progressive Web App (PWA) shell focused on Point of Sale (POS) and Approvals. Fast counter retail checkout and manager document approvals frequently occur on mobile handheld terminals, tablets, and phones. The application requires:
1. Standard Web App Manifest (`manifest.webmanifest`) declaring standalone display mode, brand tokens, and shortcuts to POS and Approvals.
2. Root-scoped Service Worker (`/service-worker.js`) caching critical static assets (tokens, Tailwind CSS, Alpine.js, HTMX, icons) with stale-while-revalidate / cache-first strategies and an offline fallback page (`/offline/`).
3. Responsive mobile polish for POS terminal (touch targets >= 44px, catalog vs cart mobile tab switching, sticky mobile checkout bar) and Approvals (responsive card list alternative to 9-column tables, full-width touch decision buttons).

## Decision
1. **PWA Manifest & Routing (`apps/core/pwa_views.py`, `config/urls.py`)**:
   - Serve `/manifest.webmanifest` and `/manifest.json` with `Content-Type: application/manifest+json`.
   - Specify `name: "Business OS"`, `short_name: "Business OS"`, `display: "standalone"`, `theme_color: "#0f172a"`, and quick shortcuts to `/pos/`, `/approvals/`, `/dashboard/`, and `/ai/attention/items/`.
   - Provide high-resolution vector and maskable SVG app icons under `static/icons/`.
2. **Service Worker Architecture**:
   - Serve `/service-worker.js` with `Content-Type: application/javascript; charset=utf-8` and `Service-Worker-Allowed: /` HTTP header to allow origin-wide control.
   - Cache-first strategy for static assets (`/static/*`) with versioned cache name (`bos-shell-v1`).
   - Network-first strategy for HTML navigations (`mode === 'navigate'`), falling back to `/offline/` when connectivity is lost.
   - Clean up stale cache versions on the `activate` event and handle `SKIP_WAITING` messages for background app updates.
3. **Offline Fallback Experience (`templates/offline.html`)**:
   - Render a Calm Ledger offline screen informing users of connectivity status with a one-click "Check Connection & Reload" action and quick links back to cached routes.
4. **Mobile Responsive Polish**:
   - **POS Terminal (`apps/pos/templates/pos/terminal.html`)**: Add mobile tab switcher (`Products` vs `Cart`), sticky mobile cart bar with item count and subtotal, touch-friendly stepper buttons (`min-w-[36px] min-h-[36px]`), and touch-optimized tender modal keypad.
   - **Approvals Inbox (`apps/approvals/templates/approvals/partials/inbox_table.html`)**: Provide a mobile-first card list layout for viewports `< 768px` alongside the desktop tabular view, featuring large touch-friendly Approve/Reject buttons (`min-h-[44px]`).
   - **Base & App Shell (`templates/layouts/base.html`, `templates/layouts/app.html`)**: Inject PWA manifest links, Apple mobile web app tags, service worker registration script, and an `Install App` prompt handler.

## Consequences
- Fast, native-feeling experience on tablets and smartphones with standalone launcher icons.
- Reliable offline resilience for cached UI assets; graceful degradation when network connectivity drops.
- Seamless touch operation on 360px+ screens for counter cashiers and travelling executives approving orders.
