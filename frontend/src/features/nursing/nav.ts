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
    permission: "orders.perform_procedure",
  },
];
