import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/render";

import { RadioGroup, RadioGroupSegment } from "./radio-group";

function Methods() {
  const [value, setValue] = useState("cash");
  return (
    <RadioGroup value={value} onValueChange={setValue} aria-label="Method">
      <RadioGroupSegment value="cash">Cash</RadioGroupSegment>
      <RadioGroupSegment value="card">Card</RadioGroupSegment>
    </RadioGroup>
  );
}

describe("RadioGroupSegment", () => {
  it("marks the chosen segment checked, so its raised style applies", async () => {
    const user = userEvent.setup();
    await renderWithProviders(<Methods />);
    const cash = screen.getByRole("radio", { name: "Cash" });
    const card = screen.getByRole("radio", { name: "Card" });
    expect(cash).toHaveAttribute("aria-checked", "true");
    expect(cash).toHaveAttribute("data-state", "checked");
    expect(card).toHaveAttribute("data-state", "unchecked");
    await user.click(card);
    expect(card).toHaveAttribute("data-state", "checked");
    expect(cash).toHaveAttribute("aria-checked", "false");
  });
});
