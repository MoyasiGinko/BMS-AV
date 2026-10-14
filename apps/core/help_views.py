"""In-app User Documentation & Help Center views for Business OS."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

HELP_TOPICS: list[dict[str, Any]] = [
    {
        "slug": "getting-started",
        "title": "Getting Started with Business OS",
        "category": "Platform",
        "icon": "rocket",
        "description": (
            "Initial setup, organization configuration, branches, team member invitations, "
            "and Two-Factor Authentication (MFA)."
        ),
        "read_time": "5 min read",
        "sections": [
            {
                "id": "org-setup",
                "title": "Setting Up Your Organization",
                "content": (
                    "When you first register your organization, Business OS provisions an "
                    "isolated tenant space equipped with a default chart of accounts, standard "
                    "user roles (Owner, Admin, Manager, Member), and a default primary branch. "
                    "You can configure your company details, base currency, fiscal year start month, "
                    "and regional time zone in Settings > Organization."
                ),
            },
            {
                "id": "branches",
                "title": "Managing Branches & Locations",
                "content": (
                    "Business OS supports multi-branch operations. Branches allow segmenting "
                    "inventory, sales transactions, and staff members across physical stores, "
                    "regional offices, or distribution centers. Navigate to Settings > Branches "
                    "to add new branches and assign default warehouses."
                ),
            },
            {
                "id": "team-invites",
                "title": "Inviting Team Members & RBAC Roles",
                "content": (
                    "Team collaboration is managed via Memberships and Roles. Go to Settings > Team "
                    "to invite new users by email and assign their role. Roles contain granular "
                    "permission strings (e.g. sales.create, accounting.post). Users can switch "
                    "between multiple organizations they belong to using the topbar switcher."
                ),
            },
            {
                "id": "security-mfa",
                "title": "Two-Factor Authentication (MFA)",
                "content": (
                    "We strongly recommend enabling Two-Factor Authentication for all accounts. "
                    "Go to Settings > Profile > Security to configure TOTP authentication using "
                    "Google Authenticator, 1Password, or any standard authenticator app. "
                    "Recovery codes are generated for emergency access."
                ),
            },
        ],
    },
    {
        "slug": "sales-invoicing",
        "title": "Sales, Invoicing & Receivables",
        "category": "Commerce",
        "icon": "cash",
        "description": (
            "Quotation workflows, sales orders, tax calculations, automated invoice posting, "
            "and customer payment collections."
        ),
        "read_time": "6 min read",
        "sections": [
            {
                "id": "quotes-orders",
                "title": "Quotes & Sales Orders",
                "content": (
                    "Create draft quotes under Sales > Quotes. Once accepted by the customer, "
                    "convert the quote into a Sales Order with a single click. Confirming a Sales "
                    "Order automatically validates stock availability across your selected "
                    "warehouse and allocates stock reservations."
                ),
            },
            {
                "id": "invoice-posting",
                "title": "Posting Invoices & General Ledger Integration",
                "content": (
                    "Draft invoices can be modified freely. Upon posting an invoice, Business OS "
                    "executes an atomic transaction that: 1) Increments the customer's Accounts "
                    "Receivable balance; 2) Dispatches physical goods from inventory; 3) Creates "
                    "balanced double-entry journal postings (Debit AR, Credit Sales Revenue, "
                    "Credit Tax Payable, Debit Cost of Goods Sold, Credit Inventory Asset); "
                    "4) Emits a sales.invoice_posted domain event."
                ),
            },
            {
                "id": "payments-allocations",
                "title": "Receiving Payments & Partial Allocations",
                "content": (
                    "Record customer payments under Sales > Payments. Payments can be allocated to "
                    "single or multiple unpaid invoices. When an invoice is fully matched, its status "
                    "transitions automatically to Paid. Unallocated balances remain as customer "
                    "credits for future invoices."
                ),
            },
            {
                "id": "recurring-invoices",
                "title": "Recurring Invoices & Automatic Reminders",
                "content": (
                    "Set up subscription or retainer billing under Sales > Recurring Invoices. "
                    "Configure schedules (weekly, monthly, annual) and automated payment reminders "
                    "that dispatch notice emails before or after due dates."
                ),
            },
        ],
    },
    {
        "slug": "purchasing-bills",
        "title": "Purchasing, Bills & Accounts Payable",
        "category": "Procurement",
        "icon": "shopping-cart",
        "description": (
            "Supplier management, purchase orders, three-way matching, goods receipt notes, "
            "and vendor bill payments."
        ),
        "read_time": "5 min read",
        "sections": [
            {
                "id": "purchase-orders",
                "title": "Purchase Orders & Vendor Agreements",
                "content": (
                    "Issue Purchase Orders under Purchasing > Orders to formalize procurement with "
                    "suppliers. Track item quantities, negotiated unit costs, tax rates, "
                    "and delivery deadlines."
                ),
            },
            {
                "id": "goods-receipt",
                "title": "Goods Receipt & Warehouse Inward",
                "content": (
                    "When supplier shipments arrive, record a Goods Receipt against the PO. Receiving "
                    "goods updates physical stock in the destination warehouse and logs incoming stock "
                    "movements with batch/lot numbers if enabled."
                ),
            },
            {
                "id": "three-way-match",
                "title": "3-Way Matching & Bill Posting",
                "content": (
                    "When the vendor invoice arrives, create a Bill. Business OS performs automated "
                    "3-way matching between the Purchase Order, Goods Receipt, and Bill line items, "
                    "highlighting any quantity or unit price variances. Posting a bill debits "
                    "Inventory/Expense accounts and credits Accounts Payable."
                ),
            },
        ],
    },
    {
        "slug": "inventory-warehouses",
        "title": "Inventory Control & Warehouses",
        "category": "Operations",
        "icon": "archive",
        "description": (
            "Product catalogs, variant tracking, warehouse stock movements, reorder thresholds, "
            "and physical audits."
        ),
        "read_time": "7 min read",
        "sections": [
            {
                "id": "items-variants",
                "title": "Item Catalog, SKUs & Variants",
                "content": (
                    "Manage products, raw materials, and service items under Inventory > Items. "
                    "Supports multiple units of measure, barcode assignment, category hierarchies, "
                    "and product variant matrices (e.g. size, color)."
                ),
            },
            {
                "id": "stock-transfers",
                "title": "Inter-Warehouse Transfers & Adjustments",
                "content": (
                    "Transfer stock between warehouses using Inventory > Transfers. Stock is tracked "
                    "in-transit until acknowledged by the receiving warehouse. Discrepancies during "
                    "stocktakes can be recorded via Stock Adjustments with required justification codes."
                ),
            },
            {
                "id": "reorder-points",
                "title": "Automated Reorder Alerts & ABC Analysis",
                "content": (
                    "Configure minimum stock levels and reorder quantities per warehouse. The system "
                    "continuously evaluates inventory velocity and alerts procurement when levels breach "
                    "safety thresholds. ABC analysis categorizes items by revenue contribution to "
                    "optimize working capital."
                ),
            },
        ],
    },
    {
        "slug": "point-of-sale",
        "title": "Point of Sale (POS)",
        "category": "Retail",
        "icon": "calculator",
        "description": (
            "Cashier registers, session management, cash drawer reconciliation, barcode scanning, "
            "and offline PWA capability."
        ),
        "read_time": "4 min read",
        "sections": [
            {
                "id": "register-sessions",
                "title": "Opening & Closing Register Sessions",
                "content": (
                    "Cashiers open a POS session at the start of their shift by entering the opening "
                    "cash drawer count. All sales, cash drops, and refunds during the shift are tracked. "
                    "At shift end, the closing count reconciles expected vs actual cash with "
                    "discrepancy reporting."
                ),
            },
            {
                "id": "checkout-flow",
                "title": "Rapid Checkout & Barcode Scanning",
                "content": (
                    "The POS interface is optimized for touchscreens and hardware barcode scanners. "
                    "Scan or search items, apply customer discounts, split tenders between cash/card, "
                    "and print thermal receipts in under 15 seconds."
                ),
            },
            {
                "id": "offline-resilience",
                "title": "Offline Mode via Service Worker",
                "content": (
                    "Business OS POS functions even if internet connectivity drops. The Progressive "
                    "Web App (PWA) caches catalog items locally and queues completed sales in browser "
                    "IndexedDB, automatically syncing transactions when the connection restores."
                ),
            },
        ],
    },
    {
        "slug": "accounting-ledger",
        "title": "General Ledger & Accounting",
        "category": "Finance",
        "icon": "book-open",
        "description": (
            "Double-entry general ledger, chart of accounts, automated posting rules, fiscal periods, "
            "and financial reports."
        ),
        "read_time": "8 min read",
        "sections": [
            {
                "id": "chart-of-accounts",
                "title": "Chart of Accounts & Semantic Mappings",
                "content": (
                    "Your chart of accounts organizes assets, liabilities, equity, revenue, and expenses. "
                    "Semantic account mappings (e.g., sales.revenue, ar, ap, inventory.asset, cogs) decouple "
                    "operational modules from hardcoded account IDs."
                ),
            },
            {
                "id": "double-entry",
                "title": "Double-Entry Balance & Immutability",
                "content": (
                    "Every posted journal entry enforces sum(debit) == sum(credit) > 0. Posted entries "
                    "are strictly immutable. Corrections require generating a symmetrical reversing "
                    "entry to maintain a transparent, audit-compliant financial trail."
                ),
            },
            {
                "id": "fiscal-closing",
                "title": "Fiscal Periods & Year-End Closing",
                "content": (
                    "Lock past accounting periods under Accounting > Fiscal Periods to prevent unauthorized "
                    "modifications to audited records. Year-end closing procedures roll net income into "
                    "Retained Earnings and initialize open balance sheets."
                ),
            },
            {
                "id": "financial-statements",
                "title": "Balance Sheet, Trial Balance & Profit & Loss",
                "content": (
                    "Generate real-time financial statements with customizable date filters, comparative "
                    "period analysis, and export options to PDF and Excel."
                ),
            },
        ],
    },
    {
        "slug": "crm-pipelines",
        "title": "CRM & Sales Pipelines",
        "category": "Growth",
        "icon": "users",
        "description": (
            "Lead tracking, visual deal pipelines, interaction logs, conversion funnels, "
            "and customer relationship history."
        ),
        "read_time": "4 min read",
        "sections": [
            {
                "id": "leads-deals",
                "title": "Lead Management & Opportunity Scoring",
                "content": (
                    "Capture leads from website inquiries, inbound webhooks, or manual entry. Score leads "
                    "based on engagement and qualify them into pipeline opportunities."
                ),
            },
            {
                "id": "deal-stages",
                "title": "Kanban Pipeline & Stage Progression",
                "content": (
                    "Visualize deals on a drag-and-drop Kanban board. Track deal probability, expected close "
                    "dates, and weighted pipeline values. Won deals can instantly generate a draft Quote or "
                    "Sales Order."
                ),
            },
        ],
    },
    {
        "slug": "hr-payroll",
        "title": "HR Directory & Payroll Runs",
        "category": "Workforce",
        "icon": "identification",
        "description": (
            "Employee directory, department structures, salary component rules, payroll calculation runs, "
            "and payslips."
        ),
        "read_time": "6 min read",
        "sections": [
            {
                "id": "employee-records",
                "title": "Employee Profiles & Compensation Packages",
                "content": (
                    "Maintain employee records, job titles, department allocations, "
                    "tax IDs, and bank details. Assign customized compensation packages "
                    "consisting of base salaries, fixed allowances, and statutory deductions."
                ),
            },
            {
                "id": "payroll-cycles",
                "title": "Executing Payroll Cycles & Payslip Generation",
                "content": (
                    "Process monthly or bi-weekly payroll runs under Payroll > Runs. The engine computes "
                    "gross pay, deductions, employer contributions, and net payable. Approving a run "
                    "generates PDF payslips and creates automated ledger entries debiting Salary Expense "
                    "and crediting Payroll Payable."
                ),
            },
        ],
    },
    {
        "slug": "workflows-approvals",
        "title": "Workflows, Automations & Approvals",
        "category": "Governance",
        "icon": "adjustments",
        "description": (
            "Configurable multi-tier approval chains, threshold rules, and automated event-driven triggers."
        ),
        "read_time": "5 min read",
        "sections": [
            {
                "id": "approval-rules",
                "title": "Configuring Approval Chains",
                "content": (
                    "Set up governance policies requiring supervisor or financial controller sign-off "
                    "on transactions exceeding configured dollar thresholds (e.g. purchase orders over "
                    "$5,000 or discount overrides > 15%)."
                ),
            },
            {
                "id": "event-automations",
                "title": "Event-Driven Automation Workflows",
                "content": (
                    "Build automated recipes responding to system events (e.g., when an invoice becomes "
                    "7 days overdue, send an SMS notification and alert the account manager in Slack)."
                ),
            },
        ],
    },
    {
        "slug": "integrations-api",
        "title": "REST API, Webhooks & Integrations",
        "category": "Developers",
        "icon": "code",
        "description": (
            "API key provisioning, OAuth2 client credentials, inbound/outbound webhooks, "
            "and third-party connector adapters."
        ),
        "read_time": "7 min read",
        "sections": [
            {
                "id": "api-keys",
                "title": "API Keys & Authentication",
                "content": (
                    "Generate tenant-scoped API keys under Settings > Integrations > API Keys. API keys "
                    "authenticate using the X-API-Key header or Authorization: Api-Key <token>. Rate limits "
                    "scale dynamically according to your subscription tier."
                ),
            },
            {
                "id": "oauth2-pkce",
                "title": "OAuth 2.0 PKCE & Client Credentials",
                "content": (
                    "Register third-party applications supporting Authorization Code Flow with PKCE for "
                    "single-page apps or mobile clients, and Client Credentials flow for server-to-server "
                    "microservice integrations."
                ),
            },
            {
                "id": "webhooks-hmac",
                "title": "Inbound & Outbound Webhooks with HMAC Verification",
                "content": (
                    "Subscribe external endpoints to system domain events (e.g., sales.invoice_posted, "
                    "inventory.level_changed). All outbound webhook payloads include an X-BOS-Signature "
                    "header computed using HMAC SHA256 over the raw JSON payload. Inbound webhook endpoints "
                    "allow receiving notifications from payment gateways or external CRMs."
                ),
            },
        ],
    },
    {
        "slug": "reports-analytics",
        "title": "Reports, Analytics & Scheduled Exports",
        "category": "Intelligence",
        "icon": "chart-bar",
        "description": (
            "Financial statements, product ABC profitability, customer cohorts, "
            "and automated periodic email reports."
        ),
        "read_time": "5 min read",
        "sections": [
            {
                "id": "standard-reports",
                "title": "Standard Financial & Operational Reports",
                "content": (
                    "Access curated reports under Reports: Sales Analysis, Customer Aging Summary (AR), "
                    "Vendor Aging (AP), Inventory Valuation, Stock Movement History, and Tax Summary."
                ),
            },
            {
                "id": "scheduled-exports",
                "title": "Scheduled Email Reports & Formats",
                "content": (
                    "Schedule reports to run daily, weekly, or monthly. The background Celery worker "
                    "compiles the report dataset into CSV or Excel and emails it directly to stakeholder "
                    "distribution lists."
                ),
            },
        ],
    },
    {
        "slug": "ai-assistant",
        "title": "AI Assistant & Copilot",
        "category": "Intelligence",
        "icon": "sparkles",
        "description": (
            "Natural language analytics, contextual document drafting, executive summaries, "
            "and safe read-only SQL queries."
        ),
        "read_time": "4 min read",
        "sections": [
            {
                "id": "natural-language",
                "title": "Conversational Data Exploration",
                "content": (
                    "Ask the AI Assistant questions in plain English: 'Which customers generated the "
                    "highest margin last quarter?' or 'Show stock levels below reorder point in "
                    "East Warehouse'. The assistant executes read-only queries with strict tenant "
                    "isolation constraints."
                ),
            },
            {
                "id": "document-drafting",
                "title": "AI Document Drafting & Summaries",
                "content": (
                    "Use the AI assistant inside invoices, quotes, and emails to generate professional "
                    "customer notes, translate text, or summarize lengthy communication threads."
                ),
            },
        ],
    },
]

FAQ_ITEMS: list[dict[str, str]] = [
    {
        "q": "How does tenant data isolation work in Business OS?",
        "a": (
            "Business OS employs a multi-layered defense-in-depth model: 1) Every business model inherits "
            "TenantModel and filters by organization_id automatically; 2) PostgreSQL Row-Level Security "
            "(RLS) is enabled and enforced at the database kernel level; 3) Application middleware validates "
            "and binds the tenant context to each request thread; 4) Cross-tenant access is tested "
            "continuously across the entire test suite."
        ),
    },
    {
        "q": "Can I reverse or edit a posted invoice or journal entry?",
        "a": (
            "Posted financial documents are strictly immutable to comply with standard accounting and "
            "audit regulations. To correct an erroneous invoice or journal entry, create a Reversal "
            "or Credit Note. This posts an offsetting transaction that preserves a transparent "
            "historical record."
        ),
    },
    {
        "q": "What happens if our internet connection drops while using the POS?",
        "a": (
            "The Point of Sale application is a Progressive Web App (PWA). It stores your item catalog "
            "and offline sales in the browser's IndexedDB. Cashiers can continue processing sales; "
            "once connectivity is restored, all offline transactions automatically sync."
        ),
    },
    {
        "q": "How do I verify webhook signatures received from Business OS?",
        "a": (
            "Outbound webhooks include an X-BOS-Signature header. In your endpoint handler, compute HMAC "
            "SHA256 of the raw request body using your endpoint's shared secret and compare using a "
            "constant-time comparison function (e.g. hmac.compare_digest)."
        ),
    },
    {
        "q": "Where can I view the interactive REST API documentation?",
        "a": (
            "Interactive Swagger OpenAPI documentation is available in the topbar or directly at "
            "/api/docs/. The raw OpenAPI schema is available at /api/schema/."
        ),
    },
]


@login_required
@require_GET
def help_index_view(request: HttpRequest) -> HttpResponse:
    """Help center landing page with topic cards, FAQs, and instant search."""
    query = request.GET.get("q", "").strip()
    filtered_topics = HELP_TOPICS
    if query:
        q_lower = query.lower()
        filtered_topics = [
            topic
            for topic in HELP_TOPICS
            if q_lower in topic["title"].lower()
            or q_lower in topic["description"].lower()
            or q_lower in topic["category"].lower()
            or any(
                q_lower in s["title"].lower() or q_lower in s["content"].lower() for s in topic["sections"]
            )
        ]

    # If requested via HTMX search partial, return just the results fragment
    if request.headers.get("HX-Request") and "q" in request.GET:
        return render(
            request,
            "help/partials/_topic_cards.html",
            {"topics": filtered_topics, "query": query},
        )

    context = {
        "topics": filtered_topics,
        "faqs": FAQ_ITEMS,
        "query": query,
    }
    return render(request, "help/index.html", context)


@login_required
@require_GET
def help_article_view(request: HttpRequest, slug: str) -> HttpResponse:
    """Detailed topic guide with section anchor navigation and table of contents."""
    topic = next((t for t in HELP_TOPICS if t["slug"] == slug), None)
    if not topic:
        raise Http404(f"Help topic '{slug}' not found.")

    related_topics = [t for t in HELP_TOPICS if t["slug"] != slug and t["category"] == topic["category"]][:3]
    if not related_topics:
        related_topics = [t for t in HELP_TOPICS if t["slug"] != slug][:3]

    context = {
        "topic": topic,
        "all_topics": HELP_TOPICS,
        "related_topics": related_topics,
    }
    return render(request, "help/article.html", context)


@login_required
@require_POST
def help_feedback_view(request: HttpRequest, slug: str) -> HttpResponse:
    """Record helpfulness feedback for an article (HTMX action)."""
    helpful = request.POST.get("helpful") == "yes"
    return render(
        request,
        "help/partials/_feedback_response.html",
        {"helpful": helpful, "slug": slug},
    )
