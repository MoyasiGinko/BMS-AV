#!/usr/bin/env bash
# Vendors pinned frontend libraries into static/vendor (no CDN at runtime, no Node needed). Versions verified 2026-10-07 (docs/STACK.md).
set -euo pipefail
cd "$(dirname "$0")/.."
D=static/vendor; mkdir -p $D
get() { [ -s "$2" ] || curl -fsSL "$1" -o "$2"; }
get https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js                    $D/htmx.min.js
get https://cdn.jsdelivr.net/npm/alpinejs@3.17.4/dist/cdn.min.js                      $D/alpine.min.js
get https://cdn.jsdelivr.net/npm/@alpinejs/focus@3.17.4/dist/cdn.min.js               $D/alpine-focus.min.js
get https://cdn.jsdelivr.net/npm/@alpinejs/collapse@3.17.4/dist/cdn.min.js            $D/alpine-collapse.min.js
get https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js                 $D/chart.umd.min.js
get https://cdn.jsdelivr.net/npm/sortablejs@1.15.7/Sortable.min.js                    $D/sortable.min.js
get https://cdn.jsdelivr.net/npm/lucide-static@1.52.0/sprite.svg                      static/icons-sprite.svg || true
echo "vendored: $(ls $D | wc -l) files"
