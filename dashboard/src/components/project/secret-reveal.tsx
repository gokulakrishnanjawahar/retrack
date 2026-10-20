"use client";

import { ShieldAlert } from "lucide-react";
import { motion } from "motion/react";
import { CopyButton } from "@/components/copy-button";

// A new API key, shown once. Only its hash is stored, so it cannot be shown again.
export function SecretReveal({ secret }: { secret: string }) {
  return (
    <div className="min-w-0 space-y-2.5">
      <div className="relative flex items-center gap-2 overflow-hidden rounded-lg border border-brand/30 bg-brand-soft py-2 pr-1.5 pl-3">
        <motion.div
          initial={{ x: "-100%" }}
          animate={{ x: "100%" }}
          transition={{ duration: 1.2, ease: "easeInOut" }}
          className="pointer-events-none absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent"
        />
        <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-foreground">{secret}</code>
        <CopyButton value={secret} label="Copy API key" />
      </div>
      <p className="flex items-center gap-1.5 text-xs text-warning">
        <ShieldAlert className="size-3.5" />
        Copy it now: for your security it will not be shown again.
      </p>
    </div>
  );
}
