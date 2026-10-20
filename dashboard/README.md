# dashboard

Retrack's web dashboard: Next.js 16 (App Router), Tailwind 4, shadcn/ui (Radix), Motion,
Recharts, Supabase Auth.

- Reads run as the signed-in user, so row-level security limits them to the user's projects.
- Writes go through `public.dashboard_*` database functions, which check the user's role.
- New API keys are generated and hashed on the server (`src/lib/keys.ts`, same format and
  HMAC as the API server); only the prefix and hash reach the database.

```
npm run dev      # http://localhost:3000
npm test         # vitest
npm run lint && npx tsc --noEmit
```

Copy `.env.example` to `.env.local` and fill it in.
