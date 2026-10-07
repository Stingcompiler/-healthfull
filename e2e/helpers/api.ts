/**
 * API access and data factories for specs (see e2e/README.md).
 *
 * 1. `apiAs(who)`: a logged-in API client per seed user (cached), CSRF-aware: every unsafe
 *    request carries the current `csrftoken` cookie as `X-CSRFToken`. Errors throw `ApiError`
 *    with the backend's `{code, message, details}`.
 * 2. `fixture(name, params)`: runs `manage.py e2e_fixture <name> --json` against the e2e
 *    database (backend/apps/core/e2e/fixtures.py). Fixtures build data through the services,
 *    as the user a real screen would act as, after checking that user's permission.
 * 3. Factories (`createPatient`, `createVisit`, `orderLines`, `createInvoice`,
 *    `approveInvoice`, `pay`, `openShift`, `closeShift`, `addCoverage`, `paidVisit`): typed
 *    wrappers that call the real API when an adapter for the endpoint is registered and the
 *    endpoint is in frontend/openapi.json, and the fixture command otherwise. Both paths return
 *    the same shapes (snake_case, ids, codes, money as strings).
 *
 * E2E_FACTORY_MODE: `auto` (default) as above, `fixture` always uses the fixture command,
 * `api` fails when a factory has no usable adapter (to prove an endpoint end to end).
 *
 * API adapters live in e2e/helpers/adapters/<module>.ts (files starting with "_" are skipped)
 * and call `registerAdapter`; they are loaded on the first factory call, so adding an endpoint
 * and its adapter never needs a change in this file.
 */
import { execFile } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { request, type APIRequestContext, type APIResponse } from "@playwright/test";

import { BACKEND_DIR, BASE_URL, DB_NAME, FRONTEND_DIR } from "../env";
import { resolveUser, type E2EUser, type SeedUser } from "../fixtures/users";
import { apiLogin } from "./auth";

// ------------------------------------------------------------------------------------------------
// API clients
// ------------------------------------------------------------------------------------------------

/** A non-2xx API answer. `code`/`details` come from the backend's `{code, message, details}`. */
export class ApiError extends Error {
  constructor(
    readonly method: string,
    readonly url: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`${method} ${url} -> ${String(status)}: ${typeof body === "string" ? body : JSON.stringify(body)}`);
    this.name = "ApiError";
  }

  get code(): string | undefined {
    const body = this.body as { code?: unknown } | null;
    return body && typeof body.code === "string" ? body.code : undefined;
  }

  get details(): Record<string, unknown> {
    const body = this.body as { details?: unknown } | null;
    return body && typeof body.details === "object" && body.details !== null
      ? (body.details as Record<string, unknown>)
      : {};
  }
}

type Query = Record<string, string | number | boolean>;

export interface RequestOptions {
  /** Query string parameters. */
  query?: Query;
  /** JSON body (unsafe methods). */
  data?: unknown;
  /** Status codes that are not errors (default: any 2xx). The raw response is still parsed. */
  expect?: number | readonly number[];
}

export interface CallOptions {
  /** Values for the `{name}` segments of the operation's path. */
  path?: Record<string, string | number>;
  query?: Query;
  body?: Record<string, unknown>;
}

export interface ApiClient {
  readonly user: E2EUser;
  /** The underlying Playwright request context (cookies: session and csrftoken). */
  readonly context: APIRequestContext;
  /** Sends a request and returns the raw response (no status check). */
  send(method: string, url: string, options?: RequestOptions): Promise<APIResponse>;
  get<T = unknown>(url: string, options?: RequestOptions): Promise<T>;
  post<T = unknown>(url: string, data?: unknown, options?: RequestOptions): Promise<T>;
  put<T = unknown>(url: string, data?: unknown, options?: RequestOptions): Promise<T>;
  patch<T = unknown>(url: string, data?: unknown, options?: RequestOptions): Promise<T>;
  delete<T = unknown>(url: string, options?: RequestOptions): Promise<T>;
  /** Calls an operation by its OpenAPI operation id (method and path from frontend/openapi.json). */
  call<T = unknown>(operationId: string, options?: CallOptions): Promise<T>;
  /** The current CSRF token (Django rotates it at login). */
  csrfToken(): Promise<string>;
  dispose(): Promise<void>;
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

async function cookie(context: APIRequestContext, name: string): Promise<string | undefined> {
  return (await context.storageState()).cookies.find((c) => c.name === name)?.value;
}

async function parse(response: APIResponse): Promise<unknown> {
  if (response.status() === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  const type = response.headers()["content-type"] ?? "";
  if (type.includes("json")) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  }
  return text;
}

function accepted(status: number, expect: RequestOptions["expect"]): boolean {
  if (expect === undefined) return status >= 200 && status < 300;
  return typeof expect === "number" ? status === expect : expect.includes(status);
}

class Client implements ApiClient {
  constructor(
    readonly user: E2EUser,
    readonly context: APIRequestContext,
  ) {}

