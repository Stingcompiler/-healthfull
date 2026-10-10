import { BookOpen, ClipboardCheck, FlaskConical, Timer, type LucideIcon } from "lucide-react";

export type LabPath = "/lab" | "/lab/approve" | "/lab/catalog" | "/lab/tat";

interface LabLink {
  to: LabPath;
  key: "worklist" | "approve" | "catalog" | "tat";
  icon: LucideIcon;
  permission: string;
}

/** The lab module's screens; each shows only to users who may use it (UI hint only). */
export const LAB_LINKS: readonly LabLink[] = [
  { to: "/lab", key: "worklist", icon: FlaskConical, permission: "lab.view_worklist" },
  { to: "/lab/approve", key: "approve", icon: ClipboardCheck, permission: "lab.approve_results" },
  { to: "/lab/catalog", key: "catalog", icon: BookOpen, permission: "lab.manage_tests" },
  { to: "/lab/tat", key: "tat", icon: Timer, permission: "lab.view_reports" },
];

/** The tab a path belongs to: a test, its label and its printout belong to the work list. */
export function activeLabPath(pathname: string): LabPath | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/lab" || path.startsWith("/lab/results/") || path.startsWith("/lab/samples/")) return "/lab";
  if (path.startsWith("/lab/catalog")) return "/lab/catalog";
  return LAB_LINKS.find((l) => l.to === path)?.to;
}
