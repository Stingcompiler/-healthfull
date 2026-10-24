import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  INITIAL_CONNECTION,
  RESTORED_NOTICE_MS,
  afterProbe,
  afterRestoredNotice,
  probeIntervalMs,
  type ConnectionModel,
} from "@/lib/connection";
import { probeServer } from "@/lib/connection-probe";

import { ConnectionContext } from "./connection-context";

/**
 * Watches the server while the staff app is open: a health probe every 20 s (every 5 s while it
 * is unreachable), an immediate one when the browser reports online or the tab comes back to the
 * foreground, and an immediate failure when the browser reports offline. Nothing is probed while
 * the tab is hidden. Reports one of two problems (unreachable, restored); see lib/connection.ts.
 */
export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [model, setModel] = useState<ConnectionModel>(INITIAL_CONNECTION);
  const state = model.state;
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const probe = async () => {
      if (inFlight.current || document.visibilityState === "hidden") return;
      inFlight.current = true;
      const ok = await probeServer();
      inFlight.current = false;
      if (!cancelled) setModel((m) => afterProbe(m, ok));
    };
    const loop = () => {
      timer = window.setTimeout(() => {
        void probe().finally(() => {
          if (!cancelled) loop();
        });
      }, probeIntervalMs(state));
    };
    loop();

    const onOnline = () => {
      void probe();
    };
    const onOffline = () => {
      // The browser itself says the link is down, so there is nothing to wait for.
      setModel((m) => afterProbe(afterProbe(m, false), false));
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void probe();
    };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [state]);

  useEffect(() => {
    if (state !== "restored") return undefined;
    const id = window.setTimeout(() => {
      setModel(afterRestoredNotice);
    }, RESTORED_NOTICE_MS);
    return () => {
      window.clearTimeout(id);
    };
  }, [state]);

  return <ConnectionContext value={state}>{children}</ConnectionContext>;
}
