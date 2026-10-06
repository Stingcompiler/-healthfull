# Feature Specification

Date: 6 October 2026. Derived from [DECISION.md](DECISION.md), [FLOW.md](FLOW.md), [STACK.md](STACK.md).

Phase tags:

- **V1**: pilot release. Must exist before the paid pilot starts.
- **V1?**: included in V1 only if the pilot center needs it. Decided during discovery.
- **P2**: after the pilot proves the cycle.
- **Later**: not planned until a customer demonstrates the need.

Default policy throughout: **pay first, then perform.** Perform-first is an authorized exception.

---

## 0. Platform and cross-cutting

| # | Feature | Phase |
|---|---|---|
| 0.1 | Login with username and password, session timeout, forced password change on first login | V1 |
| 0.2 | Roles: receptionist, doctor, cashier, cashier supervisor, pharmacist, lab technician, lab supervisor, nurse, accountant, manager, system admin | V1 |
| 0.3 | Permission matrix per role per action, editable by admin, with safe defaults | V1 |
| 0.4 | Audit trail on every write: who, when, before, after, reason where required. Postgres-side, cannot be bypassed | V1 |
| 0.5 | Arabic and English UI, per-user language, full RTL layout | V1 |
| 0.6 | Responsive layout: desktop for reception, cashier, pharmacy, lab; tablet for doctor and nursing; phone for manager dashboard | V1 |
| 0.7 | Works entirely on the clinic LAN with no internet. No feature degrades when offline except cloud backup upload | V1 |
| 0.8 | Health endpoint and status page showing DB, disk, last backup, last restore test, pending cloud uploads | V1 |
| 0.9 | Global search: patient by name, phone, file number, in Arabic or English, tolerant of spelling variants | V1 |
| 0.10 | Print templates: invoice, receipt, prescription, lab result, claim export, shift report. A4 and thermal 80mm | V1 |
| 0.11 | Local device agent: thermal receipt printer, label printer | V1? |
| 0.12 | Local device agent: lab analyzer serial or file import | P2 |
| 0.13 | Notifications in-app (result ready, stock low, transfer pending beyond N days) | V1 |
| 0.14 | SMS to patient (result ready, appointment reminder) via local gateway | Later |

## 1. Patients and registration

| # | Feature | Phase |
|---|---|---|
| 1.1 | Patient file: file number (auto), name (Arabic and English), sex, date of birth or age, phone, address, national ID optional, emergency contact | V1 |
| 1.2 | Emergency registration with name and sex only, completed later with a flag | V1 |
| 1.3 | Duplicate warning on create: same phone, or similar name plus DOB | V1 |
| 1.4 | Merge duplicate files by supervisor, with full history retained and audit entry | V1 |
| 1.5 | Patient balance: unallocated payments and refunds kept as credit, visible at cashier | V1 |
| 1.6 | Coverage on file: payer, card number, validity, default copay rule | V1 |
| 1.7 | Patient photo capture | Later |
| 1.8 | Excel import of patients with preview, validation, and duplicate detection | V1 |

## 2. Visits and queue

| # | Feature | Phase |
|---|---|---|
| 2.1 | Create visit: department, doctor, coverage, visit type (new, follow-up, emergency) | V1 |
| 2.2 | Consultation fee line auto-created as requested; follow-up within N days free or discounted per center rule | V1 |
| 2.3 | Doctor queue: paid visits in order, with called/in-progress/done states and a waiting-room display | V1 |
| 2.4 | Visit timeline: every order, invoice, result, dispense, and refund linked to the visit | V1 |
| 2.5 | Appointments: book slot per doctor, reschedule, cancel, convert to visit on arrival | V1? |
| 2.6 | Queue token printing | V1? |
| 2.7 | Visit cancellation with reason and automatic refund flow if paid | V1 |

## 3. Clinical (doctor)