  async csrfToken(): Promise<string> {
    let token = await cookie(this.context, "csrftoken");
    if (!token) {
      await this.context.get("/api/auth/csrf");
      token = await cookie(this.context, "csrftoken");
    }
    if (!token) throw new Error("csrftoken cookie was not set by /api/auth/csrf");
    return token;
  }

  async send(method: string, url: string, options: RequestOptions = {}): Promise<APIResponse> {
    const upper = method.toUpperCase();
    const headers: Record<string, string> = {};
    if (!SAFE_METHODS.has(upper)) headers["X-CSRFToken"] = await this.csrfToken();
    const send = () => this.context.fetch(url, { method: upper, headers, params: options.query, data: options.data });
    let response = await send();
    if (response.status() === 401) {
      // The session ended (logout, password change, reseed): sign in again once.
      await apiLogin(this.context, this.user.username as SeedUser);
      if (!SAFE_METHODS.has(upper)) headers["X-CSRFToken"] = await this.csrfToken();
      response = await send();
    }
    return response;
  }

  private async json<T>(method: string, url: string, options: RequestOptions): Promise<T> {
    const response = await this.send(method, url, options);
    const body = await parse(response);
    if (!accepted(response.status(), options.expect)) {
      throw new ApiError(method.toUpperCase(), url, response.status(), body);
    }
    return body as T;
  }

  get<T = unknown>(url: string, options: RequestOptions = {}): Promise<T> {
    return this.json<T>("GET", url, options);
  }

  post<T = unknown>(url: string, data?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.json<T>("POST", url, { ...options, data });
  }

  put<T = unknown>(url: string, data?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.json<T>("PUT", url, { ...options, data });
  }

  patch<T = unknown>(url: string, data?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.json<T>("PATCH", url, { ...options, data });
  }

  delete<T = unknown>(url: string, options: RequestOptions = {}): Promise<T> {
    return this.json<T>("DELETE", url, options);
  }

  async call<T = unknown>(operationId: string, options: CallOptions = {}): Promise<T> {
    const op = apiOperation(operationId);
    if (!op) throw new Error(`Operation ${operationId} is not in frontend/openapi.json (run make api)`);
    if (options.body && op.bodyProperties) {
      const unknown = Object.keys(options.body).filter((key) => !op.bodyProperties?.has(key));
      if (unknown.length > 0) {
        throw new Error(`${operationId} does not accept body field(s) ${unknown.join(", ")}`);
      }
    }
    const url = op.path.replace(/\{(\w+)\}/g, (_, name: string) => {
      const value = options.path?.[name];
      if (value === undefined) throw new Error(`${operationId} needs path parameter "${name}"`);
      return encodeURIComponent(String(value));
    });
    return this.json<T>(op.method, url, { query: options.query, data: options.body });
  }

