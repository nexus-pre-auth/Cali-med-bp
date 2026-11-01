import { next } from '@vercel/edge';

export const config = { matcher: '/index.html' };

export default async function middleware(req) {
  const res = await next();
  const html = await res.text();

  const injected = html.replace(
    "const SUPABASE_URL = '';",
    `const SUPABASE_URL = '${process.env.NEXT_PUBLIC_SUPABASE_URL || ''}';`
  ).replace(
    "const SUPABASE_ANON = '';",
    `const SUPABASE_ANON = '${process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''}';`
  );

  return new Response(injected, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}
