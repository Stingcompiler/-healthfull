import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/render";

import { InvoiceLines, type InvoiceLineRow } from "./InvoiceLines";

const line = (over: Partial<InvoiceLineRow>): InvoiceLineRow => ({
  id: 1,
  name: "Consultation",
  quantity: 1,
  gross: "15000.00",
  discount: "0.00",
  payerShare: "10500.00",
  patientShare: "4500.00",
  status: "invoiced",
  ...over,
});

describe("InvoiceLines", () => {
  it("renders one row per line with the shares in their own cells and one status badge", async () => {
    await renderWithProviders(
      <InvoiceLines
        caption="Invoice lines"
        lines={[line({}), line({ id: 2, name: "ECG", status: "paid", needsDecision: true })]}
      />,
    );
    const table = screen.getByRole("table", { name: "Invoice lines" });
    const rows = within(table).getAllByTestId("invoice-line");
    expect(rows).toHaveLength(2);
    const [first, second] = rows as [HTMLElement, HTMLElement];
    expect(within(first).getByTestId("payer-share")).toHaveTextContent("10,500.00");
    expect(within(first).getByTestId("patient-share")).toHaveTextContent("4,500.00");
    expect(first.querySelectorAll("[data-slot='status-badge']")).toHaveLength(1);
    // Only the line needing a decision is tinted; no edge stripe element exists.
    expect(first.className).not.toContain("bg-warning-bg");
    expect(second.className).toContain("bg-warning-bg");
    expect(first.querySelector(".absolute")).toBeNull();
  });

  it("adds the discount and outstanding columns only when they apply", async () => {
    const { rerender } = await renderWithProviders(<InvoiceLines caption="Lines" lines={[line({})]} />);
    expect(screen.queryByRole("columnheader", { name: /Discount/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /Outstanding/ })).not.toBeInTheDocument();
    rerender(<InvoiceLines caption="Lines" lines={[line({ discount: "500.00", outstanding: "0.00" })]} />);
    expect(screen.getByRole("columnheader", { name: /Discount/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Outstanding/ })).toBeInTheDocument();
  });
});
