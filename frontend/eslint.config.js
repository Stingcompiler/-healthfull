// @ts-check
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

/*
 * UI guard rails from docs/ARCHITECTURE.md section 5:
 *  - logical direction utilities only (ms-/me-/ps-/pe-/start-/end-/text-start)
 *  - semantic color tokens only (no Tailwind palette classes, no hex colors)
 *  - every user-visible string through i18next
 * Raw colors are allowed only in src/design/tokens.css.
 */
const PHYSICAL_DIRECTION =
  "(^|[\\s:\"'`])-?(ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br|scroll-ml|scroll-mr|scroll-pl|scroll-pr|inset-l|inset-r)-|(^|[\\s:\"'`])(text-left|text-right|float-left|float-right|clear-left|clear-right|border-l|border-r)($|[\\s\"'`])";
const PALETTE_COLOR =
  "(^|[\\s:\"'`])(bg|text|border|ring|fill|stroke|from|via|to|outline|decoration|accent|caret|divide|placeholder|shadow|ring-offset)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|black|white)(-\\d{2,3})?([\\s/\"'`]|$)";
const HEX_COLOR = "#[0-9a-fA-F]{3,8}\\b|\\brgba?\\(|\\bhsla?\\(|\\boklch\\(";

const restrictedClassSyntax = [
  {
    selector: `Literal[value=/${PHYSICAL_DIRECTION}/]`,
    message: "Use logical direction utilities (ms-/me-/ps-/pe-/start-/end-/text-start/text-end), not left/right.",
  },
  {
    selector: `TemplateElement[value.raw=/${PHYSICAL_DIRECTION}/]`,
    message: "Use logical direction utilities (ms-/me-/ps-/pe-/start-/end-/text-start/text-end), not left/right.",
  },
  {
    selector: `Literal[value=/${PALETTE_COLOR}/]`,
    message: "Use semantic color tokens (bg-surface, text-fg, bg-primary, text-danger-fg...), not palette colors.",
  },
  {
    selector: `Literal[value=/${HEX_COLOR}/]`,
    message: "Raw colors belong in src/design/tokens.css only; use a semantic token.",
  },
  {
    selector: `TemplateElement[value.raw=/${HEX_COLOR}/]`,
    message: "Raw colors belong in src/design/tokens.css only; use a semantic token.",
  },
];

export default defineConfig([
  globalIgnores(["dist", "coverage", "node_modules", "src/lib/api/schema.d.ts", "openapi.json"]),

  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat["recommended-latest"],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": ["error", { fixStyle: "inline-type-imports" }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      "@typescript-eslint/no-confusing-void-expression": ["error", { ignoreArrowShorthand: true }],
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: { attributes: false } }],
      "react-refresh/only-export-components": ["error", { allowConstantExport: true }],
      "no-restricted-syntax": ["error", ...restrictedClassSyntax],
    },
  },

  // shadcn primitives export variants next to components.
  {
    files: ["src/components/ui/**/*.tsx", "src/components/form/**/*.tsx"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },

  // Route/registry modules export functions and objects, not components.
  {
    files: ["src/**/routes.tsx", "src/**/routes.ts", "src/app/router.ts", "src/lib/use-preferences.tsx"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },

  // No literal user-visible strings in app code (shadcn primitives excluded).
  {
    files: [
      "src/features/**/*.{ts,tsx}",
      "src/components/**/*.{ts,tsx}",
      "src/portal/**/*.{ts,tsx}",
      "src/app/**/*.{ts,tsx}",
    ],
    ignores: ["src/components/ui/**", "**/*.test.{ts,tsx}"],
    plugins: { i18next },
    rules: {
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          "jsx-attributes": {
            include: [
              "^(title|alt|placeholder|label|description|caption|confirmLabel|cancelLabel|heading|aria-label|aria-description|aria-placeholder|aria-roledescription|aria-valuetext)$",
            ],
            exclude: [],
          },
          words: {
            exclude: ["[0-9!-/:-@[-`{-~\\s]+", "[A-Z_-]+", "^\\s*[*•·|–—]\\s*$"],
          },
        },
      ],
    },
  },

  // Tests may use literal strings and non-null assertions freely.
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
      "no-restricted-syntax": "off",
    },
  },

  // Plain JS: config files and the first-paint boot script.
  {
    files: ["**/*.js"],
    extends: [js.configs.recommended, tseslint.configs.disableTypeChecked],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["public/**/*.js"],
    languageOptions: { sourceType: "script", globals: { ...globals.browser } },
  },
]);
