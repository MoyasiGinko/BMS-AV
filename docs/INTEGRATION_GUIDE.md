# Business OS Integration Guide

Complete architectural guide for integrating external services, microservices, third-party apps, and payment providers with Business OS.

---

## 1. Overview of Integration Mechanisms

Business OS provides four robust integration channels tailored for different architectural scenarios:

```
+-----------------------------------------------------------------------------------+
|                                 Business OS                                       |
+-----------------------------------------------------------------------------------+
       ^                          ^                        ^                   |
       | API Key                  | OAuth 2.0              | Inbound Webhooks  | Outbound Events
       | (Headers)                | (Tokens)               | (Signatures)      | (Transactional Outbox)
       v                          v                        v                   v
+--------------+          +----------------+       +--------------+     +-------------------+
| Backend App  |          | Partner App /  |       | Payment /    |     | External Listener |
| Microservice |          | Mobile Client  |       | External CRM |     | Webhook Receiver  |
+--------------+          +----------------+       +--------------+     +-------------------+
```

1. **API Keys**: High-throughput machine-to-machine integrations scoped strictly to a single tenant.
2. **OAuth 2.0 (PKCE & Client Credentials)**: Standards-compliant delegated authorization for partner integrations, multi-tenant connectors, and mobile clients.
3. **Inbound Webhooks**: Receives asynchronous event notifications from payment gateways (Stripe, PayPal) or e-commerce platforms (Shopify).
4. **Outbound Webhooks**: Event-driven pushes powered by a transactional outbox with guaranteed delivery and cryptographic HMAC verification.

---

## 2. API Key Authentication & Governance

### 2.1. Generating API Keys
Tenant administrators generate API keys via **Settings > Integrations > API Keys** or programmatically via the back-office API.
- Keys are prefixed with `bos_live_` (production) or `bos_test_` (sandbox).
- Keys are hashed with SHA-256 before storage; the raw secret is only displayed once upon generation.
- Administrators can assign granular permission scopes (`sales:read`, `sales:write`, `inventory:manage`, `accounting:read`, `admin`).
- Optional IP allowlisting restricts key usage to authorized egress CIDRs.

### 2.2. Authentication Header Syntax
Attach the key to outgoing HTTP requests via either:
```http
X-API-Key: bos_live_sec_89d3a7b1c4e20f512...
```
or
```http
Authorization: Api-Key bos_live_sec_89d3a7b1c4e20f512...
```

---

## 3. Outbound Webhooks & HMAC Verification

Business OS uses a transactional outbox pattern to guarantee that business events are never lost, even during system crashes or temporary downstream outages.

### 3.1. Supported Webhook Event Types
- `sales.quote_created`, `sales.order_confirmed`, `sales.invoice_posted`, `sales.payment_received`, `sales.credit_note_posted`
- `purchasing.order_created`, `purchasing.order_confirmed`, `purchasing.bill_posted`, `purchasing.payment_sent`
- `inventory.item_created`, `inventory.stock_level_changed`, `inventory.stock_below_reorder`, `inventory.transfer_shipped`
- `crm.lead_created`, `crm.lead_converted`, `crm.deal_stage_changed`
- `hr.employee_hired`, `hr.employee_terminated`
- `payroll.run_computed`, `payroll.run_approved`
- `billing.subscription_created`, `billing.subscription_renewed`, `billing.subscription_cancelled`

### 3.2. Webhook Delivery Payload Format
```json
{
  "id": "evt_019283a4-b5c6-7d8e-9f0a-1b2c3d4e5f6a",
  "event": "sales.invoice_posted",
  "timestamp": "2026-10-14T10:15:30.123456Z",
  "organization_id": "org_3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "data": {
    "public_id": "inv_88291a0c-4e5b-48d3-9217-1049c81b2384",
    "invoice_number": "INV-2026-0042",
    "customer_id": "cust_99182374-1234-5678-90ab-cdef12345678",
    "total_amount": "1450.00",
    "currency": "USD",
    "status": "POSTED"
  }
}
```

### 3.3. Delivery Headers & Security
Every webhook delivery includes cryptographic headers to prevent tampering and replay attacks:
- `X-BOS-Signature`: `sha256=<hex_encoded_hmac>`
- `X-BOS-Timestamp`: Unix timestamp (seconds) when the payload was dispatched.
- `X-BOS-Event`: The event type name.
- `X-BOS-Delivery-ID`: Unique UUID for deduplication.

### 3.4. Cryptographic HMAC Signature Verification

To verify that the webhook originated from Business OS and has not been tampered with:
1. Extract `X-BOS-Signature` and `X-BOS-Timestamp`.
2. Verify that `|current_time - timestamp| <= 300` seconds (5-minute replay prevention window).
3. Compute `expected_signature = hmac_sha256(secret, timestamp + "." + raw_request_body)`.
4. Perform constant-time string comparison between the received and expected signatures.

