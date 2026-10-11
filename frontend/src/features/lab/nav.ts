import { Droplet, FileCheck2, FlaskConical } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "lab",
    to: "/lab",
    labelKey: "lab",
    icon: FlaskConical,
    group: "services",
    order: 80,
    // Technicians and supervisors work the bench; managers read the turnaround report.
    permission: ["lab.view_worklist", "lab.view_reports"],
  },
  {
    // Nurses draw samples (lab.collect_sample) without the bench; lab staff use the work list.
    id: "lab-collect",
    to: "/lab/collect",
    labelKey: "labCollect",
    icon: Droplet,
    group: "services",
    order: 81,
    permission: "lab.collect_sample",
    unless: "lab.view_worklist",
  },
  {
    // Reception prints approved results (lab.print_results); doctors read them in the clinic.
    id: "lab-approved",
    to: "/lab/approved-results",
    labelKey: "labApproved",
    icon: FileCheck2,
    group: "frontDesk",
    order: 35,
    permission: "lab.print_results",
    unless: ["lab.view_worklist", "clinical.view"],
  },
];
