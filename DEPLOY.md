# BlueprintIQ — Deployment Guide (Railway)

## Prerequisites

- GitHub account with this repo pushed to it
- Railway account: https://railway.app (free to start)
- Anthropic API key: https://console.anthropic.com
- Stripe account: https://dashboard.stripe.com

---

## Step 1 — Stripe Setup (15 min)

### 1a. Create subscription products

Go to Stripe Dashboard → **Products** → **Add product**

**Pro Plan**
- Name: `BlueprintIQ Pro`
- Price: `$299.00` / month / recurring
- Copy the `price_...` ID → this is your `STRIPE_PRO_PRICE_ID`

**Agency Plan**
- Name: `BlueprintIQ Agency`
- Price: `$899.00` / month / recurring
- Copy the `price_...` ID → this is your `STRIPE_AGENCY_PRICE_ID`

### 1b. Get your API keys

Stripe Dashboard → **Developers** → **API keys**
- Copy **Secret key** → `STRIPE_SECRET_KEY`
- Use `sk_test_...` for testing, `sk_live_...` for production

### 1c. Webhook (set AFTER Railway deploy — you need your URL first)

Stripe Dashboard → **Developers** → **Webhooks** → **Add endpoint**
- URL: `https://YOUR-RAILWAY-DOMAIN.up.railway.app/stripe/webhook`
- Events to listen for: `checkout.session.completed`
- Copy **Signing secret** → `STRIPE_WEBHOOK_SECRET`

---

## Step 2 — Generate a JWT Secret

Run locally:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output → `JWT_SECRET`

---

## Step 3 — Deploy to Railway

### 3a. Create project

1. Go to https://railway.app → **New Project**
2. **Deploy from GitHub repo** → select this repo
3. Railway detects `railway.toml` and uses the Dockerfile automatically

### 3b. Add a Volume (CRITICAL for SQLite persistence)

Without this, your database resets on every deploy.

1. In your Railway service → **Volumes** tab → **Add Volume**
2. Mount path: `/app/data`
3. Size: `1 GB` (expandable)

This persists `data/hcai.db` and `hcai_rules.db` across restarts.

### 3c. Set environment variables

Railway service → **Variables** tab → add each of these:

```
ANTHROPIC_API_KEY        = sk-ant-...
JWT_SECRET               = (output from Step 2)
STRIPE_SECRET_KEY        = sk_live_...
STRIPE_WEBHOOK_SECRET    = whsec_...  (set after deploy — see Step 1c)
STRIPE_PRO_PRICE_ID      = price_...
STRIPE_AGENCY_PRICE_ID   = price_...
APP_BASE_URL             = https://YOUR-DOMAIN.up.railway.app
CORS_ORIGINS             = https://YOUR-DOMAIN.up.railway.app
LOG_LEVEL                = INFO
```

Optional — email delivery:
```
SMTP_HOST                = smtp.gmail.com
SMTP_PORT                = 587
SMTP_USER                = you@gmail.com
SMTP_PASSWORD            = (16-char Gmail app password)
EMAIL_FROM               = BlueprintIQ <hello@blueprintiq.io>
```

### 3d. Deploy

Railway deploys automatically on push. First deploy takes ~3 min (Docker build).

Check: `https://YOUR-DOMAIN.up.railway.app/health` → should return `{"status":"ok"}`

---

## Step 4 — Custom Domain (optional)

Railway service → **Settings** → **Domains** → **Add Custom Domain**
- Point your DNS CNAME to the Railway domain
- Railway provisions TLS automatically

---

## Step 5 — Stripe Webhook (complete setup)

Now that you have your URL, go back to Stripe and add the webhook endpoint:
- URL: `https://YOUR-DOMAIN.up.railway.app/stripe/webhook`
- Copy the signing secret into Railway env var `STRIPE_WEBHOOK_SECRET`
- Trigger a redeploy (Railway → **Deploy** → **Redeploy**)

---

## Verification Checklist

- [ ] `GET /health` returns `{"status":"ok"}`
- [ ] `POST /auth/register` creates a user and returns a JWT
- [ ] `POST /auth/login` returns a JWT
- [ ] `POST /auth/upgrade` (with JWT) returns a Stripe checkout URL
- [ ] Stripe test checkout completes and webhook fires
- [ ] `POST /review` with a PDF returns a `job_id`
- [ ] `GET /review/{job_id}` eventually returns `status: completed`

---

## Costs (monthly estimate)

| Service | Plan | Cost |
|---------|------|------|
| Railway | Hobby ($5 credit free) | ~$5–15/mo |
| Anthropic API | Pay per token | ~$0.50–3.00 per review |
| Stripe | 2.9% + 30¢ per transaction | % of revenue |

At 50 Pro subscribers ($299/mo): ~$14,950 MRR, ~$435 in Stripe fees, ~$20 infra.

---

## Updating the App

```bash
git push origin main   # Railway auto-deploys on push to main
```

Monitor deploy: Railway dashboard → **Deployments** tab

---

## Troubleshooting

**App crashes on start:**
Check Railway logs. Most common cause: missing `ANTHROPIC_API_KEY`.

**Database resets on every deploy:**
Volume not mounted. Re-check Step 3b. Mount path must be `/app/data`.

**Stripe checkout fails:**
`STRIPE_PRO_PRICE_ID` or `STRIPE_AGENCY_PRICE_ID` is empty or wrong environment
(test key with live price ID won't work).

**JWT errors after redeploy:**
`JWT_SECRET` changed — all existing tokens invalidated. Keep it stable.
