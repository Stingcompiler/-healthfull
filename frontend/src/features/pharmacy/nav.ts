import { Pill } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "pharmacy",
    to: "/pharmacy",
    labelKey: "pharmacy",
    icon: Pill,
    group: "services",
    order: 70,
    // Pharmacists dispense; managers and accountants read stock and approve adjustments.
    permission: ["pharmacy.dispense", "pharmacy.view"],
  },
];
