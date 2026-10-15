#!/usr/bin/env node
/*
 * lint-ui: finds the known applications of the forbidden card patterns
 * (docs/ui-profile.md, Part A section 3 of the UI review guide) in frontend/src.
 *
 *   node scripts/lint-ui.mjs            print every hit, exit 1 when there is any, silent exit 0 otherwise
 *   node scripts/lint-ui.mjs --summary  also print counts per family
 *   LINT_UI_REPORT_ONLY=1 ...           always exit 0 (phase 1: a report, not a gate)
 *
 * A hit is waived by `ui-allow: <reason>` on the same line or the line above it, e.g.
 *   {/* ui-allow: active navigation indicator *\/}
 * Functional exceptions (progress indicators, focus rings, field borders, the active nav marker,
 * quote rules, global alert bars) are not matched on purpose; document any other in the report.
 *
 * This is a text scan: it finds specific patterns, can be bypassed, and does not judge elegance.
 * It is cheap and stops accidental regressions; it does not replace looking at screenshots.
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(root, "frontend", "src");
const args = new Set(process.argv.slice(2));
const reportOnly = process.env.LINT_UI_REPORT_ONLY === "1";

const TINT = String.raw`bg-(primary-soft|primary\/\d+|(success|warning|danger|info)-bg|state-\w+-bg|accent|subtle)\b|\btone(Classes)?\[|\btoneClass`;

/** One-line rules: [family, regex, message]. */
const LINE_RULES = [
  ["stripe", /\bborder-(s|e|l|r|t)-(2|4|8)\b/, "thick one-sided border (colored stripe)"],
  ["stripe", /\bborder-(s|e|l|r|t)-\[\d+px\]/, "arbitrary one-sided border width (stripe)"],
  [
    "stripe",
    /\babsolute\b[^"'`]*\binset-y-0\b[^"'`]*\b(start|end|left|right)-0\b[^"'`]*\bw-(px|0\.5|1|1\.5|2)\b/,
    "absolutely positioned thin side bar",
  ],
  [
    "stripe",
    /\babsolute\b[^"'`]*\binset-x-0\b[^"'`]*\b(top|bottom)-0\b[^"'`]*\bh-(px|0\.5|1|1\.5|2)\b/,
    "absolutely positioned thin top/bottom bar",
  ],
  ["stripe", /\b(before|after):absolute\b[^"'`]*\b(w|h)-(px|0\.5|1|1\.5|2)\b/, "pseudo-element bar"],
  ["stripe", /shadow-\[inset_[^\]]*\b[2-6]px/, "inset shadow used as a stripe"],
  ["gradient", /\bbg-(gradient|linear|radial|conic)-|\b(from|via|to)-(primary|success|warning|danger|info|accent|surface)\b/, "gradient utility"],
  ["gradient", /\b(linear|radial|conic)-gradient\(/, "CSS gradient"],
  ["gradient", /\bbg-clip-text\b/, "gradient text"],
  ["animation", /\banimate-(pulse|bounce|ping)\b/, "continuous animation on a static element"],
  ["animation", /\banimation(-iteration-count)?:\s*[^;]*infinite|\binfinite\b.*\banimate-/, "infinite animation"],
  ["equal-columns", /\bgrid-cols-(3|4)\b/, "equal 3-4 column grid"],
];

/** Which `animate-pulse` uses are loading placeholders (a progress indicator, an allowed exception). */
const ANIMATION_EXEMPT_FILES = [/components\/ui\/skeleton\.tsx$/];

const hits = [];
const waived = [];

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "test") continue;
      out.push(...walk(full));
    } else if (/\.(tsx|jsx|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      if (entry.name === "tokens.css") continue; // the one place raw color values (and shadows) live
      out.push(full);
    }
  }
  return out;
}

function indentOf(line) {
  return line.length - line.trimStart().length;
}

function report(family, file, lineNo, message, text) {
  const rel = path.relative(root, file);
  hits.push({ family, rel, lineNo, message, text: text.trim() });
}

function isWaived(lines, i) {
  return /ui-allow:/.test(lines[i]) || (i > 0 && /ui-allow:/.test(lines[i - 1]));
}

const CARD_OPEN = /card-surface|<Card\b|<KpiCard\b|<PatientCard\b|<ServiceLineCard\b|<AlertCard\b/;
const CARD_NESTED = /card-surface|<Card\b|<KpiCard\b|<PatientCard\b|<ServiceLineCard\b|<EmptyState\b(?![^>]*\bbare\b)/;

for (const file of walk(SRC)) {
  const lines = readFileSync(file, "utf8").split("\n");
  const isTsx = file.endsWith(".tsx");

  lines.forEach((line, i) => {
    if (isWaived(lines, i)) {
      if (LINE_RULES.some(([, re]) => re.test(line))) waived.push(`${path.relative(root, file)}:${i + 1}`);
      return;
    }
    for (const [family, re, message] of LINE_RULES) {
      if (!re.test(line)) continue;
      if (family === "animation" && ANIMATION_EXEMPT_FILES.some((x) => x.test(file))) continue;
      report(family, file, i + 1, message, line);
    }
  });

  if (!isTsx) continue;

  // Icon in a tinted tile: a small fixed-size, centered, rounded box with a tinted fill, in a
  // window of 4 lines (class lists are often split by prettier or by a tone map).
  lines.forEach((line, i) => {
    if (!/items-center/.test(line) || !/justify-center/.test(line)) {
      // The size/shape may be on the previous or next line of a split class list.
      if (!/\bsize-(8|9|10|11|12|14|16)\b/.test(line)) return;
    }
    const win = lines.slice(Math.max(0, i - 1), i + 3).join(" ");
    const sized = /\bsize-(8|9|10|11|12|14|16)\b|\bh-(8|9|10|11|12|14|16) w-(8|9|10|11|12|14|16)\b/.test(win);
    const shaped = /\brounded-(full|control|card|lg|md|xl)\b/.test(win);
    const centered = /items-center/.test(win) && /justify-center/.test(win);
    const tinted = new RegExp(TINT).test(win);
    if (sized && shaped && centered && tinted && /items-center/.test(line) && !isWaived(lines, i)) {
      report("icon-tile", file, i + 1, "icon inside a tinted circle/square", line);
    }
  });

  // KPI card per number: four or more KpiCard in one file.
  const kpi = lines.map((l, i) => (/<KpiCard\b/.test(l) ? i : -1)).filter((i) => i >= 0);
  if (kpi.length >= 4 && !kpi.some((i) => isWaived(lines, i))) {
    report("kpi-per-number", file, kpi[0] + 1, `${kpi.length} KpiCard in one file (a stat card per number)`, lines[kpi[0]]);
  }

  // Icon on every heading: an icon element opened right after a heading/title tag, or an icon prop
  // on a PageHeader.
  lines.forEach((line, i) => {
    if (isWaived(lines, i)) return;
    if (/<(h[1-6]|CardTitle|DialogTitle|SheetTitle)\b[^>]*>\s*<[A-Z][A-Za-z0-9]*\b[^>]*(aria-hidden|size-\d|className)/.test(line)) {
      report("heading-icon", file, i + 1, "icon placed in a heading", line);
    }
    if (/<PageHeader\b/.test(line)) {
      const tag = lines.slice(i, i + 12).join(" ").split(/\/>|<\/PageHeader>/)[0];
      if (/\bicon=\{/.test(tag)) report("heading-icon", file, i + 1, "icon prop on a page title", line);
    }
  });

  // Card inside card: a card-like element nested (by indentation) in another card-like element.
  lines.forEach((line, i) => {
    if (!CARD_OPEN.test(line) || isWaived(lines, i)) return;
    // Only treat as a container when it is written as an opening tag or a className on one.
    let base = indentOf(line);
    if (!line.trimStart().startsWith("<")) {
      // class list on an attribute line: find the tag start above
      let j = i - 1;
      while (j >= 0 && (lines[j].trimStart().startsWith("<") ? false : true) && i - j < 8) j--;
      if (j < 0 || !lines[j].trimStart().startsWith("<")) return;
      base = indentOf(lines[j]);
    }
    if (/\/>\s*$/.test(line) && line.trimStart().startsWith("<")) return; // self-closed on one line
    for (let k = i + 1; k < lines.length; k++) {
      const l = lines[k];
      if (l.trim() === "") continue;
      if (indentOf(l) <= base) break;
      if (CARD_NESTED.test(l) && l.trimStart().startsWith("<") && !isWaived(lines, k)) {
        report("card-in-card", file, k + 1, `card-like element nested in the card opened at line ${i + 1}`, l);
        break;
      }
    }
  });
}

const seen = new Set();
const unique = hits.filter((h) => {
  const key = `${h.family}|${h.rel}|${h.lineNo}`;
  if (seen.has(key)) return false;
  seen.add(key);
  return true;
});
unique.sort((a, b) => a.rel.localeCompare(b.rel) || a.lineNo - b.lineNo);

for (const h of unique) {
  console.log(`${h.rel}:${h.lineNo}: [${h.family}] ${h.message}\n    ${h.text.slice(0, 160)}`);
}

if (args.has("--summary") && unique.length > 0) {
  const byFamily = {};
  for (const h of unique) byFamily[h.family] = (byFamily[h.family] ?? 0) + 1;
  console.log("\nlint-ui summary");
  for (const [family, n] of Object.entries(byFamily).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${family.padEnd(16)} ${n}`);
  }
  console.log(`  ${"total".padEnd(16)} ${unique.length}  (waived with ui-allow: ${waived.length})`);
}

process.exit(unique.length > 0 && !reportOnly ? 1 : 0);
