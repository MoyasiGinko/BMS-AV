# Design Guide: BMS-AV Neumorphic Style

This style looks like soft shapes pressed out of one continuous surface. Light originates from the top left, so every raised element features a dark shadow at the bottom right and a white highlight at the top left. Every sunken element reverses this relationship.

---

## 1. Core Principles

1. **One surface.** The page background, sidebar, tiles, cards, and buttons share the exact same surface color (`#E6E9F2`). Only soft shadows separate them.
2. **Raised means "do something" or "this is a card".** Actionable elements (buttons, interactive controls) and content containers (cards, stat tiles) are raised from the plane.
3. **Sunken means "input or readout".** Search inputs, chart wells, data wells, toggle tracks, and slider tracks are sunken into the surface.
4. **Pressed means active.** Clicked buttons, active toggle states, and the current active navigation item switch dynamically to the sunken/pressed shadow.
5. **One accent.** Indigo (`#4F46E5` fill, `#4338CA` text) marks the primary action, data line, progress arcs, and active indicator—nothing else.
6. **Calm and spacious.** No hard 1px borders, high-contrast dividers, or rainbow gradients.

---

## 2. Color Palette

| Role | Hex | RGB / CSS Var | Purpose |
|---|---|---|---|
| **Surface** | `#E6E9F2` | `var(--neu-surface)` | Page background, cards, tiles, buttons, sunken wells |
| **Shadow dark** | `#C5CADB` | `var(--neu-shadow-dark)` | Bottom-right (raised) and top-left (inset) soft shadow |
| **Shadow light** | `#FFFFFF` | `var(--neu-shadow-light)` | Top-left (raised) and bottom-right (inset) crisp highlight |
| **Text** | `#262B45` | `var(--neu-text)` | High-contrast headings, KPI numbers, body copy |
| **Text muted** | `#5A607C` | `var(--neu-text-muted)` | Field labels, secondary stats, inactive nav, icons |
| **Accent text** | `#4338CA` | `var(--neu-accent-text)` | Active nav labels, ghost button text, plus icons, avatar initials |
| **Accent fill** | `#4F46E5` | `var(--neu-accent-fill)` | Primary button background, chart line, progress gauge, toggle thumb |
| **Success** | `#0E6B42` | `var(--neu-success)` | Positive trend delta text (`+18.4%`), online indicators |
| **Line / Divider** | `#D3D8E8` | `var(--neu-line)` | Chart gridlines, dial background track, soft list dividers |

### Color Rules
- Use `#4338CA` for text, badges, and small stroke icons; use `#4F46E5` for solid filled shapes.
- Pure white text (`#FFFFFF`) is permitted **only** on top of the accent fill (`#4F46E5`).
- Never introduce secondary colors (orange, purple, cyan) for decorative purposes. Status is conveyed cleanly through clear text and the single accent.

---

## 3. Shadows (The Foundation)

Light source angle: **135° (top-left to bottom-right)**.

| Level | CSS Shadow Value | Usage |
|---|---|---|
| **Raised, Large** | `9px 9px 18px #C5CADB, -9px -9px 18px #FFFFFF` | Cards, dashboard containers, sidebar, dial outer circle |
| **Raised, Medium** | `6px 6px 12px #C5CADB, -6px -6px 12px #FFFFFF` | Round 56px action buttons, primary action buttons |
| **Raised, Small** | `5px 5px 10px #C5CADB, -5px -5px 10px #FFFFFF` | Pill buttons, ghost buttons, secondary actions |
| **Raised, Extra Small** | `4px 4px 8px #C5CADB, -4px -4px 8px #FFFFFF` | User avatars (42px), selected segmented control tab |
| **Inset, Large** | `inset 6px 6px 12px #C5CADB, inset -6px -6px 12px #FFFFFF` | Search input, chart well, toggle track, slider track |
| **Pressed** | `inset 4px 4px 8px #C5CADB, inset -4px -4px 8px #FFFFFF` | Button `:active` state, pressed feedback |
| **Active Nav** | `inset 5px 5px 10px #C5CADB, inset -5px -5px 10px #FFFFFF` | Currently active page item in the sidebar |

