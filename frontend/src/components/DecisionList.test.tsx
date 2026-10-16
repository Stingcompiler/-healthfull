import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/render";

import { DecisionList, DecisionRow } from "./DecisionList";

describe("DecisionList", () => {
  it("shows the rows in one list and tints only warning and danger", async () => {
    await renderWithProviders(
      <DecisionList aria-label="Alerts">
        <DecisionRow tone="danger" count="1" title="Variances" />
        <DecisionRow tone="warning" count="11" title="Unperformed" />
        <DecisionRow tone="info" count="57" title="Not invoiced" />
      </DecisionList>,
    );
    expect(screen.getByRole("list", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("1").className).toContain("text-danger-fg");
    expect(screen.getByText("11").className).toContain("text-warning-fg");
    expect(screen.getByText("57").className).not.toMatch(/text-(info|danger|warning)/);
  });
});
