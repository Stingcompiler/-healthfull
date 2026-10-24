/**
 * Density modes (Design Reference 2.2 section 5; tokens/density.tokens.json, D-0013).
 *
 * The reference makes density an app-wide user setting. Here each working area has a default
 * instead: the cashier and the pharmacy are keyboard-first, high-volume desks (compact); the
 * patient portal and the waiting-room display are read at a glance by people who are not trained
 * on the system (comfortable); everything else is the default mode. Components read the
 * --d-row / --d-pad / --d-gap / --d-card-pad / --d-font tokens and never the mode itself.
 */
export type Density = "compact" | "default" | "comfortable";

/** Route prefixes (staff app) that run compact. */
const COMPACT_AREAS = ["/cashier", "/pharmacy"] as const;

function inArea(pathname: string, area: string): boolean {
  return pathname === area || pathname.startsWith(`${area}/`);
}

/** The density of a staff-app route. The portal and the queue display set `comfortable` themselves. */
export function densityForPath(pathname: string): Density {
  return COMPACT_AREAS.some((area) => inArea(pathname, area)) ? "compact" : "default";
}

/** Value for the data-density attribute (the default mode is the :root tokens, so no attribute). */
export function densityAttribute(density: Density): Density | undefined {
  return density === "default" ? undefined : density;
}
