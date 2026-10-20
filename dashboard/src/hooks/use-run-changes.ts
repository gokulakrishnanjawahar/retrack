"use client";

import type { RealtimePostgresChangesPayload } from "@supabase/supabase-js";
import { useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";

export type StreamStatus = "connecting" | "live" | "offline";

type Row = Record<string, unknown>;

// Streams a project's run changes (Supabase Realtime). The user's session token is attached
// before joining, so row-level security admits the stream; "live" means Postgres confirmed it.
export function useRunChanges(
  projectId: string,
  onChange: (payload: RealtimePostgresChangesPayload<Row>) => void,
): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const handler = useRef(onChange);
  useEffect(() => {
    handler.current = onChange;
  });

  useEffect(() => {
    const supabase = createClient();
    let channel: ReturnType<typeof supabase.channel> | null = null;
    let cancelled = false;

    (async () => {
      const { data } = await supabase.auth.getSession();
      if (cancelled) return;
      if (!data.session) {
        setStatus("offline");
        return;
      }
      await supabase.realtime.setAuth(data.session.access_token);
      channel = supabase
        .channel(`runs:${projectId}`)
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table: "runs", filter: `project_id=eq.${projectId}` },
          (payload) => handler.current(payload),
        )
        .on("system", {}, (message: { extension?: string; status?: string }) => {
          if (message.extension === "postgres_changes") setStatus(message.status === "ok" ? "live" : "offline");
        })
        .subscribe((state) => {
          if (state === "CHANNEL_ERROR" || state === "TIMED_OUT") setStatus("offline");
        });
    })();

    return () => {
      cancelled = true;
      if (channel) supabase.removeChannel(channel);
    };
  }, [projectId]);

  return status;
}
