import { CheckCircle2, Minus, Plus, ShoppingBag, Trash2 } from "lucide-react";
import { useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

import { useCreateSale, useSaleCustomers, useSaleServices } from "../api";
import { ErrorAlert, LabeledField, QtyText } from "../components/common";
import { PharmacyNav } from "../components/PharmacyNav";
import { SALE_MODES } from "../lib/constants";
import { lineTotal, sumAmounts } from "../lib/money";
import { parseWhole } from "../lib/qty";
import { useNames } from "../lib/use-names";
import type { SaleCustomer, SaleInvoice, SaleService } from "../types";

interface BasketLine {
  service: SaleService;
  qty: string;
}

/**
 * A walk-in pharmacy sale (FLOW 6, FEATURES 5.12): the customer's file, the items and their
 * draft invoice. The cashier approves and collects it; the medicines are dispensed from the
 * queue once paid (invariant 1).
 */
export function SalePage() {
  const { t } = useTranslation(["pharmacy", "common"]);
  const canSell = usePermission("billing.pharmacy_sale");
  const [done, setDone] = useState<SaleInvoice | null>(null);
  const [key, setKey] = useState(0);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("sale.title")} description={t("sale.description")} icon={<ShoppingBag />} />
      <PharmacyNav />
      {!canSell ? (
        <AlertCard variant="info" title={t("sale.noAccessTitle")}>
          {t("sale.noAccess")}
        </AlertCard>
      ) : done ? (
        <SaleDone
          invoice={done}
          onNew={() => {
            setDone(null);
            setKey((k) => k + 1);
          }}
        />
      ) : (
        <SaleForm key={key} onCreated={setDone} />
      )}
    </div>
  );
}

