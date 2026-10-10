import { describe, expect, it } from "vitest";

import { en } from "@/i18n/resources";

import type { AppNotification } from "./api";
import { KNOWN_KINDS, isKnownKind, isUrgent, notificationParams, notificationTarget } from "./kinds";

function note(kind: string, payload: Record<string, unknown> = {}): AppNotification {
  return { id: 1, kind, payload, created_at: "2026-10-10T08:00:00Z", read_at: null };
}

describe("notification kinds", () => {
  it("has a text for every known kind and a fallback", () => {
    const kinds = en.ops.notifications.kinds as Record<string, unknown>;
    for (const kind of KNOWN_KINDS) {
      const present = kind in kinds || `${kind}_one` in kinds;
      expect(present, kind).toBe(true);
    }
    expect(kinds.other).toBeTruthy();
  });

  it("opens the screen that resolves each alert", () => {
    expect(notificationTarget(note("lab_result_ready", { visit_id: 12 }))).toEqual({
      to: "/clinic/visits/$visitId",
      visitId: "12",
    });
    expect(notificationTarget(note("lab_result_critical"))).toBeNull();
    expect(notificationTarget(note("stock_low_summary"))).toEqual({ to: "/pharmacy/low-stock" });
    expect(notificationTarget(note("transfers_pending_overdue"))).toEqual({ to: "/cashier/transfers" });
    expect(notificationTarget(note("shift_review_pending"))).toEqual({ to: "/cashier/review" });
    expect(notificationTarget(note("patient_credit_negative", { patient_id: 7 }))).toEqual({
      to: "/patients/$patientId",
      patientId: "7",
    });
    expect(notificationTarget(note("backup_stale"))).toEqual({ to: "/administration/system" });
    expect(notificationTarget(note("something_new"))).toBeNull();
  });

  it("formats the payload for the text", () => {
    const params = notificationParams(
      note("shift_variance", { shift_number: "SH-2026-000003", variance: "-500.00", count: 2, critical: ["HGB"] }),
      "en",
    );
    expect(params.number).toBe("SH-2026-000003");
    expect(params.count).toBe(2);
    expect(params.critical).toBe("HGB");
    expect(String(params.variance)).toContain("500");
    expect(notificationParams(note("stock_low", { on_hand: { bad: 1 } }), "en").onHand).toBe("0");
  });

  it("knows its kinds and the urgent ones", () => {
    expect(isKnownKind("stock_low")).toBe(true);
    expect(isKnownKind("nope")).toBe(false);
    expect(isUrgent("lab_result_critical")).toBe(true);
    expect(isUrgent("stock_low")).toBe(false);
  });
});
