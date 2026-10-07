/** Age in whole years and months at `on` (default today), from an ISO date. */
export interface Age {
  years: number;
  months: number;
}

export function ageFromBirthDate(birthDate: string, on: Date = new Date()): Age | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(birthDate);
  if (!match) return null;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  let months = (on.getFullYear() - y) * 12 + (on.getMonth() + 1 - m);
  if (on.getDate() < d) months -= 1;
  if (months < 0) return null;
  return { years: Math.floor(months / 12), months };
}
