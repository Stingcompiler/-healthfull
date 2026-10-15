# Phase 1 findings (reconstructed)

The original review notes could not be saved at the time. This file is rebuilt from the saved
before-screenshots (docs/ui-review/phase1/before) and the `make lint-ui` baseline (142 hits:
heading-icon 64, equal-columns 44, icon-tile 17, kpi-per-number 8, stripe 4, gradient 3,
card-in-card 2). It is not the original text.

| Screen | Component | Finding | Impact | Treatment (phase 2) |
|---|---|---|---|---|
| dashboard | KpiCard x4 | Four equal cards, each with an icon tile; no figure leads | The most important number (confirmed collections) has the same weight as the rest | One group surface, hero figure, others a step down, no tiles |
| dashboard | KpiCard (375) | Amounts could wrap mid-number in a 2-column grid | Hard to read an amount | `nowrap` plus container-query sizing |
| dashboard | AlertCard x5 | Each alert is a full tinted card, even informational ones | Colour everywhere, nothing stands out | Divided rows in one surface; only warning/danger are coloured |
| dashboard | Department/collections charts (ar) | Axis labels of the department chart spilled over the neighbouring chart in full-page captures | Looked like a label collision | Department chart rebuilt as text rows + bars; shots now grow the viewport instead of using fullPage (the spill only occurred in beyond-viewport captures) |
| cashier | ServiceLineCard | Edge stripe repeats the status badge; one card per line, two columns of cards | Duplicated status, payer/patient amounts not comparable between lines | One table (md+) / rows (phone), aligned payer and patient columns, one badge |
| cashier | Totals | Totals in a separate list; approve in another footer | The amount to collect is not emphasised | One bar: to-collect largest, actions beside it |
| shared | EmptyState, PageHeader | Tinted circle / icon tile | Decoration without meaning | Removed |
| shared | card-surface | Soft shadow in light/warm, border only in dark | Inconsistent depth per theme | One hairline border, no shadow |
| kept | tabular numerals, bidi-safe money and names, pending transfers as a separate figure, skeletons at content size, StatusBadge, PatientCard, DataTable, F2/F4/F8 | Good as is | | Unchanged |
