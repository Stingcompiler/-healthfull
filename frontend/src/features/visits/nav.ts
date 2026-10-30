import { CalendarDays, Inbox, ListOrdered } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "queue",
    to: "/queue",
    labelKey: "queue",
    icon: ListOrdered,
    flipInRtl: true,
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
  {
    id: "online-bookings",
    to: "/visits/online-bookings",
    labelKey: "onlineBookings",
    icon: Inbox,
    group: "frontDesk",
    order: 32,
    permission: "visits.manage_online_bookings",
  },
];
