import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MoneyText } from "@/components/MoneyText";
import { renderWithProviders } from "@/test/render";

import { KpiCard, KpiGroup } from "./KpiCard";

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

  it("renders no icon tile and keeps the figure on one line", async () => {
    await renderWithProviders(<KpiCard label="Visits" value="3" icon={<svg data-testid="tile-icon" />} />);
    expect(screen.queryByTestId("tile-icon")).not.toBeInTheDocument();
    expect(screen.getByText("3").className).toContain("whitespace-nowrap");
  });

  it("colours the figure only for decision tones", async () => {
    await renderWithProviders(
      <>
        <KpiCard label="Plain" value="1" tone="success" />
        <KpiCard label="Pending" value="2" tone="warning" />
      </>,
    );
    expect(screen.getByText("1").className).not.toContain("text-success");
    expect(screen.getByText("2").className).toContain("text-warning-fg");
  });

  it("marks the hero figure and lets bare cards share one group surface", async () => {
    await renderWithProviders(
      <KpiGroup aria-label="Figures">
        <KpiCard bare hero label="Collected" value="9" />
        <KpiCard bare label="Queue" value="2" />
      </KpiGroup>,
    );
    const group = screen.getByLabelText("Figures");
    expect(group.querySelectorAll("[data-slot='kpi-card']")).toHaveLength(2);
    expect(group.querySelectorAll("[data-slot='kpi-card'].card-surface")).toHaveLength(0);
    expect(group.querySelectorAll("[data-hero]")).toHaveLength(1);
  });
});
