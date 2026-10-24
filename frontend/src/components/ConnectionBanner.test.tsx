import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { probeServer } from "@/lib/connection-probe";
import { ConnectionProvider } from "@/lib/hooks/use-server-connection";

import { ConnectionBanner } from "./ConnectionBanner";

vi.mock("@/lib/connection-probe", () => ({ probeServer: vi.fn(), HEALTH_PATH: "/api/ops/health" }));
const probe = vi.mocked(probeServer);

const tick = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe("ConnectionBanner", () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    probe.mockReset();
    await i18n.changeLanguage("en");
  });
  afterEach(async () => {
    vi.useRealTimers();
    await i18n.changeLanguage("ar");
  });

  it("shows nothing without a provider or while the server answers", async () => {
    const { container } = render(<ConnectionBanner />);
    expect(container).toBeEmptyDOMElement();
    probe.mockResolvedValue(true);
    render(
      <ConnectionProvider>
        <ConnectionBanner />
      </ConnectionProvider>,
    );
    await tick(60_000);
    expect(screen.queryByTestId("connection-banner")).toBeNull();
  });

  it("says the server is unreachable after two failed probes, then restored, then clears", async () => {
    probe.mockResolvedValue(false);
    render(
      <ConnectionProvider>
        <ConnectionBanner />
      </ConnectionProvider>,
    );
    await tick(20_000);
    expect(screen.queryByTestId("connection-banner")).toBeNull(); // one failure is not an outage
    await tick(20_000);
    const down = screen.getByRole("alert");
    expect(down).toHaveAttribute("data-state", "unreachable");
    expect(down).toHaveTextContent("Can't reach the server");

    probe.mockResolvedValue(true);
    await tick(5_000);
    const restored = screen.getByRole("status");
    expect(restored).toHaveAttribute("data-state", "restored");
    expect(restored).toHaveTextContent("Connection restored");

    await tick(6_000);
    expect(screen.queryByTestId("connection-banner")).toBeNull();
  });

  it("goes unreachable at once when the browser reports offline", async () => {
    probe.mockResolvedValue(true);
    render(
      <ConnectionProvider>
        <ConnectionBanner />
      </ConnectionProvider>,
    );
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveAttribute("data-state", "unreachable");
  });
});
