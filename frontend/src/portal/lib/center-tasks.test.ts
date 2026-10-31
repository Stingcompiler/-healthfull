import { describe, expect, it } from "vitest";

import {
  bookTarget,
  centerTasks,
  patientBookingPage,
  sitePage,
  stickyBar,
  summarizeHours,
  type CenterTaskInput,
} from "./center-tasks";

const base: CenterTaskInput = {
  onlineBooking: false,
  patientTracking: false,
  guestBooking: false,
  signedIn: false,
  hasDoctors: true,
  phoneUri: "",
  whatsapp: "",
  hasAddress: false,
  hasHours: false,
};

describe("center page tasks (D-0022)", () => {
  it("offers nothing to book while online booking is off", () => {
    expect(bookTarget({ ...base, guestBooking: true, patientTracking: true, signedIn: true })).toBeNull();
    const tasks = centerTasks({ ...base, patientTracking: true });
    expect(tasks.book).toBeNull();
    expect(tasks.bookViaSignIn).toBe(false);
    expect(tasks.myBooking).toBe(false);
    expect(tasks.signIn).toBe(true);
  });

  it("sends a visitor to guest booking and a signed-in patient to their file", () => {
    const on = { ...base, onlineBooking: true, guestBooking: true, patientTracking: true };
    expect(centerTasks(on).book).toBe("/portal/book");
    expect(centerTasks(on).myBooking).toBe(true);
    expect(centerTasks({ ...on, signedIn: true }).book).toBe("/portal/appointments/new");
    expect(centerTasks({ ...on, signedIn: true }).myBooking).toBe(false);
  });

  it("books after sign-in when guest booking is off and there are doctors", () => {
    const fileOnly = { ...base, onlineBooking: true, patientTracking: true };
    expect(centerTasks(fileOnly).book).toBeNull();
    expect(centerTasks(fileOnly).bookViaSignIn).toBe(true);
    expect(centerTasks({ ...fileOnly, hasDoctors: false }).bookViaSignIn).toBe(false);
    expect(centerTasks({ ...fileOnly, patientTracking: false }).bookViaSignIn).toBe(false);
  });

  it("offers contact tasks only for the data the page has", () => {
    const tasks = centerTasks({ ...base, phoneUri: "tel:+249911234567", hasHours: true });
    expect(tasks).toMatchObject({ call: true, whatsapp: false, directions: false, hours: true });
  });

  it("drops the phone bar when it has nothing to offer", () => {
    expect(stickyBar(base)).toBeNull();
    expect(stickyBar({ ...base, phoneUri: "tel:1" })).toEqual({ book: null, signIn: false, call: true });
    expect(stickyBar({ ...base, onlineBooking: true, guestBooking: true })?.book).toBe("/portal/book");
  });
});

describe("summarizeHours", () => {
  const day = (weekday: number, opens: string | null, closes: string | null, closed = false) => ({
    weekday,
    opens,
    closes,
    closed,
  });

  it("joins consecutive days with the same hours, Saturday first", () => {
    // 5 = Saturday ... 3 = Thursday, 4 = Friday (week order 5, 6, 0, 1, 2, 3, 4).
    const hours = [
      day(5, "08:00", "20:00"),
      day(6, "08:00", "20:00"),
      day(0, "08:00", "20:00"),
      day(1, "08:00", "20:00"),
      day(2, "08:00", "20:00"),
      day(3, "08:00", "14:00"),
      day(4, null, null, true),
    ];
    expect(summarizeHours(hours)).toEqual([
      { from: 5, to: 2, opens: "08:00", closes: "20:00" },
      { from: 3, to: 3, opens: "08:00", closes: "14:00" },
    ]);
  });

  it("splits a run at a day off even when the hours match again", () => {
    const hours = [day(5, "08:00", "20:00"), day(6, null, null, true), day(0, "08:00", "20:00")];
    expect(summarizeHours(hours)).toEqual([
      { from: 5, to: 5, opens: "08:00", closes: "20:00" },
      { from: 0, to: 0, opens: "08:00", closes: "20:00" },
    ]);
  });

  it("is empty without hours", () => {
    expect(summarizeHours([])).toEqual([]);
    expect(summarizeHours([day(5, "08:00", null)])).toEqual([]);
  });
});

describe("sitePage", () => {
  it("knows the center page and the two guest booking pages", () => {
    expect(sitePage("/portal")).toBe("center");
    expect(sitePage("/portal/")).toBe("center");
    expect(sitePage("/")).toBe("center");
    expect(sitePage("/portal/book")).toBe("guest");
    expect(sitePage("/portal/booking/")).toBe("guest");
  });

  it("leaves every other portal screen alone", () => {
    expect(sitePage("/portal/sign-in")).toBeNull();
    expect(sitePage("/portal/appointments/new")).toBeNull();
    expect(sitePage("/portal/bookings")).toBeNull();
  });
});

describe("patientBookingPage", () => {
  it("knows the signed-in booking and reschedule screens", () => {
    expect(patientBookingPage("/portal/appointments/new")).toBe(true);
    expect(patientBookingPage("/portal/appointments/new/")).toBe(true);
    expect(patientBookingPage("/portal/appointments/12/reschedule")).toBe(true);
  });

  it("leaves the list, the guest pages and other screens alone", () => {
    expect(patientBookingPage("/portal/appointments")).toBe(false);
    expect(patientBookingPage("/portal/appointments/x/reschedule")).toBe(false);
    expect(patientBookingPage("/portal/book")).toBe(false);
    expect(patientBookingPage("/portal/home")).toBe(false);
  });
});