#### Verification in Python
```python
import hmac
import hashlib
import time
from flask import Flask, request, abort

app = Flask(__name__)
WEBHOOK_SECRET = "whsec_your_shared_signing_secret"

@app.route("/webhooks/business-os", methods=["POST"])
def handle_webhook():
    signature_header = request.headers.get("X-BOS-Signature", "")
    timestamp = request.headers.get("X-BOS-Timestamp", "")
    raw_body = request.get_data()

    if not signature_header or not timestamp:
        abort(400, "Missing signature headers")

    # 1. Prevent replay attacks (5 minute threshold)
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:
            abort(400, "Webhook timestamp outside replay window")
    except ValueError:
        abort(400, "Invalid timestamp format")

    # 2. Compute HMAC SHA-256
    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    expected_sig = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256
    ).hexdigest()

    # 3. Constant-time comparison
    if not hmac.compare_digest(signature_header, expected_sig):
        abort(401, "Invalid webhook signature")

    # 4. Process event idempotently
    event_payload = request.get_json()
    print("Received verified event:", event_payload["event"])
    return {"status": "ok"}, 200
```

#### Verification in Node.js
```javascript
const crypto = require("crypto");
const express = require("express");

const app = express();
const WEBHOOK_SECRET = "whsec_your_shared_signing_secret";

// Ensure express captures raw body buffer
app.use(express.json({
  verify: (req, res, buf) => { req.rawBody = buf; }
}));

app.post("/webhooks/business-os", (req, res) => {
  const signature = req.headers["x-bos-signature"];
  const timestamp = req.headers["x-bos-timestamp"];

  if (!signature || !timestamp) {
    return res.status(400).send("Missing signature headers");
  }

  // 1. Replay check
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) {
    return res.status(400).send("Timestamp outside 5m tolerance window");
  }

  // 2. Compute HMAC
  const signedPayload = `${timestamp}.${req.rawBody.toString("utf8")}`;
  const expectedSig = "sha256=" + crypto
    .createHmac("sha256", WEBHOOK_SECRET)
    .update(signedPayload)
    .digest("hex");

  // 3. Constant-time compare
  const signatureValid = crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(expectedSig)
  );

  if (!signatureValid) {
    return res.status(401).send("Invalid signature");
  }

  console.log("Processed event:", req.body.event);
  res.status(200).json({ received: true });
});
```

### 3.5. Retry Policy & Dead-Letter Queue (DLQ)
- If your endpoint returns a non-2xx response or times out (10s limit), the outbox worker schedules automatic retries using exponential backoff:
  - Attempt 1: Immediate
  - Attempt 2: 1 minute
  - Attempt 3: 5 minutes
  - Attempt 4: 30 minutes
  - Attempt 5: 2 hours
- After 5 consecutive failures, the delivery is marked as `FAILED` and sent to the Dead-Letter Queue.
- Administrators can inspect error payloads, view HTTP response codes, and manually replay failed webhook deliveries via the Settings > Integrations dashboard.

---

## 4. Inbound Webhooks

Business OS can ingest webhook notifications from external systems (e.g. Stripe checkout completion, Shopify inventory sync, or Zapier webhooks).

### 4.1. Creating an Inbound Endpoint
Navigate to **Settings > Integrations > Inbound Webhooks**:
1. Name your endpoint (e.g. `Stripe Production Webhook`).
2. Select the provider type (`Stripe`, `Shopify`, `GitHub`, or `Generic JSON`).
3. Enter or generate the shared webhook signing secret. This secret is symmetrically encrypted at rest using AES-128 Fernet encryption (`apps.core.crypto`).
4. Configure event mappings: translate external event names (`payment_intent.succeeded`) to Business OS internal domain events (`sales.payment_received`).
5. Copy the generated endpoint URL: `https://api.yourdomain.com/integrations/inbound/<endpoint_uuid>/`.

---

## 5. OAuth 2.0 Integration Framework

Business OS includes an enterprise-grade OAuth 2.0 authorization server conforming to RFC 6749 and RFC 7636.

### 5.1. Supported Flows
1. **Authorization Code Grant with PKCE (Proof Key for Code Exchange)**: Mandatory for single-page web applications (React, Vue) and native mobile apps.
2. **Client Credentials Grant**: Suitable for secure server-to-server daemon processes and background synchronization workers.

### 5.2. OAuth 2.0 Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/oauth/authorize/` | `GET` | User authorization screen & consent prompt |
| `/oauth/token/` | `POST` | Exchange authorization code or credentials for access token |
| `/oauth/revoke_token/` | `POST` | Revoke active access or refresh tokens |
| `/oauth/introspect/` | `POST` | Token introspection (RFC 7662) |

### 5.3. Dynamic Client Registration (RFC 7591)
Automated partner onboarding is supported via Dynamic Client Registration (DCR) at `/oauth/register/` using initial registration access tokens.

---

## 6. Connector Framework & Data Sync

The pluggable connector framework (`apps/integrations/connectors/`) standardizes continuous two-way synchronization:
- **`GenericRESTConnector`**: Configurable polling connector with pagination, JSONPath field mapping, and delta sync based on `updated_at`.
- **`StripeBillingAdapter`**: Payment processing, card tokenize workflows, and subscription state synchronization.
- **`CSVDataPipeline`**: Bulk import and export engine with background validation, dry-run previews, and row-level error reporting.

All connectors log synchronization history to `apps.integrations.models.SyncLog` with duration, record counts, and error summaries.
