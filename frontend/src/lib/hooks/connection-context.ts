import { createContext, use } from "react";

import type { ConnectionState } from "@/lib/connection";

export const ConnectionContext = createContext<ConnectionState>("connected");

/** The current connection state ("connected" when no provider is mounted, e.g. in unit tests). */
export function useConnection(): ConnectionState {
  return use(ConnectionContext);
}
