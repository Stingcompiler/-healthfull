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
    // Cashiers, supervisors, accountants and managers each use some cashier screens.
    permission: ["payments.take_payment", "payments.view", "billing.view", "orders.authorize_perform_first"],
  },
];
