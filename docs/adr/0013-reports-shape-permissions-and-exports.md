# 0013: Reports: one shape, one code per area, documents reconciled with the ledger

Date: 2026-10-10. Status: accepted.

## Context
FEATURES 4.5 and 12.1-12.11 ask for fourteen reports and a manager dashboard, every report
exportable to Excel and PDF, with filters, permissions, and figures that never count pending
transfers or payer shares as collected (invariant 7, FEATURES 6.4). Phase 0 registered seven
broad report codes (`reports.view`, `reports.dashboard`, `reports.financial`,
`reports.operational`, `reports.stock`, `reports.lab`, `reports.export`) that nothing used.

## Decision
- **One shape for every report.** A report is filters in, metrics and sections of typed rows
  out (`apps/reports/kit.py`); a column has a kind (`money`, `int`, `days`, `minutes`,
  `percent`, `date`, `datetime`, `text`, `code`, `name`). One serializer, one Excel writer,
  one viewer, one print view serve all fourteen. Money is a `Decimal` (string in JSON).
- **Labels come with the data.** Report, section, column and metric titles are kept in
  Arabic and English in `apps/reports/labels.py` and sent with each report, like `name_ar` /
  `name_en` on rows, so the screen and the Excel file use the same words and a new column
  needs no frontend change. The screens' own words (filters, buttons, the catalog, empty
  states, the dashboard) are i18next keys as everywhere else. A test checks every label
  exists in both languages; a frontend test checks the catalog against the backend registry.
- **One code per area.** `reports.view_finance` (revenue, shift variances, pending transfers,
  discounts/cancellations/refunds, payer receivables), `reports.view_exceptions` (requested
  not invoiced, paid not performed, performed by authorization), `reports.view_stock`,
  `reports.view_visits`, `reports.view_lab` (lab supervisor too) and
  `reports.view_dashboard`. Defaults: manager, accountant and admin read money and exception
  reports, and the cashier supervisor too (who confirms transfers and reviews shifts); the
  pharmacist reads stock; doctors, cashiers, receptionists and nurses hold no report code.
  Each report has two endpoints (JSON and `.xlsx`) behind its single code: an export shows the
  same rows as the screen, so `reports.export` and the unused Phase 0 codes are removed.
- **What counts as what.** Revenue is what approved invoices froze (gross, discount, shares)
  less what approved credit notes took back, by approval day; it equals REVENUE − DISCOUNT.
  Collections are patient payments by the day they were taken, at their current
  verification: cash and confirmed transfers are collected, pending transfers are a figure
  of their own, rejected ones and spent patient credit are neither; a transfer confirmed or
  rejected later moves between those figures on its original day, and the reversal row of a
  late rejection is never counted again. Shift variances are the frozen close values.
  Department filters narrow billed revenue only (payments are not per department), so the
  collection figures are left out when a department is chosen. Tests compare every money
  report with `ledger.services` balances and postings.
- **Snapshots versus periods.** Requested-not-invoiced, paid-not-performed, pending transfers,
  stock valuation and expiry describe now (no date filter: an old open line must never fall
  out of a default period); revenue, shifts, adjustments, authorizations, stock movement and
  variance, visits and lab turnaround cover a period (at most 366 days,
  `REPORT_RANGE_TOO_LONG`). Payer receivables take an "as of" day.
- **Reuse.** Exception reports reuse `orders.services.report_*` (which gained an optional
  department), payer receivables and aging `claims.queries`, lab turnaround `lab.queries`,
  expiring batches `pharmacy.queries`. Detail sections stop at 2,000 rows and say so.
- **Excel and PDF.** openpyxl workbooks: a summary sheet and one sheet per section, numbers as
  numbers, Arabic sheets right to left; text starting with `=`, `+`, `-`, `@`, a tab or a
  carriage return is written as quoted text, and no cell is ever a formula. PDF is the
  browser's print of the A4 landscape print view (`/reports/<key>/print`): WeasyPrint needs
  system libraries (pango) the target machines do not have, and the app must not depend on
  them.

## Consequences
- Adding a report is a query function, a registry entry, labels and a catalog line; the
  screens, exports and permission sweep pick it up.
- A centre that wants the cashier supervisor out of the money reports removes the code in
  the permission matrix; nothing else changes.
- Payer receivables read per payer (the claims queries do), so their query count grows with
  the number of payers, not with lines.
