import type { WorklistFilter } from "../types";

export const WORKLIST_FILTERS: readonly WorklistFilter[] = [
  "open",
  "to_collect",
  "to_receive",
  "to_enter",
  "to_approve",
  "done",
];

/** Search params of the work list: the stage filter, the search text and the page. */
export interface WorklistSearch {
  status?: WorklistFilter;
  q?: string;
  page?: number;
}

export function parseWorklistSearch(search: Record<string, unknown>): WorklistSearch {
  const status = WORKLIST_FILTERS.find((f) => f === search.status);
  const q = typeof search.q === "string" ? search.q.slice(0, 200) : undefined;
  const page = Number(search.page);
  return {
    ...(status && status !== "open" ? { status } : {}),
    ...(q ? { q } : {}),
    ...(Number.isInteger(page) && page > 1 ? { page } : {}),
  };
}

/** Search params of the result printout: the version to print (default the current one). */
export interface PrintSearch {
  version?: number;
  lang?: "ar" | "en";
}

export function parsePrintSearch(search: Record<string, unknown>): PrintSearch {
  const version = Number(search.version);
  const lang = search.lang === "ar" || search.lang === "en" ? search.lang : undefined;
  return {
    ...(Number.isInteger(version) && version > 0 ? { version } : {}),
    ...(lang ? { lang } : {}),
  };
}

/** Search params of the label page: the test it was opened from (for the way back). */
export interface LabelSearch {
  line?: number;
}

export function parseLabelSearch(search: Record<string, unknown>): LabelSearch {
  const line = Number(search.line);
  return Number.isInteger(line) && line > 0 ? { line } : {};
}
