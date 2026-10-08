"""e2e builders of the cashier module (``manage.py e2e_fixture``, test databases only).

``cashier_payer``: a payer that pays 70% of the cash price of every line, so a 10,000 service
(``PRC-ECG``) splits exactly 7,000 payer / 3,000 patient, the split the cashier specs check.
The seeded payers price from discounted lists (``AMAN`` = cash x 0.90), so none of them gives
that split. Reference data (payer, price list, coverage rule) is written like the base seed
writes it; the price list version goes through the catalog service.
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.catalog import services as catalog_services
from apps.catalog.models import (
    ClaimPeriod,
    CoverageRule,
    CoverageRuleKind,
    Payer,
    PayerKind,
    PriceList,
    PriceListKind,
    PriceListVersion,
)
from apps.core.e2e.fixtures import Json, Params, fixture

CODE = "CSH70"
CASH_LIST = "CASH"


@fixture(
    "cashier_payer",
    summary=(
        f"Payer {CODE}: cash prices, payer pays 70% of every line (idempotent); returns its code."
    ),
    params=(),
)
def cashier_payer(p: Params) -> Json:
    actor = p.actor("admin")
    today = timezone.localdate()
    plist, _ = PriceList.objects.update_or_create(
        code=CODE,
        defaults={
            "name_ar": "أسعار تأمين اختبار الكاشير",
            "name_en": "Cashier test insurance prices",
            "kind": PriceListKind.PAYER,
            "is_default": False,
            "active": True,
        },
    )
    if not PriceListVersion.objects.filter(price_list=plist).exists():
        cash = catalog_services.effective_version(PriceList.objects.get(code=CASH_LIST), today)
        catalog_services.create_version(
            plist,
            effective_from=today,
            prices=catalog_services.version_prices(cash),
            actor=actor,
            note="Cash prices (cashier e2e)",
            today=today,
        )
    payer, _ = Payer.objects.update_or_create(
        code=CODE,
        defaults={
            "name_ar": "تأمين اختبار الكاشير",
            "name_en": "Cashier test insurance",
            "kind": PayerKind.INSURANCE,
            "price_list": plist,
            "contract_no": "CSH-70",
            "contract_start": date(today.year, 1, 1),
            "contract_end": None,
            "claim_period": ClaimPeriod.MONTHLY,
            "requires_card_number": False,
            "active": True,
        },
    )
    CoverageRule.objects.update_or_create(
        payer=payer,
        service=None,
        service_kind="",
        active=True,
        defaults={
            "rule_kind": CoverageRuleKind.PERCENTAGE,
            "payer_percent": 70,
            "note": "70% of every line (cashier e2e)",
        },
    )
    return {"payer": payer.code, "id": payer.pk}