| # | Feature | Phase |
|---|---|---|
| 3.1 | Patient summary on open: allergies (prominent), chronic conditions, active medications, last 5 visits, latest results | V1 |
| 3.2 | Allergy and chronic condition registry, with alert on prescribing a flagged drug class | V1 |
| 3.3 | Clinical note: complaint, examination, diagnosis (free text plus ICD-10 lookup), plan | V1 |
| 3.4 | Vitals entry by nurse or doctor | V1 |
| 3.5 | Orders: lab tests from catalog, procedures from catalog, prescriptions from drug catalog with dose, frequency, duration, quantity auto-calculated | V1 |
| 3.6 | Order sets and favorites per doctor | V1 |
| 3.7 | Doctor sees order status (requested, paid, in progress, done) and approved results inline | V1 |
| 3.8 | Doctor never sees prices or billing screens, except an optional "estimated cost" toggle enabled by the center | V1 |
| 3.9 | Referral note to another department or external facility | V1 |
| 3.10 | Sick leave and medical report templates | P2 |
| 3.11 | Clinical templates per specialty | P2 |
| 3.12 | Growth charts, obstetric calculators, specialty tools | Later |

## 4. Service orders and state machine

| # | Feature | Phase |
|---|---|---|
| 4.1 | Every service line has a state: requested, invoiced, paid, performed, cancelled | V1 |
| 4.2 | Cancellation requires a reason from a configurable list plus free text | V1 |
| 4.3 | Work lists (lab, pharmacy, procedures) show only paid lines or lines with a perform-first authorization | V1 |
| 4.4 | Perform-first authorization screen: who, why, which lines, with supervisor role and audit | V1 |
| 4.5 | Reports: requested-not-invoiced (with age), paid-not-performed, performed-by-authorization | V1 |

## 5. Billing, price lists, and coverage

| # | Feature | Phase |
|---|---|---|
| 5.1 | Service catalog: consultations, lab tests, procedures, drugs, consumables, with department and category | V1 |
| 5.2 | Price lists with effective dates; multiple lists (cash, each payer); bulk percentage update creating a new dated version | V1 |
| 5.3 | Invoice built from the visit's requested lines; cashier can remove lines (cancel with reason) but not add arbitrary amounts | V1 |
| 5.4 | Price frozen on the line at invoice approval, from the list effective that day | V1 |
| 5.5 | Coverage rule per line: one payer, payer share and patient share (percentage, fixed copay, or ceiling) | V1 |
| 5.6 | Different payers across lines in one invoice | V1 |
| 5.7 | Exclusions: services a payer never covers fall entirely to the patient automatically | V1 |
| 5.8 | Pre-approval reference number recorded on the line where the payer requires it | V1 |
| 5.9 | Discounts and exemptions: by role with limit, reason mandatory, shown on shift report with approver name | V1 |
| 5.10 | Invoice approval locks it. No edits after approval | V1 |
| 5.11 | Credit note and correction documents linked to the original invoice, with approval | V1 |
| 5.12 | Standalone pharmacy sale invoice for walk-in customers, same rules | V1 |
| 5.13 | Package or bundle pricing (e.g. antenatal package) | P2 |
| 5.14 | Doctor fee share per service (percentage or fixed) computed per invoice, with a monthly doctor statement | P2 |
| 5.15 | Two payers sharing the same line | Later |

## 6. Payments, cashier, and bank transfers

| # | Feature | Phase |
|---|---|---|
| 6.1 | Payment methods: cash, bank transfer (Bankak and others), QR, card, patient credit balance | V1 |
| 6.2 | Transfer record: bank, reference, amount, date, who entered. **Reference unique per bank**; override needs supervisor and reason | V1 |
| 6.3 | Transfer states: pending verification, confirmed, rejected. Confirmation by cashier supervisor or accountant only, with timestamp | V1 |
| 6.4 | Pending transfers never count as confirmed collection; separate report with age in days | V1 |
| 6.5 | Payment allocation: one payment across several invoices, several payments on one invoice, unallocated remainder to patient balance | V1 |
| 6.6 | Partial payment allowed only if center policy permits; otherwise lines stay unpaid and do not reach work lists | V1 |
| 6.7 | Refund document: opened only from a cancelled paid line or credit note, supervisor approval, paid from the current shift | V1 |
| 6.8 | Rejected transfer after shift close: reversal entry in the current shift, invoice returns to outstanding, alert to manager | V1 |
| 6.9 | Receipt printing (thermal and A4) with QR of receipt number for verification | V1 |
| 6.10 | Bank statement import (Excel/CSV) with auto-matching of references to pending transfers | P2 |
| 6.11 | Direct bank API confirmation | Later (no public API verified) |