> [!IMPORTANT]
> The light source must remain uniform across every element. A shadow rendered in reverse orientation disrupts the illusion of a continuous physical material.

---

## 4. Typography

Primary typeface: **Hanken Grotesk** (weights 400, 600, 700, 800). Fallback: system UI sans-serif.

| Hierarchy | Size / Weight | Letter Spacing | Context |
|---|---|---|---|
| **Page Title** | 30px / 800 | `-0.02em` | Main screen heading |
| **Hero Number** | `clamp(34px, 5vw, 48px)` / 800 | `-0.03em` | Primary KPI revenue/sales total |
| **Stat Number** | 30px / 800 | `-0.02em` | Metric cards (Receivables, Orders, Stock) |
| **Dial Value** | 30px / 800 | `normal` | Target completion percentage inside radial gauge |
| **Section Title** | 18px / 800 | `-0.01em` | Card header, list group header |
| **Wordmark** | 21px / 800 | `-0.02em` | App brand wordmark in header/sidebar |
| **Label** | 14px / 600 | `normal` | Form labels, metric descriptors (muted color) |
| **Nav Item** | 15px / 600 | `normal` | Sidebar links and menu items |
| **Buttons** | 14px / 700 | `normal` | Pill buttons, ghost buttons (Primary: 15px / 700) |

---

## 5. Shape and Spacing Specifications

- **Radii:**
  - Cards: `28px`
  - Chart well / Data wells: `22px`
  - Primary button & search inputs: `16px`
  - Segmented control outer track: `16px` (inner buttons: `12px`)
  - Pill buttons & ghost buttons: `14px`
  - Round icon buttons, avatars, dials: `50%` (circular)
  - Toggle switch: `58px × 30px` pill with `24px` round thumb
  - Slider track: `14px` height with `24px` round thumb
- **Spacing:**
  - Page padding: `28px`
  - Gap between grid tiles: `30px`
  - Card internal padding: `24px` (stat tiles: `20px`)
  - List row height / spacing: `12px` padding with `1px #D3D8E8` divider
- **Sidebar:**
  - Width: `232px`
  - Container padding: `22px 16px`
  - Nav item padding: `13px 16px` with `16px` border radius

---

## 6. Components Anatomy

### 1. Card (`.neu-card`)
- Background: `#E6E9F2`
- Border-radius: `28px`
- Shadow: Raised Large (`--neu-raise-lg`)
- Border: `none`

### 2. Sunken Well (`.neu-well`)
- Background: `#E6E9F2`
- Border-radius: `22px`
- Shadow: Inset Large (`--neu-inset-lg`)
- Border: `none`
- Used for chart containers, analytics beds, and search bars.

### 3. Primary Button (`.neu-btn-primary`)
- Background: `#4F46E5`
- Text: `#FFFFFF` (white), font-weight 700
- Border-radius: `16px`
- Shadow: Raised Medium (`--neu-raise-md`)
- Active state (`:active`): Inset Small (`--neu-inset-sm`), background remains `#4338CA`.

### 4. Ghost Button (`.neu-btn-ghost`)
- Background: `#E6E9F2`
- Text: `#4338CA` (accent text), font-weight 700
- Border-radius: `14px`
- Shadow: Raised Small (`--neu-raise-sm`)
- Active state (`:active`): Inset Small (`--neu-inset-sm`).

### 5. Round Icon Button (`.neu-btn-round`)
- Dimensions: `56px × 56px`, `border-radius: 50%`
- Background: `#E6E9F2`
- Icon: stroke width `2.2`, color `#5A607C`
- Shadow: Raised Medium (`--neu-raise-md`)
- Active state (`:active`): Inset Small (`--neu-inset-sm`).

### 6. Search Field (`.neu-search`)
- Background: `#E6E9F2`
- Border: `none`
- Border-radius: `16px`
- Shadow: Inset Large (`--neu-inset-lg`)
- Text: `#262B45`, placeholder `#5A607C`
- Focus: `outline: 2px solid #4338CA; outline-offset: 3px;`

### 7. Segmented Control (`.neu-segmented`)
- Outer container: Inset Large (`--neu-inset-lg`), radius `16px`, padding `4px`
- Active option: Raised Extra Small (`--neu-raise-xs`), radius `12px`, background `#E6E9F2`, text `#4338CA` font-weight 700
- Inactive options: flat, text `#5A607C` font-weight 600

