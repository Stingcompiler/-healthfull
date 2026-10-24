#!/usr/bin/env python3
"""WCAG 2.x contrast check of the design tokens (frontend/src/design/tokens/*.tokens.json).

The pairs live in frontend/src/design/tokens/contrast.json and are shared with the vitest
suite (src/design/contrast.test.ts). Exit code 1 on any failure.

    python3 scripts/check_contrast.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_tokens import THEMES, load_theme, resolved_hex, load_json  # noqa: E402

TOKENS_DIR = Path(__file__).resolve().parent.parent / "frontend" / "src" / "design" / "tokens"


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def failures() -> list[str]:
    pairs = load_json(TOKENS_DIR / "contrast.json")["pairs"]
    bad: list[str] = []
    for theme in THEMES:
        tokens = resolved_hex(load_theme(theme))
        for fg, bg, minimum in pairs:
            for name in (fg, bg):
                if name not in tokens:
                    bad.append(f"{theme}: --{name} is not defined")
            if fg not in tokens or bg not in tokens:
                continue
            got = ratio(tokens[fg], tokens[bg])
            if got < minimum:
                bad.append(f"{theme}: --{fg} {tokens[fg]} on --{bg} {tokens[bg]} = {got:.2f}:1 (needs {minimum}:1)")
    return bad


def main() -> int:
    bad = failures()
    for line in bad:
        print(f"contrast: {line}", file=sys.stderr)
    if bad:
        print(f"contrast: {len(bad)} failing pair(s)", file=sys.stderr)
        return 1
    print("contrast: every pair passes in every theme")
    return 0


if __name__ == "__main__":
    sys.exit(main())
