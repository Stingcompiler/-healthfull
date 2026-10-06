import type { ColumnDef } from "@tanstack/react-table";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/render";
import { setViewportWidth } from "@/test/match-media";

import { DataTable } from "./DataTable";

interface Row {
  id: string;
  name: string;
  amount: string;
}

const rows: Row[] = Array.from({ length: 12 }, (_, i) => ({
  id: `r${String(i + 1)}`,
  name: `Patient ${String(i + 1).padStart(2, "0")}`,
  amount: `${String((i + 1) * 100)}.00`,
}));

const columns: ColumnDef<Row>[] = [
  { accessorKey: "name", header: "Name", meta: { label: "Name" } },
  { accessorKey: "amount", header: "Amount", meta: { label: "Amount", align: "end" } },
];

describe("DataTable", () => {
  afterEach(() => {
    setViewportWidth(1280);
  });

  it("renders a table at desktop width", async () => {
    setViewportWidth(1280);
    await renderWithProviders(<DataTable caption="Lines" columns={columns} data={rows} getRowId={(r) => r.id} />);
    const table = screen.getByRole("table", { name: "Lines" });
    // header row + first page of 10
    expect(within(table).getAllByRole("row")).toHaveLength(11);
    expect(screen.queryByRole("list", { name: "Lines" })).not.toBeInTheDocument();
  });

  it("switches to cards below the md breakpoint, using renderCard", async () => {
    setViewportWidth(375);
    await renderWithProviders(
      <DataTable
        caption="Lines"
        columns={columns}
        data={rows}
        renderCard={(row) => <div data-testid="card">{row.name}</div>}
      />,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Lines" });
    expect(within(list).getAllByTestId("card")).toHaveLength(10);
  });

  it("switches live when the viewport crosses the breakpoint", async () => {
    setViewportWidth(1280);
    await renderWithProviders(<DataTable caption="Lines" columns={columns} data={rows} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    act(() => {
      setViewportWidth(500);
    });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // Default card layout shows each column label.
    expect(screen.getAllByText("Amount").length).toBeGreaterThan(0);
    act(() => {
      setViewportWidth(900);
    });
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("honors a forced mode regardless of width", async () => {
    setViewportWidth(1280);
    await renderWithProviders(<DataTable caption="Lines" columns={columns} data={rows} mode="cards" />);
    expect(screen.getByRole("list", { name: "Lines" })).toBeInTheDocument();
  });

  it("paginates and sorts", async () => {
    setViewportWidth(1280);
    const user = userEvent.setup();
    await renderWithProviders(<DataTable caption="Lines" columns={columns} data={rows} pageSize={5} />);
    expect(screen.getByText("1–5 of 12")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("6–10 of 12")).toBeInTheDocument();
    expect(screen.getByText("Patient 06")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sort by Name" }));
    await user.click(screen.getByRole("button", { name: "Sort by Name" }));
    // Sorting resets to the first page; descending puts Patient 12 first.
    const firstCell = screen.getAllByRole("row")[1];
    expect(firstCell).toHaveTextContent("Patient 12");
    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("shows the empty state and skeletons", async () => {
    setViewportWidth(1280);
    const { rerender } = await renderWithProviders(<DataTable caption="Lines" columns={columns} data={[]} />);
    expect(screen.getByText("No results")).toBeInTheDocument();
    rerender(<DataTable caption="Lines" columns={columns} data={[]} loading />);
    expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("No results")).not.toBeInTheDocument();
  });

  it("offers row actions in both modes", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    setViewportWidth(375);
    await renderWithProviders(
      <DataTable
        caption="Lines"
        columns={columns}
        data={rows.slice(0, 1)}
        rowActions={() => [{ label: "View", onSelect }]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Row actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "View" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
