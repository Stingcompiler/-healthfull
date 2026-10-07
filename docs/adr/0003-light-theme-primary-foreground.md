# 0003: Dark text on the light theme's primary color

Date: 2026-10-06. Status: accepted (product sign-off welcome; changing it is a token edit).

## Context
ARCHITECTURE 5.1 fixes the light theme's `--primary` at `#0D9488` (Teal 600) and requires WCAG AA for
text. White text on `#0D9488` is 3.74:1, below the 4.5:1 AA threshold for normal text, so the usual
"white label on a teal button" fails in the default theme.

## Decision
Keep the brand value and change what sits on it:
- Light theme `--primary-fg` is a near-black teal `#0B1E1C` (4.61:1 on `#0D9488`).
- Links and primary-colored text on light surfaces use `--primary-strong` `#0F766E` (5.47:1 on white,
  5.23:1 on `--bg`).
- Dark (`#2DD4BF` with `#042F2E` text, 7.77:1) and warm (`#4F46E5` with white text, 6.29:1) keep their
  usual pairings.
- `frontend/src/design/contrast.test.ts` checks every text pair in all three themes for 4.5:1 and
  borders and the focus ring for 3:1, so a token edit that breaks AA fails `make check`.

## Alternatives rejected
- White text on `#0D9488`: fails AA.
- Darkening the light `--primary` to Teal 700: changes a value ARCHITECTURE pins and makes the
  light and warm themes look less distinct.

## Consequences
Primary buttons in the light theme have dark labels. If product prefers white labels, the only
compliant route is a darker light-theme primary, which needs an ARCHITECTURE 5.1 change.
