import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

/**
 * What happened to the signed-in session (inspection F06), per query client:
 *
 * - `null`: nothing; the session is live (or nobody signed in yet);
 * - `expired`: an API call answered 401 while `userId` was signed in. The page stays mounted
 *   (hidden) with whatever the user was typing, and a sign-in dialog asks for the password;
 * - `switching`: someone else signed in from that dialog. The page is unmounted first, so the
 *   previous user's draft is dropped from memory without being shown, then the app starts over.
 */
export type SessionState = { kind: "expired"; userId: number; username: string } | { kind: "switching" } | null;

interface Store {
  state: SessionState;
  listeners: Set<() => void>;
}

const stores = new WeakMap<QueryClient, Store>();

function storeOf(client: QueryClient): Store {
  let store = stores.get(client);
  if (!store) {
    store = { state: null, listeners: new Set() };
    stores.set(client, store);
  }
  return store;
}

export function getSessionState(client: QueryClient): SessionState {
  return storeOf(client).state;
}

export function setSessionState(client: QueryClient, state: SessionState): void {
  const store = storeOf(client);
  if (store.state === state) return;
  store.state = state;
  for (const listener of store.listeners) listener();
}

/** Marks the session of `user` as expired (once; later 401s change nothing). */
export function markSessionExpired(client: QueryClient, user: { id: number; username: string }): void {
  if (getSessionState(client) !== null) return;
  setSessionState(client, { kind: "expired", userId: user.id, username: user.username });
}

export function useSessionState(): SessionState {
  const client = useQueryClient();
  const store = storeOf(client);
  return useSyncExternalStore(
    (listener) => {
      store.listeners.add(listener);
      return () => store.listeners.delete(listener);
    },
    () => store.state,
  );
}
