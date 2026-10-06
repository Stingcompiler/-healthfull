import { describe, expect, it } from "vitest";
import { z } from "zod";

import { decodeMessage, vmsg } from "./validation";

describe("validation messages", () => {
  it("round-trips keys and params", () => {
    expect(decodeMessage(vmsg("validation.required"))).toEqual({ key: "validation.required", params: {} });
    expect(decodeMessage(vmsg("validation.minLength", { min: 8 }))).toEqual({
      key: "validation.minLength",
      params: { min: 8 },
    });
    expect(decodeMessage("plain server text")).toBeNull();
  });

  it("gives zod issues translatable defaults", () => {
    const schema = z.object({ name: z.string().min(1), code: z.string().min(6) });
    const result = schema.safeParse({ name: "", code: "12" });
    expect(result.success).toBe(false);
    const messages = result.error?.issues.map((i) => decodeMessage(i.message)?.key);
    expect(messages).toEqual(["validation.required", "validation.minLength"]);
  });
});
