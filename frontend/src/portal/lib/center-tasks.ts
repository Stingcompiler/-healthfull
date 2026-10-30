/**
 * What the public center page offers a visitor (D-0022): the task cards of its first screen, the
 * phone's bottom action bar and the footer's quick links. Pure display choices made from the
 * site switches (ADR 0028, 0029) and the page answer; the server still enforces every switch.
 */
import { WEEK_ORDER, type HoursDay } from "@/lib/weekdays";

/** The policies block of the page, which the footer links to. */
export const POLICIES_ID = "center-policies";

export type BookTarget = "/portal/appointments/new" | "/portal/book";

export interface CenterTaskInput {
  onlineBooking: boolean;
  patientTracking: boolean;
  guestBooking: boolean;
  signedIn: boolean;
  /** The page lists doctors (something a signed-out visitor could book after signing in). */
  hasDoctors: boolean;
  phoneUri: string;
  whatsapp: string;
  hasAddress: boolean;
  hasHours: boolean;
}

export interface CenterTasks {
  /** Book online: a patient from the file, a visitor as a guest (ADR 0029 D); null when off. */
  book: BookTarget | null;
  /** Booking is open but only from a file, and the visitor is signed out: book after sign-in. */
  bookViaSignIn: boolean;
  /** Open a guest booking with its reference and PIN. */
  myBooking: boolean;
  /** Sign in to the file (signed out) or open it (signed in). */
  signIn: boolean;
  call: boolean;
  whatsapp: boolean;
  directions: boolean;
  hours: boolean;
}

/** Where "Book online" leads, or null while it is not offered to this visitor. */
export function bookTarget(
  input: Pick<CenterTaskInput, "onlineBooking" | "patientTracking" | "guestBooking" | "signedIn">,
): BookTarget | null {
  if (!input.onlineBooking) return null;
  if (input.signedIn && input.patientTracking) return "/portal/appointments/new";
  if (input.guestBooking) return "/portal/book";
  return null;
}

export function centerTasks(input: CenterTaskInput): CenterTasks {
  const book = bookTarget(input);
  return {
    book,
    bookViaSignIn: book === null && !input.signedIn && input.onlineBooking && input.patientTracking && input.hasDoctors,
    myBooking: input.guestBooking && !input.signedIn,
    signIn: input.patientTracking,
    call: Boolean(input.phoneUri),
    whatsapp: Boolean(input.whatsapp),
    directions: input.hasAddress,
    hours: input.hasHours,
  };
}

export interface StickyBar {
  book: BookTarget | null;
  signIn: boolean;
  call: boolean;
}

/** The phone's bottom bar: book and sign in as before, plus a call button when there is a phone. */
export function stickyBar(input: CenterTaskInput): StickyBar | null {
  const bar = { book: bookTarget(input), signIn: input.patientTracking, call: Boolean(input.phoneUri) };
  return bar.book || bar.signIn || bar.call ? bar : null;
}

export interface HoursRun {
  /** First and last weekday of a run of consecutive days (week order) sharing the same hours. */
  from: number;
  to: number;
  opens: string;
  closes: string;
}

/**
 * The footer's hours summary: consecutive open days (Saturday first) with the same hours become
 * one run, "Sat – Wed 8:00 AM – 8:00 PM". Days off and days without times are left out.
 */
export function summarizeHours(hours: readonly HoursDay[]): HoursRun[] {
  const byDay = new Map(hours.map((h) => [h.weekday, h]));
  const runs: HoursRun[] = [];
  let previous: number | null = null;
  for (const weekday of WEEK_ORDER) {
    const day = byDay.get(weekday);
    const open = day?.opens && day.closes && !day.closed ? { opens: day.opens, closes: day.closes } : null;
    const last = runs.at(-1);
    if (open && last?.to === previous && last.opens === open.opens && last.closes === open.closes) {
      last.to = weekday;
    } else if (open) {
      runs.push({ from: weekday, to: weekday, ...open });
    }
    previous = open ? weekday : null;
  }
  return runs;
}

/**
 * Which public website page a portal path is (D-0022, D-0023): the center page itself, one of
 * the two guest booking pages (same header, width and footer), or a plain portal screen (null).
 */
export function sitePage(pathname: string): "center" | "guest" | null {
  const trimmed = pathname.replace(/\/+$/u, "");
  if (trimmed === "/portal" || trimmed === "") return "center";
  if (trimmed === "/portal/book" || trimmed === "/portal/booking") return "guest";
  return null;
}
