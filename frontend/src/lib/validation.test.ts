import { describe, expect, it } from "vitest";
import { z } from "zod";

import { decodeMessage, vmsg } from "./validation";

describe("validation messages", () => {
  it("round-trips keys and params", () => {
    expect(decodeMessage(vmsg("validation.required"))).toEqual({ key: "validation.required", params: {} });
    expect(decodeMessage(vmsg("validation.minLength", { count: 8 }))).toEqual({
      key: "validation.minLength",
      params: { count: 8 },
    });
    expect(decodeMessage("plain server text")).toBeNull();
  });

  it("gives zod issues translatable defaults", () => {
    const schema = z.object({ name: z.string().min(1), code: z.string().min(6) });
    const result = schema.safeParse({ name: "", code: "12" });
    expect(result.success).toBe(false);
    const messages = result.error?.issues.map((i) => decodeMessage(i.message)?.key);
    expect(messages).toEqual(["validation.required", "validation.minLength"]);
    expect(decodeMessage(result.error?.issues[1]?.message ?? "")?.params).toEqual({ count: 6 });
  });

  it("uses Arabic plural forms for length limits", async () => {
    const i18n = (await import("@/i18n")).default;
    const t = i18n.getFixedT("ar", "common");
    expect(t("validation.maxLength", { count: 500 })).toBe("يجب ألا يزيد عن 500 حرف");
    expect(t("validation.maxLength", { count: 10 })).toBe("يجب ألا يزيد عن 10 أحرف");
    expect(t("validation.maxLength", { count: 20 })).toBe("يجب ألا يزيد عن 20 حرفاً");
    expect(t("validation.minLength", { count: 2 })).toBe("يجب ألا يقل عن حرفين");
    expect(t("validation.minLength", { count: 1 })).toBe("يجب ألا يقل عن حرف واحد");
    const en = i18n.getFixedT("en", "common");
    expect(en("validation.minLength", { count: 1 })).toBe("Must be at least 1 character");
    expect(en("validation.minLength", { count: 8 })).toBe("Must be at least 8 characters");
  });
});