## 7. Shifts and cash control

| # | Feature | Phase |
|---|---|---|
| 7.1 | Open shift per cashier with opening float; one open shift per cashier | V1 |
| 7.2 | Shift close: expected cash computed, counted cash entered, variance with mandatory explanation if non-zero | V1 |
| 7.3 | Shift report: cash confirmed, bank confirmed, bank pending, discounts by approver, cancellations, refunds, patient credits | V1 |
| 7.4 | Closed shift is locked. Any later effect posts to the current shift with a link to the original | V1 |
| 7.5 | Manager review screen: variances, pending transfers, exceptions, with sign-off | V1 |
| 7.6 | Daily cash handover record between shifts and to the safe | V1 |
| 7.7 | Multi-cashier and multi-till per shift | V1? |

## 8. Pharmacy and inventory

| # | Feature | Phase |
|---|---|---|
| 8.1 | Item master: drug name (generic and brand), form, strength, units hierarchy (box, strip, tablet), barcode, min stock, storage | V1 |
| 8.2 | Batches with expiry and cost; FEFO suggestion at dispense | V1 |
| 8.3 | Dispense from paid prescription lines only; partial dispense with remainder cancelled-and-refunded or deferred | V1 |
| 8.4 | Stock decrement at dispense, not at invoicing | V1 |
| 8.5 | Goods receipt from supplier: invoice, batch, expiry, cost, quantity | V1 |
| 8.6 | Stock adjustment with reason (damage, expiry, count correction), supervisor approval | V1 |
| 8.7 | Stock count sessions: counted vs book, variance report, post adjustments | V1 |
| 8.8 | Expiry report: expiring within 30/60/90 days | V1 |
| 8.9 | Low stock alerts and reorder suggestion | V1 |
| 8.10 | Internal transfer between stores (main store to pharmacy, to lab consumables) | V1? |
| 8.11 | Consumables issued to departments and charged or not per policy | P2 |
| 8.12 | Purchase orders and supplier management | P2 |
| 8.13 | Excel import of items, batches, opening stock, with preview | V1 |
| 8.14 | Drug interaction checks | Later |

## 9. Laboratory

| # | Feature | Phase |
|---|---|---|
| 9.1 | Test catalog: name, sample type, parameters, units, reference ranges by sex and age, turnaround time | V1 |
| 9.2 | Work list of paid or authorized tests; sample received step with label print | V1 |
| 9.3 | Result entry per parameter with flags (high/low/critical) against reference ranges | V1 |
| 9.4 | Supervisor approval; only approved results visible to doctor and patient | V1 |
| 9.5 | Result correction after approval creates an amended version, original retained | V1 |
| 9.6 | Result print and PDF in Arabic and English | V1 |
| 9.7 | Test cannot be performed: cancel with reason, auto refund flow | V1 |
| 9.8 | Turnaround time report | V1 |
| 9.9 | Outsourced tests to external lab with tracking | P2 |
| 9.10 | Analyzer integration through device agent | P2 |
| 9.11 | Radiology orders and report entry with image attachment | P2 |

## 10. Procedures and nursing

| # | Feature | Phase |
|---|---|---|
| 10.1 | Procedure work list of paid or authorized lines | V1 |
| 10.2 | One-tap "done" marking who and when; optional note | V1 |
| 10.3 | Vitals and nursing note per visit | V1 |
| 10.4 | Consumables used per procedure (deducted from stock) | P2 |
| 10.5 | Minimal inpatient: admit, bed assignment, daily bed charge to invoice, discharge | V1? (explicit scope increase) |
| 10.6 | Nursing care documentation, medication administration record | Later |

## 11. Insurance and payer claims

| # | Feature | Phase |
|---|---|---|
| 11.1 | Payer master: name, contract, price list, copay rules, exclusions, pre-approval requirements, claim period | V1 |
| 11.2 | Payer share accrues per line as receivable, never as cash | V1 |
| 11.3 | Claim batch per payer per period: select lines, generate claim, export Excel and PDF in the payer's format | V1 |
| 11.4 | Claim response entry: accepted, rejected, partial, per line with reason | V1 |
| 11.5 | Rejected amounts: re-bill patient or write off, both with approval and reason | V1 |
| 11.6 | Payer payment recording and allocation to claims | V1 |
| 11.7 | Payer aging and outstanding report | V1 |
| 11.8 | Electronic claim submission | Later |