  dispose(): Promise<void> {
    return this.context.dispose();
  }
}

/** A new logged-in client for `who`, not shared with other callers (dispose it yourself). */
export async function newApiClient(who: SeedUser): Promise<ApiClient> {
  const user = resolveUser(who);
  const context = await request.newContext({ baseURL: BASE_URL });
  try {
    await apiLogin(context, user.username as SeedUser);
  } catch (error) {
    await context.dispose();
    throw error;
  }
  return new Client(user, context);
}

const clients = new Map<string, Promise<ApiClient>>();

/**
 * The shared logged-in client of a seed user (one per user per worker):
 * `const cashier = await apiAs("cashier"); await cashier.get("/api/auth/me")`.
 */
export function apiAs(who: SeedUser): Promise<ApiClient> {
  const { username } = resolveUser(who);
  let client = clients.get(username);
  if (!client) {
    client = newApiClient(username as SeedUser);
    clients.set(username, client);
    client.catch(() => clients.delete(username));
  }
  return client;
}

/** Disposes every shared client (e.g. `test.afterAll(disposeApiClients)`). */
export async function disposeApiClients(): Promise<void> {
  const all = [...clients.values()];
  clients.clear();
  await Promise.all(all.map(async (client) => (await client).dispose().catch(() => undefined)));
}

// ------------------------------------------------------------------------------------------------
// OpenAPI operations (frontend/openapi.json, the committed contract)
// ------------------------------------------------------------------------------------------------

export interface OperationInfo {
  operationId: string;
  method: string;
  path: string;
  /** Body fields the operation accepts (null when it has no JSON object body schema). */
  bodyProperties: ReadonlySet<string> | null;
  requiredBody: ReadonlySet<string>;
}

interface SchemaObject {
  $ref?: string;
  properties?: Record<string, unknown>;
  required?: string[];
}

interface OpenApiDocument {
  paths: Record<string, Record<string, { operationId?: string; requestBody?: unknown }>>;
  components?: { schemas?: Record<string, SchemaObject> };
}

let operations: Map<string, OperationInfo> | undefined;

function loadOperations(): Map<string, OperationInfo> {
  const doc = JSON.parse(readFileSync(path.join(FRONTEND_DIR, "openapi.json"), "utf8")) as OpenApiDocument;
  const resolve = (schema: SchemaObject | undefined): SchemaObject | undefined => {
    if (!schema?.$ref) return schema;
    return doc.components?.schemas?.[schema.$ref.replace("#/components/schemas/", "")];
  };
  const found = new Map<string, OperationInfo>();
  for (const [route, methods] of Object.entries(doc.paths)) {
    for (const [method, op] of Object.entries(methods)) {
      if (!op.operationId) continue;
      const body = op.requestBody as { content?: Record<string, { schema?: SchemaObject }> } | undefined;
      const schema = resolve(body?.content?.["application/json"]?.schema);
      found.set(op.operationId, {
        operationId: op.operationId,
        method: method.toUpperCase(),
        path: route,
        bodyProperties: schema?.properties ? new Set(Object.keys(schema.properties)) : null,
        requiredBody: new Set(schema?.required ?? []),
      });
    }
  }
  return found;
}

/** The operation with this id in frontend/openapi.json, or undefined while it does not exist. */
export function apiOperation(operationId: string): OperationInfo | undefined {
  operations ??= loadOperations();
  return operations.get(operationId);
}

// ------------------------------------------------------------------------------------------------
// The fixture command
// ------------------------------------------------------------------------------------------------

/** A fixture refused by a rule; `code` is the backend error code (e.g. SHIFT_ALREADY_OPEN). */
export class FixtureError extends Error {
  constructor(
    readonly fixture: string,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown>,
  ) {
    super(`e2e_fixture ${fixture}: ${code}: ${message}`);
    this.name = "FixtureError";
  }
}

interface FixtureOutput {
  ok: boolean;
  result?: unknown;
  error?: { code: string; message: string; details: Record<string, unknown> };
}

function python(): { command: string; prefix: string[] } {
  const venv = path.join(BACKEND_DIR, ".venv", "bin", "python");
  return existsSync(venv) ? { command: venv, prefix: [] } : { command: "uv", prefix: ["run", "python"] };
}

type Params = Record<string, unknown>;

function clean(params: Params): Params {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined));
}

/**
 * Runs `manage.py e2e_fixture <name>` on the e2e database and returns its result, e.g.
 * `await fixture<{ shift: ShiftRef }>("open_shift", { opening_float: "5000" })`.
 * Fixture names and parameters: `manage.py e2e_fixture --list` and e2e/README.md.
 */
