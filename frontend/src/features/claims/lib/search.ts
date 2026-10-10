/** Search params of the claim screens: the payer a list or the batch builder starts with. */
export interface ClaimsSearch {
  payer?: number;
}

export function parseClaimsSearch(search: Record<string, unknown>): ClaimsSearch {
  const payer = Number(search.payer);
  return Number.isInteger(payer) && payer > 0 ? { payer } : {};
}
