"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import Link from "next/link";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ProjectSummary } from "@/lib/data";

function Initial({ name }: { name: string }) {
  return (
    <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-brand/80 to-[oklch(0.7_0.13_190)] text-[11px] font-semibold text-white">
      {name.charAt(0).toUpperCase()}
    </span>
  );
}

export function ProjectSwitcher({ current, projects }: { current: ProjectSummary; projects: ProjectSummary[] }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-lg border border-border bg-white/[0.02] px-2 py-1.5 text-left transition-colors hover:bg-white/[0.04]">
        <Initial name={current.organization || current.name} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{current.name}</span>
          <span className="block truncate text-[11px] text-faint">{current.organization}</span>
        </span>
        <ChevronsUpDown className="size-3.5 text-faint" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        <DropdownMenuLabel className="text-[11px] text-faint">Projects</DropdownMenuLabel>
        {projects.map((p) => (
          <DropdownMenuItem key={p.id} asChild>
            <Link href={`/p/${p.id}`} className="flex items-center gap-2">
              <Initial name={p.organization || p.name} />
              <span className="min-w-0 flex-1 truncate">
                {p.name} <span className="text-faint">· {p.organization}</span>
              </span>
              {p.id === current.id ? <Check className="size-3.5 text-brand" /> : null}
            </Link>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/onboarding" className="flex items-center gap-2 text-muted-foreground">
            <Plus className="size-3.5" /> New project
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