export function fixture<T = unknown>(name: string, params: Params = {}): Promise<T> {
  const { command, prefix } = python();
  const args = [...prefix, "manage.py", "e2e_fixture", name, "--params", JSON.stringify(clean(params)), "--json"];
  return new Promise<T>((resolve, reject) => {
    execFile(
      command,
      args,
      {
        cwd: BACKEND_DIR,
        env: { ...process.env, DB_NAME, DJANGO_DEBUG: "1" },
        timeout: 120_000,
        maxBuffer: 64 * 1024 * 1024,
        encoding: "utf8",
      },
      (error, stdout, stderr) => {
        const line = stdout.trim().split("\n").pop() ?? "";
        let output: FixtureOutput | undefined;
        try {
          output = JSON.parse(line) as FixtureOutput;
        } catch {
          output = undefined;
        }
        if (output?.ok) {
          resolve(output.result as T);
        } else if (output?.error) {
          const { code, message, details } = output.error;
          reject(new FixtureError(name, code, message, details));
        } else {
          reject(new Error(`e2e_fixture ${name} failed: ${error?.message ?? ""}\n${stderr}\n${stdout}`));
        }
      },
    );
  });
}

// ------------------------------------------------------------------------------------------------
// Result shapes (identical for the API and the fixture path)
// ------------------------------------------------------------------------------------------------

/** Money as the API sends it: a decimal string with two places ("15000.00"). */
export type Money = string;
/** Money to send: a string ("15000.00") or a whole number. */
export type MoneyInput = string | number;

export type ServiceKind = "consultation" | "lab" | "procedure" | "drug" | "consumable" | "bed";
export type LineState = "requested" | "invoiced" | "paid" | "performed" | "cancelled";
export type PaymentMethod = "cash" | "bank_transfer" | "qr" | "card" | "patient_credit";

export interface PatientRef {
  id: number;
  file_no: string;
  full_name_ar: string;
  full_name_en: string;
  sex: "male" | "female" | "unknown";
  date_of_birth: string | null;
  phone: string;
  is_incomplete: boolean;
}

export interface CoverageRef {
  id: number;
  patient_id: number;
  payer: string;
  card_number: string;
  is_default: boolean;
}

export interface ServiceLineRef {
  id: number;
  visit_id: number;
  service: string;
  kind: ServiceKind;
  quantity: number;
  payer: string | null;
  billing_status: "unbilled" | "invoiced" | "settled" | "credited";
  fulfilment_status: "pending" | "in_progress" | "performed" | "cancelled";
  state: LineState;
  order_source: string;
}

export interface VisitRef {
  id: number;
  number: string;
  patient_id: number;
  visit_type: "new" | "follow_up" | "emergency" | "pharmacy_sale" | "inpatient";
  status: "open" | "closed" | "cancelled";
  department: string | null;
  doctor: string | null;
  payer: string | null;
  card_number: string;
}

export interface QueueEntryRef {
  id: number;
  token_no: number;
  queue_date: string;
  status: string;
  department: string;
  doctor: string | null;
  /** The consultation fee is paid (or none is due): the doctor's queue shows the entry. */
  ready: boolean;
}

export interface InvoiceLineRef {
  id: number;
  line_no: number;
  service_line_id: number;
  service: string;
  quantity: number;
  unit_price: Money;
  gross: Money;
  discount: Money;
  payer: string | null;
  payer_share: Money;
  patient_share: Money;
}

export interface InvoiceRef {
  id: number;
  number: string | null;
  status: "draft" | "approved" | "void";
  visit_id: number;
  patient_id: number;
  priced_on: string | null;
  gross_total: Money;
  discount_total: Money;
  payer_total: Money;
  patient_total: Money;
  /** Patient money still owed (approved invoices only). */
  outstanding: Money | null;
  lines: InvoiceLineRef[];
}

export interface ShiftRef {
  id: number;
  number: string;
  status: "open" | "closed";
  cashier: string;
  till: string | null;
  opening_float: Money;
  expected_cash: Money;
  counted_cash: Money | null;
  variance: Money | null;
}

export interface PaymentRef {
  id: number;
  number: string;
  shift_id: number;
  patient_id: number;
  method: PaymentMethod;
  amount: Money;
  verification: "pending" | "confirmed" | "rejected";
  bank: string | null;
  reference: string;
}

