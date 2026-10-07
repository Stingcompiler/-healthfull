import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MoneyText } from "@/components/MoneyText";
import { renderWithProviders } from "@/test/render";

import { KpiCard } from "./KpiCard";

describe("KpiCard", () => {
  it("reads a ReactNode trend value after the direction word", async () => {
    await renderWithProviders(
      <KpiCard label="Collected" value="0" trend={{ direction: "up", value: <MoneyText value="1500.00" /> }} />,
    );
    const card = screen.getByRole("heading", { name: "Collected" }).closest("section");
    expect(card).not.toBeNull();
    // Nothing in the trend is hidden from screen readers any more.
    expect(card?.querySelector("[aria-hidden='true'] [data-slot='money']")).toBeNull();
    const trend = screen.getByText("Up").parentElement;
    expect(trend?.textContent).toMatch(/^Up\s.*1,500\.00/);
  });

  it("uses an h2 by default and a configurable level", async () => {
    const { rerender } = await renderWithProviders(<KpiCard label="Visits" value="3" />);
    expect(screen.getByRole("heading", { level: 2, name: "Visits" })).toBeInTheDocument();
    rerender(<KpiCard label="Visits" value="3" headingLevel="h4" />);
    expect(screen.getByRole("heading", { level: 4, name: "Visits" })).toBeInTheDocument();
    rerender(<KpiCard label="Visits" value="3" headingLevel="p" />);
    expect(screen.queryByRole("heading", { name: "Visits" })).not.toBeInTheDocument();
  });
});
