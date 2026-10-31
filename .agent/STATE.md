- Phase: P7 Hardening & delivery - COMPLETE (All phases P1 through P7 complete)
- Last completed task: Comprehensive UI & Neumorphic Design Ergonomics Fix (Badges, Subnav Tabs, Form Buttons, Sidebar Highlight)
- Next task: NONE - BACKLOG 100% COMPLETE
- Open `[!]` tasks: none
- Last `make verify`: PASSED
- Notes:
  - Addressed 5 visual defect feedback points:
    1. Status Badges ("Posted" pill): Eliminated murky pastel backgrounds and neon text (`dark:bg-emerald-950/70 dark:text-emerald-300`). Standardized on solid, high-contrast, universally accessible status pills (`bg-emerald-600 text-white font-bold`, `bg-rose-600 text-white`, `bg-amber-600 text-white`, `bg-slate-600 text-white`) across bills, returns, invoices, journals, and neumorphic CSS.
    2. Redundant Actions: Removed extraneous "Tax Summary" button from accounting top action bar; preserved proper dedicated tab in navigation.
    3. Sidebar Navigation: Fixed dual-active highlighting under "PEOPLE & PAYROLL" between "Payroll Runs" and "Employee Salaries" by dedicating the `/payroll/salaries/` route and enforcing mutually exclusive active state matching.
    4. Form Actions ("Cancel" & "Create Product"): Unified button ergonomics with matching 44px height, 12px rounded corners, matching padding, and clean visual hierarchy for `.neu-btn-primary` and `.neu-btn-ghost`.
    5. Subnav Tabs vs Medium Cards: Scoped container card padding selectors to avoid inflating interactive controls; constrained all module subnav tabs (`.neu-subnav-btn`, `nav[aria-label*="Tabs"] a`) to sleek, uniform 38px height and 7px 16px padding.
    6. Cache Busting: Bumped static stylesheet version to `?v=4.1.0` in `base.html`.
  - Test Suites Verified:
    - UI theme manager & styleguide smoke suite: 5 passed in 51s.