export interface AllergyRef {
  id: number;
  allergen_type: "drug" | "drug_class" | "food" | "environmental" | "other";
  drug_class: string | null;
  substance: string;
  severity: "mild" | "moderate" | "severe" | "life_threatening";
}

export interface PatientResult {
  patient: PatientRef;
  coverage: CoverageRef | null;
  /** Allergies recorded with the patient (empty unless `allergies` was given). */
  allergies: AllergyRef[];
}

export interface VisitResult {
  visit: VisitRef;
  /** Every service line of the visit (the consultation fee line first). */
  lines: ServiceLineRef[];
  queue_entry: QueueEntryRef | null;
}

export interface InvoiceResult {
  invoice: InvoiceRef;
  /** Every service line of the invoice's visit, with its state after the step. */
  lines: ServiceLineRef[];
}

export interface PayResult {
  payment: PaymentRef;
  allocations: { invoice_id: number; amount: Money }[];
  invoices: InvoiceRef[];
  lines: ServiceLineRef[];
  shift: ShiftRef;
}

export interface PaidVisitResult extends PatientResult, VisitResult {
  invoice: InvoiceRef | null;
  payment: PaymentRef | null;
  shift: ShiftRef | null;
}

/** Ids of the seeded catalog by code (`catalog` fixture). */
export interface CatalogRef {
  departments: Record<string, number>;
  rooms: Record<string, number>;
  doctors: Record<string, { id: number; user_id: number; department: string; consultation_service: string | null }>;
  services: Record<
    string,
    {
      id: number;
      kind: ServiceKind;
      department: string | null;
      name_ar: string;
      name_en: string;
      cash_price: Money | null;
    }
  >;
  price_lists: Record<string, number>;
  payers: Record<string, { id: number; kind: string; price_list: string | null; requires_card_number: boolean }>;
  stores: Record<string, number>;
  items: Record<
    string,
    {
      id: number;
      base_unit: string;
      units: Record<string, number>;
      batches: { id: number; batch_no: string; expiry_date: string; stock: Record<string, number> }[];
    }
  >;
  lab_tests: Record<string, number>;
  beds: Record<string, { id: number; status: string }>;
  tills: Record<string, number>;
  banks: Record<string, number>;
}

// ------------------------------------------------------------------------------------------------
// Factory options
// ------------------------------------------------------------------------------------------------

/** A row given as the factory result object, its id, or its number / file number. */
export type Ref = { id: number } | number | string;

export interface ActAs {
  /** The acting seed user; each factory defaults to the role that does the step. */
  as?: SeedUser;
}

export interface PatientOptions extends ActAs {
  full_name_ar?: string;
  full_name_en?: string;
  sex?: "male" | "female" | "unknown";
  /** ISO date (YYYY-MM-DD). Default: a random adult or child birth date. */
  date_of_birth?: string;
  age_years?: number;
  /** Default: a random Sudanese mobile number. */
  phone?: string;
  phone_alt?: string;
  address?: string;
  national_id?: string;
  emergency_contact_name?: string;
  emergency_contact_phone?: string;
  notes?: string;
  /** Default true: skip the duplicate warning (set false to test it). */
  confirm_not_duplicate?: boolean;
  /** Emergency registration (name and sex only, flagged incomplete). */
  emergency?: boolean;
  /** Also put this payer's coverage on file: AMAN, NAKHEEL or RAHMA. */
  payer?: string;
  card_number?: string;
  valid_from?: string;
  valid_to?: string;
  patient_percent_override?: MoneyInput;
  /**
   * Allergies to record: drug class codes (PENICILLIN, CEPHALOSPORIN, NSAID) or objects, e.g.
   * `{ substance: "Peanuts", allergen_type: "food" }`. Severity defaults to "severe".
   */
  allergies?: (string | AllergyInput)[];
  /** Who records the allergies (default "nurse"; needs clinical.manage_allergies). */
  allergies_as?: SeedUser;
}

export interface AllergyInput {
  drug_class?: string;
  substance?: string;
  allergen_type?: AllergyRef["allergen_type"];
  severity?: AllergyRef["severity"];
  reaction?: string;
}

export interface CoverageOptions extends ActAs {
  patient: Ref;
  payer: string;
  card_number?: string;
  valid_from?: string;
  valid_to?: string;
  patient_percent_override?: MoneyInput;
  is_default?: boolean;
}

