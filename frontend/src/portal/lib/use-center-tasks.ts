import type { CenterPage } from "@/lib/center/api";
import { getSiteConfig } from "@/lib/site";

import { usePortalMe } from "../api";
import { type CenterTaskInput } from "./center-tasks";
import { usePick } from "./ui";

/** The inputs of `centerTasks` and `stickyBar`: the site switches, the session and the page. */
export function useCenterTaskInput(page: CenterPage | undefined): CenterTaskInput {
  const me = usePortalMe();
  const pick = usePick();
  const { onlineBooking, patientTracking, guestBooking } = getSiteConfig();
  return {
    onlineBooking,
    patientTracking,
    guestBooking,
    signedIn: Boolean(me.data),
    hasDoctors: Boolean(page && page.doctors.length > 0),
    phoneUri: page?.phone_uri ?? "",
    whatsapp: page?.whatsapp ?? "",
    hasAddress: Boolean(page && (page.address || pick(page.directions_ar, page.directions_en) || page.maps_url)),
    hasHours: Boolean(page && page.hours.length > 0),
  };
}
