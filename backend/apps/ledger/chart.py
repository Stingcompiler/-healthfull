"""The fixed chart of accounts (ARCHITECTURE 4.7), seeded by ``0003_seed_accounts``.

``domain/ledger.py`` owns the posting rules over these codes; the migration holds a frozen
copy of this table and ``apps/ledger/tests/test_models.py`` keeps them in sync.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountDef:
    code: str
    name_ar: str
    name_en: str
    kind: str
    normal_balance: str


CHART: tuple[AccountDef, ...] = (
    AccountDef("CASH", "النقد في الصندوق", "Cash in drawer", "asset", "debit"),
    AccountDef(
        "BANK_PENDING",
        "تحويلات بانتظار التحقق",
        "Transfers awaiting verification",
        "asset",
        "debit",
    ),
    AccountDef("BANK", "البنك (مؤكد)", "Bank (verified)", "asset", "debit"),
    AccountDef("AR_PATIENT", "ذمم المرضى", "Patient receivable", "asset", "debit"),
    AccountDef("AR_PAYER", "ذمم جهات التغطية", "Payer receivable", "asset", "debit"),
    AccountDef("PATIENT_CREDIT", "أرصدة المرضى", "Patient credit", "liability", "credit"),
    AccountDef("REVENUE", "إيراد الخدمات", "Service revenue", "revenue", "credit"),
    AccountDef("DISCOUNT", "الخصومات والإعفاءات", "Discounts", "contra_revenue", "debit"),
    AccountDef("WRITE_OFF", "شطب مرفوضات جهات التغطية", "Payer write-offs", "expense", "debit"),
    AccountDef("CASH_OVER_SHORT", "فروق النقد", "Cash over and short", "expense", "debit"),
)

ACCOUNT_CODES: frozenset[str] = frozenset(a.code for a in CHART)


def ensure_chart_of_accounts() -> int:
    """Create missing chart accounts (transactional tests truncate them); returns the count."""
    from apps.ledger.models import Account

    created = 0
    for order, account in enumerate(CHART):
        _, was_created = Account.objects.get_or_create(
            code=account.code,
            defaults={
                "name_ar": account.name_ar,
                "name_en": account.name_en,
                "kind": account.kind,
                "normal_balance": account.normal_balance,
                "sort_order": order,
            },
        )
        created += int(was_created)
    return created
