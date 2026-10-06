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
    permission: "pharmacy.dispense",
  },
];