export interface VisitOptions extends ActAs {
  patient: Ref;
  /** A doctor's username (default "doctor"); null for a visit without a doctor. */
  doctor?: SeedUser | null;
  department?: string;
  visit_type?: "new" | "follow_up" | "emergency";
  /** "default" (the default coverage on file), "cash", or a payer code on file. */
  coverage?: string;
  card_number?: string;
  chief_complaint?: string;
  room?: string;
}

export interface Prescription {
  dose: string;
  dose_quantity?: MoneyInput;
  route?: string;
  frequency_code?: string;
  frequency_per_day?: MoneyInput;
  duration_days?: number;
  as_needed?: boolean;
  instructions?: string;
}

export interface OrderItem {
  /** Service code, e.g. "LAB-CBC". */
  service: string;
  /** Whole units (base units for drugs). Default 1, or dose x frequency x days for a prescription. */
  quantity?: number;
  note?: string;
  pre_approval_ref?: string;
  prescription?: Prescription;
}

export interface OrderOptions extends ActAs {
  visit: Ref;
  items: OrderItem[];
  acknowledge_allergies?: boolean;
}

export interface InvoiceOptions extends ActAs {
  visit: Ref;
  /** Service line ids to invoice (default: every unbilled line). */
  lines?: number[];
  /** Or service codes whose unbilled lines to invoice. */
  services?: string[];
  approve?: boolean;
}

export type ApproveInvoiceOptions = ActAs & ({ invoice: Ref } | { visit: Ref; lines?: number[]; services?: string[] });

export interface PayOptions extends ActAs {
  invoice?: Ref;
  visit?: Ref;
  patient?: Ref;
  /** Default: everything owed by the invoice(s). */
  amount?: MoneyInput;
  method?: PaymentMethod;
  /** Bank code for transfers (default BOK). */
  bank?: string;
  /** Default: a fresh unique reference. */
  reference?: string;
  sender_name?: string;
  transfer_date?: string;
  /** "none" keeps the money as patient credit. */
  allocate?: "auto" | "none";
  /** Default true: open the cashier's shift (zero float) when none is open. */
  open_shift?: boolean;
  note?: string;
}

export interface OpenShiftOptions extends ActAs {
  opening_float?: MoneyInput;
  till?: string;
  note?: string;
  /** What to do when the cashier already has an open shift (default "error"). */
  if_open?: "error" | "reuse" | "close";
}

export interface CloseShiftOptions extends ActAs {
  /** Default: the acting user's open shift. */
  shift?: Ref;
  /** Default: the expected cash (no variance). */
  counted?: MoneyInput;
  /** Variance reason code, e.g. COUNTING_ERROR. */
  reason?: string;
  note?: string;
}

export interface PaidVisitOptions extends ActAs, Omit<VisitOptions, "patient" | "as" | "room"> {
  patient?: Ref;
  patient_fields?: Omit<PatientOptions, "as">;
  method?: PaymentMethod;
  cashier_as?: SeedUser;
}

// ------------------------------------------------------------------------------------------------
// Adapters (factories over real endpoints)
// ------------------------------------------------------------------------------------------------

export interface Factories {
  createPatient: [PatientOptions, PatientResult];
  addCoverage: [CoverageOptions, CoverageRef];
  createVisit: [VisitOptions, VisitResult];
  orderLines: [OrderOptions, ServiceLineRef[]];
  createInvoice: [InvoiceOptions, InvoiceResult];
  approveInvoice: [ApproveInvoiceOptions, InvoiceResult];
  pay: [PayOptions, PayResult];
  openShift: [OpenShiftOptions, ShiftRef];
  closeShift: [CloseShiftOptions, ShiftRef];
  paidVisit: [PaidVisitOptions, PaidVisitResult];
}
export type FactoryName = keyof Factories;

export interface FactoryAdapter<N extends FactoryName> {
  /** Operation ids the adapter calls; it is used only when every one is in frontend/openapi.json. */
  operations: readonly string[];
  /**
   * Builds the result through the API. Returning undefined (before calling anything) hands
   * options the endpoint does not cover back to the fixture command.
   */
  run(options: Factories[N][0], api: (who: SeedUser) => Promise<ApiClient>): Promise<Factories[N][1] | undefined>;
}

