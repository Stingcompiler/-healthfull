import { Syringe } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "nursing",
    to: "/nursing",
    labelKey: "nursing",
    icon: Syringe,
    group: "services",
    order: 90,
    // Any nursing section: procedures, vitals and notes, or the bed board.
    permission: ["orders.perform_procedure", "clinical.record_vitals", "visits.manage_beds"],
  },
];
