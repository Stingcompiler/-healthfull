/**
 * Connection state of the browser to the hospital server (Design Reference 2.2 section 8, reduced
 * to the two states a LAN app needs; docs/DECISIONS.md D-0014). There is no offline queue, so the
 * reference's synced / pending / syncing / failed / stale states do not exist here: work is either
 * saved on the server or it is not.
 *
 *   connected    normal; nothing is shown
 *   unreachable  the server did not answer (the user's own network, the server, or the database)
 *   restored     it answers again after being unreachable; shown briefly, then back to connected
 */
export type ConnectionState = "connected" | "unreachable" | "restored";

/** Consecutive failed probes before the banner appears (a single dropped request is not an outage). */
export const FAILURES_BEFORE_UNREACHABLE = 2;

export interface ConnectionModel {
  state: ConnectionState;
  failures: number;
}

export const INITIAL_CONNECTION: ConnectionModel = { state: "connected", failures: 0 };

/** The model after one probe. `ok` is whether the server answered with success. */
export function afterProbe(model: ConnectionModel, ok: boolean): ConnectionModel {
  if (ok) {
    if (model.state === "unreachable") return { state: "restored", failures: 0 };
    // restored stays restored until the timer clears it; connected stays connected.
    return { state: model.state, failures: 0 };
  }
  const failures = model.failures + 1;
  if (model.state === "unreachable" || failures >= FAILURES_BEFORE_UNREACHABLE) {
    return { state: "unreachable", failures };
  }
  // A failure while the "restored" notice is up counts toward a new outage but keeps the notice.
  return { state: model.state, failures };
}

/** The model after the "restored" notice has been shown long enough. */
export function afterRestoredNotice(model: ConnectionModel): ConnectionModel {
  return model.state === "restored" ? { state: "connected", failures: model.failures } : model;
}

/** Seconds between probes: faster while the server is unreachable so the notice clears quickly. */
export function probeIntervalMs(state: ConnectionState): number {
  return state === "unreachable" ? 5_000 : 20_000;
}

/** How long the "restored" notice stays. */
export const RESTORED_NOTICE_MS = 6_000;
