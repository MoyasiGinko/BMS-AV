# Business OS REST API Guide

Comprehensive developer guide for integrating with the Business OS v1 REST API.

All endpoints adhere to REST conventions, enforce tenant isolation, and use standard JSON request and response payloads.

---

## 1. Base URL & Interactive Documentation

- **Base URL**: `https://api.yourdomain.com/api/v1/` (or `http://localhost:8000/api/v1/` in development)
- **Interactive Swagger UI**: `/api/docs/`
- **OpenAPI 3.0 Schema**: `/api/schema/`

---

## 2. Authentication & Headers

Business OS supports three primary authentication schemes:

| Scheme | Header Syntax | Use Case |
|---|---|---|
| **API Key (Recommended)** | `X-API-Key: <api_key>` or `Authorization: Api-Key <api_key>` | Server-to-server microservices & backend scripts |
| **OAuth2 Bearer Token** | `Authorization: Bearer <access_token>` | Third-party partner apps & single-page applications |
| **Session Cookie** | `Cookie: sessionid=...` with `X-CSRFToken: ...` | In-app frontend HTMX / Alpine.js calls |

### Standard Request Headers
```http
Content-Type: application/json
Accept: application/json
X-API-Key: bos_live_9a8b7c6d5e4f3a2b1c0d
Idempotency-Key: 7b830e9d-4c31-4122-83b5-7798efd41b55
X-Request-ID: req_c9842f1b0a
```

- `Idempotency-Key`: Strongly recommended on all mutating requests (`POST`, `PUT`, `PATCH`) to prevent double-billing or duplicate stock movements during network retries. Keys are cached in Redis for 24 hours.
- `X-Request-ID`: Correlation identifier propagated to logs and error responses for tracing.

---

## 3. Rate Limits & Error Handling

Rate limits scale dynamically according to your organization's subscription plan tier:
- **Starter**: 60 requests/minute
- **Growth**: 300 requests/minute
- **Business**: 1,000 requests/minute
- **Enterprise**: 3,000 requests/minute

When a rate limit is exceeded, the server returns HTTP `429 Too Many Requests` with a `Retry-After: <seconds>` header.

### Standard Error Response Format
```json
{
  "code": "validation_error",
  "message": "Invalid line item quantity or unit price.",
  "details": {
    "lines": [
      {"quantity": ["Quantity must be greater than zero."]}
    ]
  },
  "request_id": "req_c9842f1b0a"
}
```

---

## 4. Pagination, Filtering & Sorting

List endpoints use cursor-based or limit-offset pagination:
- `?page_size=25` (Default: 25, Maximum: 100)
- `?cursor=cD0yMDI2LTEwLTAxKzAwJTNBMDA...`
- `?search=<term>`: Full-text search across relevant fields (name, SKU, email).
- `?ordering=-created_at`: Prepend `-` for descending order.
- `?updated_after=2026-10-01T00:00:00Z`: Delta synchronization filter.

---

## 5. Code Examples by Resource Group

### 5.1. Authentication & Organization Info

#### cURL
```bash
curl -X GET "http://localhost:8000/api/v1/tenancy/organizations/" \
  -H "X-API-Key: bos_live_your_key_here" \
  -H "Accept: application/json"
```

#### Python
```python
import requests

API_URL = "http://localhost:8000/api/v1"
HEADERS = {
    "X-API-Key": "bos_live_your_key_here",
    "Accept": "application/json",
}

response = requests.get(f"{API_URL}/tenancy/organizations/", headers=HEADERS)
response.raise_for_status()
orgs = response.json()
print("Connected Organization:", orgs["results"][0]["name"])
```

---

### 5.2. Catalog & Products

#### List Items (cURL)
```bash
curl -X GET "http://localhost:8000/api/v1/catalog/items/?category=electronics&search=widget" \
  -H "X-API-Key: bos_live_your_key_here"
```

#### Create New Product (Python)
```python
import uuid
import requests

item_payload = {
    "name": "Industrial Sensor Node v2",
    "sku": "SN-IND-002",
    "type": "goods",
    "cost_price": "45.00",
    "selling_price": "120.00",
    "tax_rate": "10.00",
    "track_inventory": True,
}

response = requests.post(
    "http://localhost:8000/api/v1/catalog/items/",
    headers={
        "X-API-Key": "bos_live_your_key_here",
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json=item_payload,
)
print("Created Item:", response.json())
```

---

### 5.3. Customers & Contacts

#### Create Customer (Python)
```python
customer_data = {
    "name": "Nexus Global Logistics LLC",
    "email": "procurement@nexusglobal.test",
    "phone": "+1-555-0199",
    "credit_limit": "25000.00",
    "currency": "USD",
    "billing_address": {
        "line1": "450 Industrial Parkway",
        "city": "Chicago",
        "state": "IL",
        "postal_code": "60601",
        "country": "US",
    },
}

res = requests.post(
    "http://localhost:8000/api/v1/customers/",
    headers={"X-API-Key": "bos_live_your_key_here"},
    json=customer_data,
)
customer_id = res.json()["public_id"]
```