### 8. Toggle Switch (`.neu-toggle`)
- Dimensions: `58px × 30px`
- Track: Inset Large (`--neu-inset-lg`), radius `9999px`
- Thumb: `24px × 24px`, circular, background `#4F46E5`, Raised Small
- Text readout companion: Explicit label (e.g. `Auto-reorder: On`)

### 9. Slider (`.neu-slider`)
- Track height: `14px`, Inset Large (`--neu-inset-lg`), radius `9999px`
- Thumb: `24px × 24px`, circular, background `#E6E9F2`, Raised Small (`--neu-raise-sm`)

### 10. Dial Gauge (`.neu-dial`)
- Raised circular disc holding an SVG arc progress bar (`stroke: #4F46E5`, background track `stroke: #D3D8E8`)
- Inset circular center displaying the bold completion stat (`30px / 800`)

---

## 7. Comparative Analysis: Calm Ledger vs. Neumorphic

| Dimension | Calm Ledger (Signature) | BMS-AV Neumorphic | Best Fit |
|---|---|---|---|
| **Visual Language** | Dense, crisp, 1px border dividers, high data density | Soft, sculptural, physical depth via opposing shadows | Calm Ledger for High-volume ERP/POS; Neumorphic for Executive Dashboards/Reports |
| **Surface Strategy** | Multi-surface (slate background `#f8fafc`, pure white cards `#ffffff`) | Single continuous surface (`#E6E9F2` everywhere) | Neumorphic creates a unique tactile luxury feel |
| **Data Tables** | High-density tabular layout with zebra/dividers | Flat data rows on surface (shadows avoided on bulk rows for performance) | Calm Ledger for dense 100-row accounting journals |
| **Action Affordance** | Solid teal fill `#0F766E` with subtle drop shadow | Raised physical buttons with pressed inset feedback | Both provide exceptional tactile affordance |
| **Dark Mode** | Deep navy/slate palette (`#0B1220` / `#111A2E`) | Neumorphic dark uses `#1B1E2B` surface with soft dark/light opposing shadows | Both fully supported via token switching |

---

## 8. Implementation Tokens (`static/css/neumorphic.css`)

```css
:root {
  --neu-surface: #E6E9F2;
  --neu-shadow-dark: #C5CADB;
  --neu-shadow-light: #FFFFFF;
  --neu-text: #262B45;
  --neu-text-muted: #5A607C;
  --neu-line: #D3D8E8;
  --neu-accent-text: #4338CA;
  --neu-accent-fill: #4F46E5;
  --neu-success: #0E6B42;

  --neu-raise-lg: 9px 9px 18px var(--neu-shadow-dark), -9px -9px 18px var(--neu-shadow-light);
  --neu-raise-md: 6px 6px 12px var(--neu-shadow-dark), -6px -6px 12px var(--neu-shadow-light);
  --neu-raise-sm: 5px 5px 10px var(--neu-shadow-dark), -5px -5px 10px var(--neu-shadow-light);
  --neu-raise-xs: 4px 4px 8px var(--neu-shadow-dark), -4px -4px 8px var(--neu-shadow-light);
  --neu-inset-lg: inset 6px 6px 12px var(--neu-shadow-dark), inset -6px -6px 12px var(--neu-shadow-light);
  --neu-inset-sm: inset 4px 4px 8px var(--neu-shadow-dark), inset -4px -4px 8px var(--neu-shadow-light);
  --neu-inset-nav: inset 5px 5px 10px var(--neu-shadow-dark), inset -5px -5px 10px var(--neu-shadow-light);

  --neu-radius-card: 12px;
  --neu-radius-btn: 16px;
  --neu-radius-pill-btn: 14px;
  --neu-radius-well: 22px;
  --neu-radius-seg: 16px;
  --neu-radius-seg-inner: 12px;
  --neu-gap: 30px;
  --neu-pad-card: 24px;
  --neu-tap: 44px;
  --neu-font: 'Hanken Grotesk', system-ui, -apple-system, sans-serif;
}
```
