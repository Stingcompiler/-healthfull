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

  it("pages on the server with one pager and the true total", async () => {
    setViewportWidth(1280);
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    await renderWithProviders(
      <DataTable
        caption="Lines"
        columns={columns}
        data={rows.slice(5, 10)}
        serverPagination={{ page: 2, pageSize: 5, count: 12, onPageChange }}
      />,
    );
    // The loaded page is page 2 of 3 on the server, not "1 of 1" of what was loaded.
    expect(screen.getByText("6–10 of 12")).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(6);
    expect(screen.queryByText("Rows per page")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPageChange).toHaveBeenCalledWith(3);
    await user.click(screen.getByRole("button", { name: "Previous page" }));
    expect(onPageChange).toHaveBeenCalledWith(1);
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

  it("opens a row from the keyboard in table mode", async () => {
    setViewportWidth(1280);
    const onRowClick = vi.fn();
    const user = userEvent.setup();
    await renderWithProviders(
      <DataTable
        caption="Lines"
        columns={columns}
        data={rows.slice(0, 2)}
        onRowClick={onRowClick}
        rowLabel={(r) => `Open ${r.name}`}
      />,
    );
    const open = screen.getByRole("button", { name: "Open Patient 01" });
    open.focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
    await user.keyboard(" ");
    expect(onRowClick).toHaveBeenCalledTimes(2);
    // Tab reaches the next row's open control.
    await user.tab();
    expect(screen.getByRole("button", { name: "Open Patient 02" })).toHaveFocus();
    // A mouse click anywhere on the row still opens it, once.
    await user.click(screen.getByText("200.00"));
    expect(onRowClick).toHaveBeenLastCalledWith(rows[1]);
    expect(onRowClick).toHaveBeenCalledTimes(3);
  });

  it("opens a row in card mode too (default card), by click and keyboard", async () => {
    setViewportWidth(375);
    const onRowClick = vi.fn();
    const onSelect = vi.fn();
    const user = userEvent.setup();
    await renderWithProviders(
      <DataTable
        caption="Lines"
        columns={columns}
        data={rows.slice(0, 1)}
        onRowClick={onRowClick}
        rowLabel={(r) => `Open ${r.name}`}
        rowActions={() => [{ label: "View", onSelect }]}
      />,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const open = screen.getByRole("button", { name: "Open Patient 01" });
    await user.click(open);
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
    open.focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledTimes(2);
    // The actions menu stays usable above the open overlay and does not open the row.
    await user.click(screen.getByRole("button", { name: "Row actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "View" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onRowClick).toHaveBeenCalledTimes(2);
  });

  it("passes the open callback to custom card renderers", async () => {
    setViewportWidth(375);
    const onRowClick = vi.fn();
    const user = userEvent.setup();
    await renderWithProviders(
      <DataTable
        caption="Lines"
        columns={columns}
        data={rows.slice(0, 1)}
        onRowClick={onRowClick}
        renderCard={(row, { open }) => (
          <button type="button" onClick={open}>
            {row.name}
          </button>
        )}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Patient 01" }));
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });

  it("switches to cards when its container is too narrow for the columns", async () => {
    setViewportWidth(1280);
    const observers: { cb: ResizeObserverCallback; el: Element }[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        cb: ResizeObserverCallback;
        constructor(cb: ResizeObserverCallback) {
          this.cb = cb;
        }
        observe(el: Element) {
          observers.push({ cb: this.cb, el });
        }
        unobserve() {
          return undefined;
        }
        disconnect() {
          return undefined;
        }
      },
    );
    const resize = (width: number) => {
      act(() => {
        for (const { cb, el } of observers) {
          cb([{ target: el, contentRect: { width } } as unknown as ResizeObserverEntry], {} as ResizeObserver);
        }
      });
    };
    try {
      const wide: ColumnDef<Row>[] = Array.from({ length: 7 }, (_, i) => ({
        id: `c${String(i)}`,
        accessorFn: (r: Row) => r.name,
        header: `Col ${String(i)}`,
        meta: { label: `Col ${String(i)}` },
      }));
      await renderWithProviders(<DataTable caption="Lines" columns={wide} data={rows} />);
      resize(960);
      expect(screen.getByRole("table")).toBeInTheDocument();
      // Beside the tablet rail: ~648px is not enough for seven columns.
      resize(648);
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.getByRole("list", { name: "Lines" })).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
