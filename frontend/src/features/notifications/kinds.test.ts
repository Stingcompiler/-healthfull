import { describe, expect, it } from "vitest";

import { en } from "@/i18n/resources";

import type { AppNotification } from "./api";
import {
  KNOWN_KINDS,
  NOTIFICATION_LINKS,
  isKnownKind,
  isUrgent,
  notificationParams,
  notificationTarget,
} from "./kinds";

function note(kind: string, payload: Record<string, unknown> = {}): AppNotification {
  return { id: 1, kind, payload, created_at: "2026-10-10T08:00:00Z", read_at: null };
}

const reader = (...permissions: string[]) => ({ roles: ["someone"], permissions });

const sources = import.meta.glob<string>("../../../../backend/apps/core/notification_kinds.py", {
  query: "?raw",
  import: "default",
  eager: true,
});
const registry = Object.values(sources)[0];

/** kind -> [route, permission][] as declared in the backend table. */
function backendLinks(text: string): Record<string, [string, string][]> {
  const out: Record<string, [string, string][]> = {};
  const entries = text.split(/NotificationKind\(\s*\n?\s*"/).slice(1);
  for (const entry of entries) {
    const code = entry.slice(0, entry.indexOf('"'));
    if (!/^[a-z_]+$/.test(code)) continue; // the docstring's example
    out[code] = [...entry.matchAll(/Link\("([^"]+)", "([^"]+)"\)/g)].map((m) => [m[1] ?? "", m[2] ?? ""]);
  }
  return out;
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

  it("opens the screen that resolves each alert for a reader who may open it", () => {
    const doctor = reader("clinical.view");
    expect(notificationTarget(note("lab_result_ready", { visit_id: 12 }), doctor)).toEqual({
      to: "/clinic/visits/$visitId",
      visitId: "12",
    });
    expect(notificationTarget(note("lab_result_critical"), doctor)).toBeNull();
    expect(notificationTarget(note("stock_low_summary"), reader("pharmacy.view"))).toEqual({
      to: "/pharmacy/low-stock",
    });
    expect(notificationTarget(note("transfers_pending_overdue"), reader("payments.confirm_transfer"))).toEqual({
      to: "/cashier/transfers",
    });
    expect(notificationTarget(note("shift_review_pending"), reader("payments.review_shift"))).toEqual({
      to: "/cashier/review",
    });
    expect(notificationTarget(note("patient_credit_negative", { patient_id: 7 }), reader("patients.view"))).toEqual({
      to: "/patients/$patientId",
      patientId: "7",
    });
    expect(notificationTarget(note("integrity_failed"), reader("ops.view_status"))).toEqual({
      to: "/administration/system",
    });
    expect(notificationTarget(note("something_new"), doctor)).toBeNull();
  });

  it("sends a manager to the patient file, not to the transfer queue they cannot open", () => {
    const rejected = note("transfer_rejected", { patient_id: 5 });
    const manager = reader("patients.view", "payments.view", "payments.review_shift");
    expect(notificationTarget(rejected, manager)).toEqual({ to: "/patients/$patientId", patientId: "5" });
    const supervisor = reader("patients.view", "payments.confirm_transfer");
    expect(notificationTarget(rejected, supervisor)).toEqual({ to: "/cashier/transfers" });
  });

  it("shows no link when the reader may open none of its screens", () => {
    expect(notificationTarget(note("backup_stale"), reader("patients.view"))).toBeNull();
    expect(notificationTarget(note("backup_stale"), null)).toBeNull();
  });

  it.skipIf(registry === undefined)("links exactly as the backend table declares", () => {
    const backend = backendLinks(registry ?? "");
    expect(Object.keys(backend).sort()).toEqual([...KNOWN_KINDS].sort());
    for (const kind of KNOWN_KINDS) {
      expect(
        NOTIFICATION_LINKS[kind].map((l) => [l.route, l.permission]),
        kind,
      ).toEqual(backend[kind]);
    }
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
    expect(isUrgent("integrity_failed")).toBe(true);
    expect(isUrgent("stock_low")).toBe(false);
  });
});