const adapters = new Map<FactoryName, FactoryAdapter<FactoryName>>();

/** Routes a factory through real endpoints (call from e2e/helpers/adapters/<module>.ts). */
export function registerAdapter<N extends FactoryName>(name: N, adapter: FactoryAdapter<N>): void {
  adapters.set(name, adapter as unknown as FactoryAdapter<FactoryName>);
}

/** Removes an adapter (specs that register one temporarily). */
export function unregisterAdapter(name: FactoryName): void {
  adapters.delete(name);
}

const ADAPTERS_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "adapters");
let adaptersLoaded: Promise<void> | undefined;

function loadAdapters(): Promise<void> {
  adaptersLoaded ??= (async () => {
    if (!existsSync(ADAPTERS_DIR)) return;
    const files = readdirSync(ADAPTERS_DIR)
      .filter((f) => f.endsWith(".ts") && !f.endsWith(".d.ts") && !f.startsWith("_"))
      .sort();
    for (const file of files) await import(pathToFileURL(path.join(ADAPTERS_DIR, file)).href);
  })();
  return adaptersLoaded;
}

export type FactoryMode = "auto" | "fixture" | "api";

export function factoryMode(): FactoryMode {
  const mode = process.env.E2E_FACTORY_MODE ?? "auto";
  if (mode !== "auto" && mode !== "fixture" && mode !== "api") {
    throw new Error(`E2E_FACTORY_MODE must be auto, fixture or api (got "${mode}")`);
  }
  return mode;
}

/** Whether the factory would call the real API now (an adapter whose operations all exist). */
export async function usesApi(name: FactoryName): Promise<boolean> {
  await loadAdapters();
  const adapter = adapters.get(name);
  return (
    factoryMode() !== "fixture" &&
    adapter !== undefined &&
    adapter.operations.every((id) => apiOperation(id) !== undefined)
  );
}

async function build<N extends FactoryName>(
  name: N,
  options: Factories[N][0],
  viaFixture: () => Promise<Factories[N][1]>,
): Promise<Factories[N][1]> {
  if (await usesApi(name)) {
    const adapter = adapters.get(name) as unknown as FactoryAdapter<N>;
    const result = await adapter.run(options, apiAs);
    if (result !== undefined) return result;
  }
  if (factoryMode() === "api") {
    throw new Error(
      `E2E_FACTORY_MODE=api: no adapter of ${name} covers these options with operations in frontend/openapi.json`,
    );
  }
  return viaFixture();
}

// ------------------------------------------------------------------------------------------------
// Factories
// ------------------------------------------------------------------------------------------------

function ref(value: Ref | undefined): number | string | undefined {
  if (value === undefined) return undefined;
  return typeof value === "object" ? value.id : value;
}

function moneyParam(value: MoneyInput | undefined): string | undefined {
  return value === undefined ? undefined : String(value);
}

function username(who: SeedUser | undefined): string | undefined {
  return who === undefined ? undefined : resolveUser(who).username;
}

function patientParams(options: Omit<PatientOptions, "as">): Params {
  return {
    ...options,
    patient_percent_override: moneyParam(options.patient_percent_override),
    allergies_as: username(options.allergies_as),
  };
}

/** Registers a patient (as reception); with `payer`, puts that payer's coverage on file. */
export function createPatient(options: PatientOptions = {}): Promise<PatientResult> {
  return build("createPatient", options, () =>
    fixture<PatientResult>("patient", { ...patientParams(options), as: username(options.as) }),
  );
}

/** Puts a payer's coverage on a patient's file (as reception). */
export function addCoverage(options: CoverageOptions): Promise<CoverageRef> {
  return build("addCoverage", options, async () => {
    const result = await fixture<{ coverage: CoverageRef }>("coverage", {
      ...options,
      patient: ref(options.patient),
      patient_percent_override: moneyParam(options.patient_percent_override),
      as: username(options.as),
    });
    return result.coverage;
  });
}

