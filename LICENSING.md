# BlueprintIQ Licensing

BlueprintIQ is **proprietary software**. The source code in this repository
is made available for evaluation and due-diligence purposes only. All
production use, deployment, and distribution requires a signed commercial
license agreement.

---

## License Tiers

### 1 · SaaS Access (End-User Subscription)

For architects, engineers, and consultants who need access to the hosted
BlueprintIQ platform.

| Plan     | Price         | Reviews / mo | Users       | Features                                      |
|----------|---------------|-------------|-------------|-----------------------------------------------|
| Free     | $0            | 1           | 1           | Single review, PDF report                     |
| Pro      | $149 / mo     | Unlimited   | 1           | All rules, history, priority support          |
| Agency   | $399 / mo     | Unlimited   | 10 seats    | Team dashboard, custom branding, API access   |

Subscriptions are managed through Stripe. See `/auth/upgrade` endpoint.

---

### 2 · White-Label License

For healthcare-tech companies, AEC software vendors, or consulting firms that
want to embed BlueprintIQ inside their own product.

**What you get:**
- Full source code access under a white-label license
- Right to rebrand (your logo, domain, color scheme)
- Right to deploy on your own infrastructure
- Rule-set customization (add jurisdiction-specific rules)
- 12 months of updates + priority support

**Pricing:** Starting at **$24,000 / year** (single deployment) or
**$48,000 / year** (multi-tenant / reseller rights)

---

### 3 · Enterprise On-Premise License

For hospital systems, health networks, or government agencies that require
air-gapped or on-premise deployment with no external API calls.

**What you get:**
- Everything in White-Label
- Right to host fully on-premise / private cloud
- Swap LLM backend (Azure OpenAI, local Llama, etc.)
- SLA: 99.9 % uptime commitment, 4-hour response SLA
- Annual rule-set audit + compliance attestation

**Pricing:** Starting at **$75,000 / year** — includes 3 named
environments (dev / staging / prod)

---

### 4 · OEM / Reseller License

For companies that want to resell BlueprintIQ-powered reviews as part of
their own service offering (e.g., plan-check-as-a-service).

**What you get:**
- API access + per-review pricing model
- Volume discounts from 10 ¢ / review at scale
- Co-marketing options

**Pricing:** Custom — contact us with estimated monthly review volume.

---

## Frequently Asked Questions

**Can I fork and self-host for free?**
No. The MIT license that may appear in git history has been superseded by the
proprietary license in `LICENSE`. Production deployment of any kind requires a
commercial agreement.

**Can I evaluate the code before buying?**
Yes. You may read and run the code locally for evaluation purposes. You may not
deploy it to a production environment, share it, or use it to serve external
users without a license.

**Do you offer pilot programs?**
Yes — 30-day pilot licenses are available at no cost for qualified enterprise
prospects. Contact us to apply.

**What about open-source dependencies?**
BlueprintIQ is built on open-source libraries (FastAPI, SQLite, etc.) which
retain their respective licenses. Only the BlueprintIQ-specific application
code and rule sets are proprietary.

---

## Contact

**Licensing inquiries:** licensing@blueprintiq.io  
**Enterprise / White-Label:** mason@blueprintiq.io  
**General:** hello@blueprintiq.io
