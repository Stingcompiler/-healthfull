import { Wallet } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "cashier",
    to: "/cashier",
    labelKey: "cashier",
    icon: Wallet,
    group: "finance",
    order: 50,
    permission: "payments.take_payment",
  },
];
