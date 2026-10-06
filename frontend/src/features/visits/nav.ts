import { CalendarDays, ListOrdered } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "queue",
    to: "/queue",
    labelKey: "queue",
    icon: ListOrdered,
    group: "frontDesk",
    order: 25,
    permission: "visits.view_queue",
  },
  {
    id: "appointments",
    to: "/appointments",
    labelKey: "appointments",
    icon: CalendarDays,
    group: "frontDesk",
    order: 30,
    permission: "visits.manage_appointments",
  },
];
