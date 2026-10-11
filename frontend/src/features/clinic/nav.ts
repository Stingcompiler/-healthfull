import { Stethoscope } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "clinic",
    to: "/clinic",
    labelKey: "clinic",
    icon: Stethoscope,
    group: "clinical",
    order: 40,
    // The doctor's workspace: a queue of their own patients needs a doctor (nurses hold
    // clinical.view for the nursing chart, not a clinic of their own).
    permission: "clinical.write_note",
  },
];
