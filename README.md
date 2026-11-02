# Cali Med BP

A Vercel-ready healthcare compliance workspace built with Next.js and Supabase.

## Stack

- Frontend: Next.js 14 + TypeScript + App Router
- Auth: Supabase Auth
- Data: Supabase Postgres
- Deployment: Vercel
- Review engine: existing Python compliance engine retained as an API/CLI component

## What is included

- Secure sign-in and sign-up with Supabase auth
- Protected dashboard and project routes
- Project creation flow
- Review creation flow with audit findings
- Vercel deployment configuration
- SQL schema for profiles, projects, and reviews

## Local setup

```bash
npm install
cp .env.example .env.local
```

Update `.env.local` with your actual Supabase values:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

Then run:

```bash
npm run dev
```

## Deploy on Vercel

1. Push this branch to GitHub.
2. Import the repo in Vercel.
3. Add the same environment variables in the Vercel dashboard.
4. Set the project framework to Next.js.
5. Deploy.

## Supabase setup

Run the SQL in `supabase/schema.sql` in your Supabase SQL editor.

Then enable email authentication in Supabase Auth.

## Notes

The original Python compliance engine remains available in the repo and is exposed via API integration points. For a full production deployment, ensure the Python review engine is run in an environment with Python available or expose it behind a separate API service.
