/**
 * Controllable window.matchMedia for jsdom (which has none).
 * Supports `(min-width: Npx)` and `(max-width: Npx)` queries against a
 * simulated viewport width, plus `prefers-color-scheme: dark` (setPrefersDark, default light).
 */
type Listener = (event: MediaQueryListEvent) => void;

let viewportWidth = 1280;
let prefersDark = false;
const lists = new Set<{ query: string; listeners: Set<Listener>; last: boolean }>();

function evaluate(query: string): boolean {
  if (/prefers-color-scheme:\s*dark/.test(query)) return prefersDark;
  let matches = true;
  let matchedAny = false;
  for (const m of query.matchAll(/\((min|max)-width:\s*(\d+(?:\.\d+)?)(px|rem|em)\)/g)) {
    matchedAny = true;
    const value = Number(m[2]) * (m[3] === "px" ? 1 : 16);
    matches &&= m[1] === "min" ? viewportWidth >= value : viewportWidth <= value;
  }
  if (!matchedAny) return false;
  return matches;
}

/** Simulated OS color scheme for `(prefers-color-scheme: dark)` queries. */
export function setPrefersDark(value: boolean): void {
  prefersDark = value;
  setViewportWidth(viewportWidth);
}

export function setViewportWidth(width: number): void {
  viewportWidth = width;
  for (const entry of lists) {
    const now = evaluate(entry.query);
    if (now !== entry.last) {
      entry.last = now;
      const event = { matches: now, media: entry.query } as MediaQueryListEvent;
      for (const l of entry.listeners) l(event);
    }
  }
}

export function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList => {
      const entry = { query, listeners: new Set<Listener>(), last: evaluate(query) };
      lists.add(entry);
      const mql = {
        get matches() {
          return evaluate(query);
        },
        media: query,
        onchange: null,
        addEventListener: (_type: string, l: Listener) => entry.listeners.add(l),
        removeEventListener: (_type: string, l: Listener) => entry.listeners.delete(l),
        addListener: (l: Listener) => entry.listeners.add(l),
        removeListener: (l: Listener) => entry.listeners.delete(l),
        dispatchEvent: () => false,
      };
      return mql as unknown as MediaQueryList;
    },
  });
}
