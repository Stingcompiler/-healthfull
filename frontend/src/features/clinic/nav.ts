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
    permission: "clinical.view",
  },
];
