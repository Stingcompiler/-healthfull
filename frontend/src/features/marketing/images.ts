/**
 * The marketing page's screenshots: real screens of the demo system (synthetic data), resized
 * and encoded as WebP, two widths each. Vite hashes the files (immutable caching) and nothing
 * is fetched from outside.
 */
const urls = import.meta.glob<string>("../../assets/marketing/*.webp", {
  eager: true,
  query: "?url",
  import: "default",
});

function urlOf(name: string, width: number): string {
  const found = urls[`../../assets/marketing/${name}-${String(width)}.webp`];
  if (!found) throw new Error(`marketing image missing: ${name}-${String(width)}.webp`);
  return found;
}

export interface Shot {
  src: string;
  srcSet: string;
  /** Intrinsic size of `src`, reserved on the element so nothing shifts while it loads. */
  width: number;
  height: number;
}

/** Desktop screens are 16:10; the phone screens of the portal are 540x1169. */
export function shot(name: string, widths: readonly [number, number], height: number): Shot {
  const [small, large] = widths;
  return {
    src: urlOf(name, large),
    srcSet: `${urlOf(name, small)} ${String(small)}w, ${urlOf(name, large)} ${String(large)}w`,
    width: large,
    height,
  };
}

export const HERO_WIDTHS = [640, 1280] as const;
export const SCREEN_WIDTHS = [640, 1100] as const;
export const PHONE_WIDTHS = [360, 540] as const;
