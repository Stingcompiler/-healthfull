import { FileStack } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "claims",
    to: "/claims",
    labelKey: "claims",
    icon: FileStack,
    group: "finance",
    order: 60,
    permission: "claims.view",
  },
];
