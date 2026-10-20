import "server-only";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

// A Supabase client acting as the signed-in user: every query runs under row-level security.
// Create one per request.
export async function createClient() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component, where cookies are read-only. The proxy
            // refreshes the session on every request, so this is safe to ignore.
          }
        },
      },
    },
  );
}