function SaleForm({ onCreated }: { onCreated: (invoice: SaleInvoice) => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const names = useNames();
  const create = useCreateSale();
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [customerQ, setCustomerQ] = useState("");
  const debouncedCustomer = useDebouncedValue(customerQ, 300);
  const customers = useSaleCustomers(mode === "existing" ? debouncedCustomer : "");
  const [customer, setCustomer] = useState<SaleCustomer | null>(null);
  const [fullName, setFullName] = useState("");
  const [sex, setSex] = useState<"" | "male" | "female">("");
  const [phone, setPhone] = useState("");
  const [itemQ, setItemQ] = useState("");
  const debouncedItem = useDebouncedValue(itemQ, 250);
  const services = useSaleServices(debouncedItem);
  const [basket, setBasket] = useState<BasketLine[]>([]);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totals = basket.map((l) => {
    const qty = parseWhole(l.qty);
    return qty !== null && l.service.unit_price !== null ? lineTotal(l.service.unit_price, qty) : null;
  });
  const total = basket.length > 0 ? sumAmounts(totals) : null;
  const customerMissing = mode === "existing" ? customer === null : !fullName.trim() || !sex;

  const add = (service: SaleService) => {
    setBasket((prev) =>
      prev.some((l) => l.service.service_id === service.service_id)
        ? prev.map((l) =>
            l.service.service_id === service.service_id ? { ...l, qty: String((parseWhole(l.qty) ?? 0) + 1) } : l,
          )
        : [...prev, { service, qty: "1" }],
    );
    setItemQ("");
  };

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (customerMissing || basket.length === 0 || basket.some((l) => parseWhole(l.qty) === null)) return;
    try {
      const invoice = await create.mutateAsync({
        patient_id: mode === "existing" ? (customer?.id ?? null) : null,
        customer:
          mode === "new" ? { full_name: fullName.trim(), sex: sex as "male" | "female", phone: phone.trim() } : null,
        items: basket.map((l) => ({ service_id: l.service.service_id, quantity: parseWhole(l.qty) ?? 1, note: "" })),
      });
      onCreated(invoice);
    } catch (err) {
      setError(translateError(err));
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="card-surface grid content-start gap-3 p-4 md:p-5" aria-labelledby="sale-customer">
        <h2 id="sale-customer" className="text-base font-semibold">
          {t("sale.customer")}
        </h2>
        <RadioGroup
          value={mode}
          onValueChange={(v) => {
            setMode(v as "new" | "existing");
          }}
          className="flex flex-wrap gap-4"
        >
          {SALE_MODES.map((m) => (
            <div key={m} className="flex items-center gap-2">
              <RadioGroupItem value={m} id={`sale-mode-${m}`} data-testid={`sale-mode-${m}`} />
              <Label htmlFor={`sale-mode-${m}`} className="font-normal">
                {t(`sale.mode.${m}`)}
              </Label>
            </div>
          ))}
        </RadioGroup>
        {mode === "new" ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <LabeledField
              label={t("sale.fullName")}
              required
              className="sm:col-span-2"
              error={checked && !fullName.trim() ? t("common.required") : null}
            >
              {(id) => (
                <Input
                  id={id}
                  value={fullName}
                  maxLength={200}
                  autoComplete="off"
                  data-testid="sale-name"
                  onChange={(e) => {
                    setFullName(e.target.value);
                  }}
                />
              )}
            </LabeledField>
            <LabeledField label={t("sale.sex")} required error={checked && !sex ? t("common.required") : null}>
              {(id) => (
                <Select
                  value={sex}
                  onValueChange={(v) => {
                    setSex(v as "male" | "female");
                  }}
                >
                  <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="sale-sex">
                    <SelectValue placeholder={t("sale.sexPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="male">{t("common:sex.male")}</SelectItem>
                    <SelectItem value="female">{t("common:sex.female")}</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </LabeledField>
            <LabeledField label={t("sale.phone")}>
              {(id) => (
                <Input
                  id={id}
                  value={phone}
                  dir="ltr"
                  inputMode="tel"
                  maxLength={30}
                  data-testid="sale-phone"
                  onChange={(e) => {
                    setPhone(e.target.value);
                  }}
                />
              )}
            </LabeledField>
          </div>
        ) : customer ? (
          <div className="flex items-center justify-between gap-2 rounded-control border border-border-strong bg-subtle px-3 py-2">
            <span className="grid min-w-0 text-sm" data-testid="sale-customer-selected">
              <span className="font-medium">{names.person(customer)}</span>
              <bdi className="text-muted">{customer.file_no}</bdi>
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setCustomer(null);
              }}
            >
              {t("common.change")}
            </Button>
          </div>
        ) : (
          <div className="grid gap-2">
            <LabeledField label={t("sale.findCustomer")} error={checked ? t("sale.chooseCustomer") : null}>
              {(id) => (
                <Input
                  id={id}
                  type="search"
                  value={customerQ}
                  autoComplete="off"
                  placeholder={t("sale.findCustomerPlaceholder")}
                  data-testid="sale-customer-search"
                  onChange={(e) => {
                    setCustomerQ(e.target.value);
                  }}
                />
              )}
            </LabeledField>
            {debouncedCustomer.trim() ? (
              <ul
                className="grid max-h-56 overflow-y-auto rounded-control border border-border"
                aria-label={t("sale.findCustomer")}
              >
                {(customers.data ?? []).length === 0 ? (
                  <li className="px-3 py-2 text-sm text-muted">
                    {customers.isFetching ? t("common.searching") : t("common.noResults")}
                  </li>
                ) : (
                  (customers.data ?? []).map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        className="flex w-full flex-wrap justify-between gap-2 px-3 py-2 text-start text-sm focus-ring hover:bg-accent"
                        onClick={() => {
                          setCustomer(c);
                        }}
                      >
                        <span className="font-medium">{names.person(c)}</span>
                        <span className="text-muted">
                          <bdi>{c.file_no}</bdi> {c.phone ? <bdi>{c.phone}</bdi> : null}
                        </span>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            ) : null}
          </div>
        )}
      </section>

      <section className="card-surface grid content-start gap-3 p-4 md:p-5" aria-labelledby="sale-items">
        <h2 id="sale-items" className="text-base font-semibold">
          {t("sale.items")}
        </h2>
        <LabeledField label={t("sale.findItem")}>
          {(id) => (
            <Input
              id={id}
              type="search"
              value={itemQ}
              autoComplete="off"
              placeholder={t("sale.findItemPlaceholder")}
              data-testid="sale-item-search"
              onChange={(e) => {
                setItemQ(e.target.value);
              }}
            />
          )}
        </LabeledField>
        {debouncedItem.trim() ? (
          <ul
            className="grid max-h-64 overflow-y-auto rounded-control border border-border"
            aria-label={t("sale.findItem")}
          >
            {(services.data ?? []).length === 0 ? (
              <li className="px-3 py-2 text-sm text-muted">
                {services.isFetching ? t("common.searching") : t("common.noResults")}
              </li>
            ) : (
              (services.data ?? []).map((s) => (
                <li key={s.service_id}>
                  <button
                    type="button"
                    disabled={s.unit_price === null}
                    className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-start text-sm focus-ring hover:bg-accent disabled:opacity-60"
                    onClick={() => {
                      add(s);
                    }}
                    data-testid="sale-item-option"
                  >
                    <span className="grid">
                      <span className="font-medium">{names.name(s)}</span>
                      <span className="text-xs text-muted">
                        <bdi>{s.code}</bdi> ·{" "}
                        {s.item_id !== null ? (
                          <>
                            {t("sale.inStock")} <QtyText value={s.on_hand} unit={names.baseUnit(s)} />
                          </>
                        ) : (
                          t("dispense.notStocked")
                        )}
                      </span>
                    </span>
                    {s.unit_price !== null ? <MoneyText value={s.unit_price} /> : <span>{t("sale.noPrice")}</span>}
                  </button>
                </li>
              ))
            )}
          </ul>
        ) : null}

        {basket.length === 0 ? (
          <EmptyState bare size="compact" icon={<ShoppingBag />} title={t("sale.emptyBasket")} />
        ) : (
          <ul className="grid gap-2" data-testid="sale-basket">
            {basket.map((line, index) => {
              const qty = parseWhole(line.qty);
              const inputId = `sale-qty-${String(line.service.service_id)}`;
              return (
                <li
                  key={line.service.service_id}
                  className="grid gap-2 rounded-control border border-border p-3"
                  data-testid="sale-line"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="grid min-w-0">
                      <span className="font-medium break-words">{names.name(line.service)}</span>
                      <span className="text-xs text-muted">
                        {line.service.unit_price !== null ? <MoneyText value={line.service.unit_price} /> : null}
                        {line.service.item_id !== null ? (
                          <>
                            {" · "}
                            {t("sale.perUnit", { unit: names.baseUnit(line.service) })}
                          </>
                        ) : null}
                      </span>
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("sale.remove")}
                      onClick={() => {
                        setBasket((prev) => prev.filter((_, i) => i !== index));
                      }}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1">
                      <Label htmlFor={inputId} className="sr-only">
                        {t("sale.quantityOf", { name: names.name(line.service) })}
                      </Label>
                      <Button
                        type="button"
                        variant="outline"
                        size="icon-sm"
                        aria-label={t("sale.less")}
                        onClick={() => {
                          setBasket((prev) =>
                            prev.map((l, i) => (i === index ? { ...l, qty: String(Math.max(1, (qty ?? 1) - 1)) } : l)),
                          );
                        }}
                      >
                        <Minus aria-hidden="true" />
                      </Button>
                      <Input
                        id={inputId}
                        value={line.qty}
                        className="w-20 text-center"
                        inputMode="numeric"
                        dir="ltr"
                        aria-invalid={checked && qty === null ? true : undefined}
                        data-testid="sale-qty"
                        onChange={(e) => {
                          setBasket((prev) => prev.map((l, i) => (i === index ? { ...l, qty: e.target.value } : l)));
                        }}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon-sm"
                        aria-label={t("sale.more")}
                        onClick={() => {
                          setBasket((prev) =>
                            prev.map((l, i) => (i === index ? { ...l, qty: String((qty ?? 0) + 1) } : l)),
                          );
                        }}
                      >
                        <Plus aria-hidden="true" />
                      </Button>
                    </div>
                    {totals[index] ? <MoneyText value={totals[index] ?? "0"} className="font-semibold" /> : null}
                  </div>
                  {line.service.item_id !== null && qty !== null && qty > line.service.on_hand ? (
                    <p className="text-xs text-warning-fg">{t("sale.moreThanStock")}</p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        {checked && basket.length === 0 ? (
          <p role="alert" className="text-xs font-medium text-danger-fg">
            {t("sale.basketRequired")}
          </p>
        ) : null}
        {total !== null ? (
          <p className="flex justify-between border-t border-border pt-3 text-base font-semibold">
            <span>{t("sale.total")}</span>
            <span data-testid="sale-total">
              <MoneyText value={total} />
            </span>
          </p>
        ) : null}
        <p className="text-xs text-muted">{t("sale.priceNote")}</p>
        <ErrorAlert message={error} />
        <div className="flex justify-end">
          <Button type="submit" loading={create.isPending} data-testid="sale-submit">
            {t("sale.submit")}
          </Button>
        </div>
      </section>
    </form>
  );
}

function SaleDone({ invoice, onNew }: { invoice: SaleInvoice; onNew: () => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const names = useNames();
  return (
    <section className="card-surface grid gap-4 p-4 md:p-5" data-testid="sale-done">
      <AlertCard variant="success" icon={<CheckCircle2 />} title={t("sale.doneTitle")} live>
        {t("sale.doneBody", { visit: invoice.visit_number, fileNo: invoice.patient.file_no })}
      </AlertCard>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted">{t("sale.customer")}</dt>
          <dd className="font-medium">{names.person(invoice.patient)}</dd>
        </div>
        <div>
          <dt className="text-muted">{t("sale.fileNo")}</dt>
          <dd>
            <bdi data-testid="sale-file-no">{invoice.patient.file_no}</bdi>
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t("sale.visitNo")}</dt>
          <dd>
            <bdi data-testid="sale-visit-no">{invoice.visit_number}</bdi>
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t("sale.total")}</dt>
          <dd className="font-semibold">
            <MoneyText value={invoice.patient_total} />
          </dd>
        </div>
      </dl>
      <ul className="grid gap-1.5 text-sm">
        {invoice.lines.map((ln) => (
          <li key={ln.id} className="flex flex-wrap justify-between gap-2">
            <span>{t("sale.lineQty", { name: names.name(ln.service), qty: ln.quantity })}</span>
            <MoneyText value={ln.patient_share} />
          </li>
        ))}
      </ul>
      <div className="flex justify-end">
        <Button onClick={onNew} data-testid="sale-new">
          {t("sale.new")}
        </Button>
      </div>
    </section>
  );
}
