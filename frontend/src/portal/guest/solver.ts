/**
 * Runs the proof-of-work search (ADR 0029 F) without blocking the page: in a Web Worker when
 * the browser has them, else on the main thread in slices that yield between them. Either way
 * the caller gets progress reports and can stop the search.
 */
import { SLICE, solveRange } from "./pow";

export interface SolveRequest {
  token: string;
  bits: number;
}

export type SolverMessage = { kind: "progress"; tried: number } | { kind: "done"; nonce: string; tried: number };

export interface SolveOptions {
  onProgress?: (tried: number) => void;
  signal?: AbortSignal;
}

function aborted(): DOMException {
  return new DOMException("The search was stopped", "AbortError");
}

function inWorker(request: SolveRequest, options: SolveOptions): Promise<string> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./pow.worker.ts", import.meta.url), { type: "module" });
    const stop = () => {
      worker.terminate();
      reject(aborted());
    };
    options.signal?.addEventListener("abort", stop, { once: true });
    worker.onmessage = (event: MessageEvent<SolverMessage>) => {
      const message = event.data;
      options.onProgress?.(message.tried);
      if (message.kind === "done") {
        options.signal?.removeEventListener("abort", stop);
        worker.terminate();
        resolve(message.nonce);
      }
    };
    worker.onerror = (event) => {
      event.preventDefault();
      options.signal?.removeEventListener("abort", stop);
      worker.terminate();
      // A browser that cannot start the worker still gets the form through.
      onMainThread(request, options).then(resolve, reject);
    };
    worker.postMessage(request);
  });
}

/** Main-thread fallback: one slice, then a yield to the event loop, so input stays responsive. */
export async function onMainThread(request: SolveRequest, options: SolveOptions = {}): Promise<string> {
  for (let start = 0; ; start += SLICE) {
    if (options.signal?.aborted) throw aborted();
    const nonce = solveRange(request.token, request.bits, start, SLICE);
    if (nonce !== null) {
      options.onProgress?.(Number(nonce) + 1);
      return nonce;
    }
    options.onProgress?.(start + SLICE);
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
}

/** Finds the nonce for a challenge. Rejects with an `AbortError` when `signal` aborts. */
export function solveChallenge(request: SolveRequest, options: SolveOptions = {}): Promise<string> {
  if (options.signal?.aborted) return Promise.reject(aborted());
  if (typeof Worker === "undefined") return onMainThread(request, options);
  try {
    return inWorker(request, options);
  } catch {
    return onMainThread(request, options);
  }
}