/** Opens a visit (as reception): consultation fee line and queue token included. */
export function createVisit(options: VisitOptions): Promise<VisitResult> {
  return build("createVisit", options, () =>
    fixture<VisitResult>("visit", {
      ...options,
      patient: ref(options.patient),
      doctor: options.doctor === null ? null : username(options.doctor ?? undefined),
      as: username(options.as),
    }),
  );
}

/** Orders services on an open visit (as the doctor) after the allergy check. */
export function orderLines(options: OrderOptions): Promise<ServiceLineRef[]> {
  return build("orderLines", options, async () => {
    const items = options.items.map((item) => ({
      ...item,
      prescription: item.prescription && {
        ...item.prescription,
        dose_quantity: moneyParam(item.prescription.dose_quantity),
        frequency_per_day: moneyParam(item.prescription.frequency_per_day),
      },
    }));
    const result = await fixture<{ lines: ServiceLineRef[] }>("order", {
      ...options,
      visit: ref(options.visit),
      items: items.map((item) => clean(item)),
      as: username(options.as),
    });
    return result.lines;
  });
}

/** Drafts an invoice from a visit's unbilled lines (as the cashier); `approve: true` approves it. */
export function createInvoice(options: InvoiceOptions): Promise<InvoiceResult> {
  return build("createInvoice", options, () =>
    fixture<InvoiceResult>("invoice", { ...options, visit: ref(options.visit), as: username(options.as) }),
  );
}

/**
 * Approves a draft `invoice`, or drafts and approves a `visit`'s unbilled lines (as the
 * cashier). Prices freeze from the list effective today.
 */
export function approveInvoice(options: ApproveInvoiceOptions): Promise<InvoiceResult> {
  return build("approveInvoice", options, () => {
    const params: Params =
      "invoice" in options
        ? { invoice: ref(options.invoice) }
        : { visit: ref(options.visit), lines: options.lines, services: options.services };
    return fixture<InvoiceResult>("approve_invoice", { ...params, as: username(options.as) });
  });
}

/**
 * Takes a payment (as the cashier, in their open shift, opened with a zero float when
 * missing) for an `invoice`, a `visit`'s approved invoices or a `patient`'s open invoices.
 */
export function pay(options: PayOptions): Promise<PayResult> {
  return build("pay", options, () =>
    fixture<PayResult>("pay", {
      ...options,
      invoice: ref(options.invoice),
      visit: ref(options.visit),
      patient: ref(options.patient),
      amount: moneyParam(options.amount),
      as: username(options.as),
    }),
  );
}

/** Opens the cashier's shift (`if_open`: error, reuse or close the open one first). */
export function openShift(options: OpenShiftOptions = {}): Promise<ShiftRef> {
  return build("openShift", options, async () => {
    const result = await fixture<{ shift: ShiftRef }>("open_shift", {
      ...options,
      opening_float: moneyParam(options.opening_float),
      as: username(options.as),
    });
    return result.shift;
  });
}

/** Closes a shift (default: the acting cashier's open one) at the expected or `counted` cash. */
export function closeShift(options: CloseShiftOptions = {}): Promise<ShiftRef> {
  return build("closeShift", options, async () => {
    const result = await fixture<{ shift: ShiftRef }>("close_shift", {
      ...options,
      shift: ref(options.shift),
      counted: moneyParam(options.counted),
      as: username(options.as),
    });
    return result.shift;
  });
}

/**
 * A patient whose visit's consultation fee is invoiced and paid in cash, so the visit waits
 * ready in the doctor's queue. The cashier's shift stays open.
 */
export function paidVisit(options: PaidVisitOptions = {}): Promise<PaidVisitResult> {
  return build("paidVisit", options, () =>
    fixture<PaidVisitResult>("paid_visit", {
      ...options,
      patient: ref(options.patient),
      patient_fields: options.patient_fields && patientParams(options.patient_fields),
      doctor: options.doctor === null ? null : username(options.doctor ?? undefined),
      as: username(options.as),
      cashier_as: username(options.cashier_as),
    }),
  );
}

let catalogCache: Promise<CatalogRef> | undefined;

/** Ids of the seeded catalog by code (cached per worker; the seed never changes them). */
export function seededCatalog(): Promise<CatalogRef> {
  catalogCache ??= fixture<CatalogRef>("catalog");
  catalogCache.catch(() => (catalogCache = undefined));
  return catalogCache;
}
