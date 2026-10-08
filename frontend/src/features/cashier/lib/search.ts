/** Search params of the cashier desk: the visit being billed and the lookup text. */
export interface CashierSearch {
  visit?: number;
  q?: string;
}

export function parseCashierSearch(search: Record<string, unknown>): CashierSearch {
  const visit = Number(search.visit);
  const q = typeof search.q === "string" ? search.q.slice(0, 200) : undefined;
  return {
    ...(Number.isInteger(visit) && visit > 0 ? { visit } : {}),
    ...(q ? { q } : {}),
  };
}