## 12. Reports and dashboards

| # | Feature | Phase |
|---|---|---|
| 12.1 | Daily revenue: by department, by doctor, by payment method, confirmed vs pending | V1 |
| 12.2 | Requested-not-invoiced, paid-not-performed, performed-by-authorization | V1 |
| 12.3 | Shift variances by cashier and date | V1 |
| 12.4 | Pending transfers with age | V1 |
| 12.5 | Discounts, cancellations, refunds by user and reason | V1 |
| 12.6 | Stock valuation, movement, variance, expiry | V1 |
| 12.7 | Payer receivables by status | V1 |
| 12.8 | Patient visits by department, doctor, day, new vs follow-up | V1 |
| 12.9 | Lab turnaround and volume by test | V1 |
| 12.10 | Manager dashboard (phone-friendly): today's cash, pending, queue, alerts | V1 |
| 12.11 | Every report exportable to Excel and PDF | V1 |
| 12.12 | Doctor statements (fee share) | P2 |
| 12.13 | Government reporting exports in DHIS2-compatible format | P2 |
| 12.14 | Cloud owner dashboard across branches (read-only, one-way replication) | P2 |

## 13. Administration and configuration

| # | Feature | Phase |
|---|---|---|
| 13.1 | Center profile: name, logo, address, tax/registration numbers printed on documents | V1 |
| 13.2 | Departments, rooms, doctors with specialties and schedules | V1 |
| 13.3 | Users, roles, permission matrix | V1 |
| 13.4 | Policy switches: pay-first default, partial payment allowed, follow-up window, discount limits per role, perform-first roles | V1 |
| 13.5 | Cancellation and adjustment reason lists | V1 |
| 13.6 | Document numbering sequences per type | V1 |
| 13.7 | Print template editor (logo, footer text) | V1 |
| 13.8 | Backup status, manual backup trigger, restore test log | V1 |
| 13.9 | Data export: full export of patients, invoices, payments, stock in open formats on demand | V1 |
| 13.10 | Update management: version shown, release notes, update trigger with rollback | V1 |

## 14. Data protection and operations

| # | Feature | Phase |
|---|---|---|
| 14.1 | Nightly local backup, continuous WAL archiving to cloud when online, monthly automated restore test with result on the status page | V1 |
| 14.2 | Approved invoices and closed shifts protected by DB triggers against update and delete | V1 |
| 14.3 | Row-level access: doctors see clinical data, cashiers see financial data, by role | V1 |
| 14.4 | Session and login audit, failed login lockout | V1 |
| 14.5 | Encrypted cloud backup at rest | V1 |
| 14.6 | Disaster runbook: replace server from backup within a defined time | V1 |

## 15. Patient-facing

| # | Feature | Phase |
|---|---|---|
| 15.1 | Printed receipt and result with QR for verification | V1 |
| 15.2 | Web portal: appointments, approved results, instructions, no app install | P2 |
| 15.3 | SMS notifications | Later |

---

## V1 summary by actor

| Actor | What they can do in V1 |
|---|---|
| Receptionist | Register, find, merge-flag patients; create visits; book appointments (if V1?); print tokens |
| Doctor | See summary and alerts; write note; order tests, procedures, drugs; see statuses and results; refer |
| Cashier | Build invoice from orders; apply coverage; collect cash and transfers; allocate; print receipt; open and close shift |
| Cashier supervisor / accountant | Confirm transfers; approve refunds, discounts above limit, credit notes; review shifts; run claims |
| Pharmacist | Dispense from paid prescriptions; receive goods; adjust and count stock; walk-in sales |
| Lab technician | Receive samples; enter results |
| Lab supervisor | Approve and amend results |
| Nurse | Vitals; mark procedures done |
| Manager | Dashboard; exception reports; shift sign-off; policy settings |
| System admin | Users, roles, catalogs, price lists, backups, updates |

## Explicitly not in V1

Inpatient (beyond the minimal exception), radiology, multi-branch sync, electronic payer or bank integration, native mobile apps, doctor fee shares, purchase orders, patient portal, SMS, AI features.
