"""PWA Views for Progressive Web App shell, Service Worker, and Manifest (P6-05)."""

from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

SERVICE_WORKER_CODE = """// Business OS Service Worker (bos-shell-v1)
const CACHE_NAME = 'bos-shell-v1';
const STATIC_ASSETS = [
  '/',
  '/offline/',
  '/pos/',
  '/approvals/',
  '/static/css/tokens.css',
  '/static/css/tailwind.css',
  '/static/vendor/alpine.min.js',
  '/static/vendor/alpine-focus.min.js',
  '/static/vendor/alpine-collapse.min.js',
  '/static/vendor/htmx.min.js',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg'
];

// Install: pre-cache critical shell assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('PWA Pre-cache notice:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Activate: purge stale cache versions
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: Stale-While-Revalidate for static assets, Network-First for HTML navigations
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Non-GET requests (mutations, checkouts, approvals) must always hit network directly
  if (request.method !== 'GET') {
    return;
  }

  // 1. Static assets: Cache-first / Stale-While-Revalidate
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) {
          // Revalidate in background
          fetch(request).then((networkRes) => {
            if (networkRes && networkRes.status === 200) {
              caches.open(CACHE_NAME).then((cache) => cache.put(request, networkRes));
            }
          }).catch(() => {/* offline silent */});
          return cached;
        }
        return fetch(request).then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      })
    );
    return;
  }

  // 2. HTML navigation requests: Network-First with Offline Fallback
  const isNav = request.mode === 'navigate' ||
    (request.headers.get('accept') && request.headers.get('accept').includes('text/html'));

  if (isNav) {
    event.respondWith(
      fetch(request).then((response) => {
        // Cache successful page views in shell cache
        if (response && response.status === 200) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      }).catch(async () => {
        // Try cached version of this exact URL
        const cached = await caches.match(request);
        if (cached) {
          return cached;
        }
        // Fallback to offline shell page
        const offlinePage = await caches.match('/offline/');
        if (offlinePage) {
          return offlinePage;
        }
        return new Response(
          '<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:40px;">' +
          '<h1>Offline</h1><p>Business OS server unreachable.</p>' +
          '<button onclick="window.location.reload()">Retry</button></body></html>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      })
    );
    return;
  }

  // 3. Default fallback: network with cache fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

// Support immediate reload on SKIP_WAITING message
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
"""


@require_GET
def manifest_view(request: HttpRequest) -> HttpResponse:
    """Serve the Web App Manifest (manifest.webmanifest) for PWA installation."""
    org = getattr(request, "organization", None)
    app_name = f"{org.name} - Business OS" if org else "Business OS - ERP"
    short_name = org.name[:12] if org else "Business OS"

    manifest_data = {
        "name": app_name,
        "short_name": short_name,
        "description": "Multi-tenant SaaS Business Management Platform with POS and Approvals",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": "#0f172a",
        "background_color": "#0f172a",
        "categories": ["business", "finance", "productivity"],
        "icons": [
            {
                "src": "/static/icons/icon-192.svg",
                "sizes": "192x192",
                "type": "image/svg+xml",
                "purpose": "any",
            },
            {
                "src": "/static/icons/icon-512.svg",
                "sizes": "512x512",
                "type": "image/svg+xml",
                "purpose": "any",
            },
            {
                "src": "/static/icons/icon-512.svg",
                "sizes": "512x512",
                "type": "image/svg+xml",
                "purpose": "maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "POS Terminal",
                "short_name": "POS",
                "description": "Counter retail checkout and cashier register",
                "url": "/pos/",
                "icons": [{"src": "/static/icons/icon-192.svg", "sizes": "192x192"}],
            },
            {
                "name": "Approval Inbox",
                "short_name": "Approvals",
                "description": "Review and approve pending business documents",
                "url": "/approvals/",
                "icons": [{"src": "/static/icons/icon-192.svg", "sizes": "192x192"}],
            },
            {
                "name": "What Needs Attention",
                "short_name": "Attention",
                "description": "Critical daily operations and action items",
                "url": "/ai/attention/items/",
                "icons": [{"src": "/static/icons/icon-192.svg", "sizes": "192x192"}],
            },
            {
                "name": "Dashboard",
                "short_name": "Dashboard",
                "description": "Executive KPI overview and business performance",
                "url": "/dashboard/",
                "icons": [{"src": "/static/icons/icon-192.svg", "sizes": "192x192"}],
            },
        ],
    }

    response = HttpResponse(
        json.dumps(manifest_data, indent=2),
        content_type="application/manifest+json; charset=utf-8",
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_GET
def service_worker_view(request: HttpRequest) -> HttpResponse:
    """Serve root-scoped service worker script with Service-Worker-Allowed header."""
    response = HttpResponse(
        SERVICE_WORKER_CODE,
        content_type="application/javascript; charset=utf-8",
    )
    # Service-Worker-Allowed header permits script served at /service-worker.js to control scope '/'
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@require_GET
def offline_view(request: HttpRequest) -> HttpResponse:
    """Render the offline fallback shell when network connectivity is lost."""
    return render(request, "offline.html", status=200)
