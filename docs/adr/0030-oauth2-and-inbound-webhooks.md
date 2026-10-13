# ADR 0030: OAuth2 Provider and Inbound Webhook Framework

## Context
External applications, third-party marketplaces, and internal developer integrations require standard OAuth2 authentication (PKCE for SPAs/native apps, client credentials for machine-to-machine integrations). In addition, external services (payment processors, e-commerce stores, CRMs) need to push event notifications into Business OS via inbound webhooks with cryptographic signature verification.

## Decision
1. **OAuth2 Provider**:
   - Integrated `django-oauth-toolkit` (`oauth2_provider`) supporting Authorization Code Grant with PKCE and Client Credentials Grant.
   - `OAuthApplication` model in `apps.integrations.models` inheriting from `AbstractApplication` and `TenantModel`, strictly scoping client apps to tenant organizations with RLS enabled.
   - Granular permission scopes (`catalog:read|write`, `sales:read|write`, `accounting:read|write`, `inventory:read|write`, `admin`, etc.) mapped into the platform's 3-layer security system via `OAuth2Authentication` and token scope validation.
   - Branded consent screen displaying client application details, organization context, and human-readable scope requests.
   - App Registry UI for managing client applications, generating/rotating client secrets, and viewing authorized apps.

2. **Inbound Webhooks Framework**:
   - `InboundWebhookEndpoint` model supporting multi-provider signature verification schemes (Generic HMAC-SHA256, Stripe `t=,v1=`, Shopify Base64 HMAC, GitHub `sha256=`, Bearer token).
   - `InboundWebhookLog` for full audit trails and transcript logs of incoming payloads.
   - Public receiver endpoint `/api/v1/integrations/inbound/<uuid:public_id>/` that validates signatures, records logs, and atomically dispatches domain events (`inbound_webhook.received`) to the transactional outbox.
