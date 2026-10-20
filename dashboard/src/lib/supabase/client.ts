import { createBrowserClient } from "@supabase/ssr";

// Browser client for live updates (Realtime). Row-level security applies to it as well.
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  );
}
