"use client";

import { BrainCircuit, Gauge, History, KeyRound, ListChecks, Radar, Settings2, ShieldCheck, type LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

type Item = { href: string; label: string; icon: LucideIcon; badge?: number };

export function SidebarNav({ projectId, superAdmin, openReviews }: { projectId: string; superAdmin: boolean; openReviews: number }) {
  const pathname = usePathname();
  const base = `/p/${projectId}`;
  const groups: { title?: string; items: Item[] }[] = [
    { items: [{ href: base, label: "Overview", icon: Gauge }] },
    {
      title: "Agents",
      items: [
        { href: `${base}/runs`, label: "Runs", icon: History },
        { href: `${base}/memory`, label: "Memory", icon: BrainCircuit },
        { href: `${base}/review`, label: "Review", icon: ListChecks, badge: openReviews },
        { href: `${base}/recalls`, label: "Recalls", icon: Radar },
      ],
    },
    {
      title: "Project",
      items: [
        { href: `${base}/keys`, label: "API keys", icon: KeyRound },
        { href: `${base}/settings`, label: "Settings", icon: Settings2 },
      ],
    },
  ];
  if (superAdmin) groups.push({ title: "Retrack", items: [{ href: "/admin", label: "Admin", icon: ShieldCheck }] });

  return (
    <nav className="space-y-5">
      {groups.map((group, g) => (
        <div key={group.title ?? g} className="space-y-0.5">
          {group.title ? (
            <p className="px-2.5 pb-1.5 text-[11px] font-medium tracking-wide text-faint uppercase">{group.title}</p>
          ) : null}
          {group.items.map(({ href, label, icon: Icon, badge }) => {
            const active = href === base ? pathname === base : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
                  active ? "text-foreground" : "text-muted-foreground hover:bg-white/[0.03] hover:text-foreground",
                )}
              >
                {active ? (
                  <motion.span
                    layoutId="nav-active"
                    className="absolute inset-0 rounded-md bg-white/[0.06] ring-1 ring-white/[0.06]"
                    transition={{ type: "spring", stiffness: 500, damping: 40 }}
                  />
                ) : null}
                <Icon className={cn("relative size-4", active ? "text-brand" : "text-faint")} />
                <span className="relative">{label}</span>
                {badge ? (
                  <span className="relative ml-auto rounded-full bg-warning/15 px-1.5 font-mono text-[10.5px] text-warning ring-1 ring-warning/25">
                    {badge}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
