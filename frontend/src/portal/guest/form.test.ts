import { describe, expect, it } from "vitest";

import { guestContactSchema, guestSignInSchema, normalizeReference, phoneKey } from "./form";

describe("guest booking form", () => {
  it.each([
    ["0912345678", "249912345678"],
    ["0912 345 678", "249912345678"],
    ["912345678", "249912345678"],
    ["+249 912-345-678", "249912345678"],
    ["00201001234567", "201001234567"],
    ["٠٩١٢٣٤٥٦٧٨", "249912345678"],
  ])("folds the phone %j like the server", (raw, key) => {
    expect(phoneKey(raw)).toBe(key);
  });

  it.each(["", "12", "abc", "0912abc678", "+1234567890123456"])("refuses %j as a phone", (raw) => {
    expect(phoneKey(raw)).toBeNull();
  });

  it("needs a name and a phone", () => {
    const empty = guestContactSchema.safeParse({ contact_name: " ", contact_phone: "" });
    expect(empty.success).toBe(false);
    const paths = empty.error?.issues.map((i) => i.path[0]);
    expect(paths).toEqual(expect.arrayContaining(["contact_name", "contact_phone"]));
    expect(guestContactSchema.safeParse({ contact_name: "Amna", contact_phone: "0912345678" }).success).toBe(true);
  });

  it("caps the name at 200 characters", () => {
    expect(guestContactSchema.safeParse({ contact_name: "a".repeat(201), contact_phone: "0912345678" }).success).toBe(
      false,
    );
  });
});

describe("guest sign-in form", () => {
  it("forgives case, spaces and the dash in the reference", () => {
    expect(normalizeReference("abcde-fgh23")).toBe("ABCDEFGH23");
    expect(guestSignInSchema.safeParse({ reference: "abcde fgh23", pin: "012345" }).success).toBe(true);
  });

  it("refuses a malformed reference or PIN", () => {
    expect(guestSignInSchema.safeParse({ reference: "ABCDE-FGH1", pin: "012345" }).success).toBe(false);
    expect(guestSignInSchema.safeParse({ reference: "ABCDE-FGH23", pin: "12345" }).success).toBe(false);
    expect(guestSignInSchema.safeParse({ reference: "ABCDE-FGH23", pin: "٠١٢٣٤٥" }).success).toBe(true);
  });
});
