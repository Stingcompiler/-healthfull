/**
 * Web Worker that solves the booking form's proof-of-work off the main thread (ADR 0029 F),
 * reporting how many nonces it tried after each slice. Bundled by Vite with the app; nothing
 * is loaded from outside.
 */
import { SLICE, solveRange } from "./pow";
import type { SolveRequest, SolverMessage } from "./solver";

interface WorkerScope {
  onmessage: ((event: MessageEvent<SolveRequest>) => void) | null;
  postMessage: (message: SolverMessage) => void;
}

const scope = self as unknown as WorkerScope;

scope.onmessage = (event) => {
  const { token, bits } = event.data;
  for (let start = 0; ; start += SLICE) {
    const nonce = solveRange(token, bits, start, SLICE);
    if (nonce !== null) {
      scope.postMessage({ kind: "done", nonce, tried: Number(nonce) + 1 });
      return;
    }
    scope.postMessage({ kind: "progress", tried: start + SLICE });
  }
};
