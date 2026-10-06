import { Users } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "patients",
    to: "/patients",
    labelKey: "patients",
    icon: Users,
    group: "frontDesk",
    order: 20,
    permission: "patients.view",
  },
];
