import { describe, expect, it } from "vitest";

import {
  FAILURES_BEFORE_UNREACHABLE,
  INITIAL_CONNECTION,
  afterProbe,
  afterRestoredNotice,
  probeIntervalMs,
  type ConnectionModel,
} from "./connection";

const run = (start: ConnectionModel, probes: boolean[]) => probes.reduce(afterProbe, start);

describe("connection state", () => {
  it("one failed probe is not an outage", () => {
    expect(run(INITIAL_CONNECTION, [false]).state).toBe("connected");
    expect(run(INITIAL_CONNECTION, [false, true, false]).state).toBe("connected");
  });

  it("consecutive failures make the server unreachable", () => {
    const failing = Array.from({ length: FAILURES_BEFORE_UNREACHABLE }, () => false);
    expect(run(INITIAL_CONNECTION, failing).state).toBe("unreachable");
  });

  it("the first success after an outage is restored, then the notice clears to connected", () => {
    const down = run(INITIAL_CONNECTION, [false, false, false]);
    expect(down.state).toBe("unreachable");
    const up = afterProbe(down, true);
    expect(up).toEqual({ state: "restored", failures: 0 });
    expect(afterRestoredNotice(up).state).toBe("connected");
  });

  it("restored goes back to unreachable if the server drops again", () => {
    const restored: ConnectionModel = { state: "restored", failures: 0 };
    expect(run(restored, [false, false]).state).toBe("unreachable");
  });

  it("clearing the notice does nothing in other states", () => {
    expect(afterRestoredNotice(INITIAL_CONNECTION)).toBe(INITIAL_CONNECTION);
    const down: ConnectionModel = { state: "unreachable", failures: 4 };
    expect(afterRestoredNotice(down)).toBe(down);
  });

  it("probes faster while unreachable", () => {
    expect(probeIntervalMs("unreachable")).toBeLessThan(probeIntervalMs("connected"));
  });
});