---

### 5.4. Sales Invoices (with Idempotency)

#### Create & Post Invoice (cURL)
```bash
curl -X POST "http://localhost:8000/api/v1/sales/invoices/" \
  -H "X-API-Key: bos_live_your_key_here" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: e82d3b41-f67c-47ea-a228-569d628eb4f9" \
  -d '{
    "customer": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "currency": "USD",
    "payment_terms_days": 30,
    "lines": [
      {
        "item": "9bb2e1f4-3860-4ea2-938b-d72b2c9ad110",
        "description": "Industrial Sensor Node v2",
        "quantity": "10.00",
        "unit_price": "120.00",
        "tax_rate": "10.00"
      }
    ],
    "auto_post": true
  }'
```

#### Create & Post Invoice (Python)
```python
import uuid
import requests

invoice_payload = {
    "customer": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "currency": "USD",
    "payment_terms_days": 30,
    "lines": [
        {
            "item": "9bb2e1f4-3860-4ea2-938b-d72b2c9ad110",
            "description": "Industrial Sensor Node v2",
            "quantity": "10.00",
            "unit_price": "120.00",
            "tax_rate": "10.00",
        }
    ],
    "auto_post": True,  # Dispatches stock & updates General Ledger atomically
}

response = requests.post(
    "http://localhost:8000/api/v1/sales/invoices/",
    headers={
        "X-API-Key": "bos_live_your_key_here",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json=invoice_payload,
)
invoice = response.json()
print(f"Invoice {invoice['invoice_number']} created. Total: ${invoice['total_amount']}")
```

---

### 5.5. Customer Payments & Allocation

#### Record Payment (Python)
```python
payment_payload = {
    "customer": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "amount": "1320.00",
    "payment_method": "bank_transfer",
    "reference": "WIRE-2026-90412",
    "allocations": [
        {
            "invoice": invoice["public_id"],
            "amount": "1320.00",
        }
    ],
}

res = requests.post(
    "http://localhost:8000/api/v1/sales/payments/",
    headers={
        "X-API-Key": "bos_live_your_key_here",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json=payment_payload,
)
print("Payment recorded and invoice marked PAID:", res.json()["status"])
```

---

### 5.6. Inventory Levels & Adjustments

#### Query Stock Levels (cURL)
```bash
curl -X GET "http://localhost:8000/api/v1/inventory/stock-levels/?warehouse=main-dc" \
  -H "X-API-Key: bos_live_your_key_here"
```

#### Post Inventory Adjustment (Python)
```python
adjustment_payload = {
    "warehouse": "4f9d2a1c-8b3e-4d5f-9a1b-2c3d4e5f6a7b",
    "reason_code": "cycle_count",
    "lines": [
        {
            "item": "9bb2e1f4-3860-4ea2-938b-d72b2c9ad110",
            "quantity_delta": "5.00",  # Positive increases stock, negative decreases
            "unit_cost": "45.00",
        }
    ],
    "notes": "Q4 cycle count variance reconciliation",
}

res = requests.post(
    "http://localhost:8000/api/v1/inventory/adjustments/",
    headers={
        "X-API-Key": "bos_live_your_key_here",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json=adjustment_payload,
)
print("Inventory adjustment posted:", res.json())
```

---

### 5.7. Webhook Subscription Management

#### Register Endpoint (Python)
```python
webhook_registration = {
    "target_url": "https://ops.example.com/webhooks/business-os",
    "events": [
        "sales.invoice_posted",
        "sales.payment_received",
        "inventory.stock_below_reorder",
    ],
    "description": "Enterprise ERP sync listener",
}

res = requests.post(
    "http://localhost:8000/api/v1/integrations/webhooks/",
    headers={"X-API-Key": "bos_live_your_key_here"},
    json=webhook_registration,
)
data = res.json()
print("Webhook registered!")
print(f"Signing Secret (save securely): {data['secret']}")
```

---

## 6. Complete Python SDK Quickstart Example

```python
"""Minimal end-to-end client script using requests."""

import uuid
import requests


class BusinessOSClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def get(self, endpoint: str, **kwargs):
        return self.session.get(f"{self.base_url}/{endpoint.lstrip('/')}", **kwargs).json()

    def post(self, endpoint: str, data: dict, idempotent: bool = True, **kwargs):
        headers = {}
        if idempotent:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        response = self.session.post(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            json=data,
            headers=headers,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()


if __name__ == "__main__":
    client = BusinessOSClient(
        base_url="http://localhost:8000/api/v1",
        api_key="bos_live_your_key_here",
    )
    items = client.get("catalog/items")
    print(f"Loaded {items.get('count', 0)} catalog items.")
```
