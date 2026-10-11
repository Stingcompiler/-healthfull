"""e2e builders of the claims module (``manage.py e2e_fixture``, test databases only).

``claims_case``: one payer's shares at a chosen stage of the claim cycle, in one call: a new
payer (70% of cash prices, so ``PRC-ECG`` 10,000 splits 7,000 payer / 3,000 patient), a
patient covered by it, a visit with the ordered services invoiced and approved, then (by
``stage``) a draft claim, the claim submitted, or the payer's answers recorded. Each call
makes its own payer, so a spec sees exactly its own lines in the batch builder and aging.

``claims_screens``: the claim screens with data in them for the responsive matrix, built
once (idempotent): accrued shares, a draft claim, an answered claim with a partial line, a
rejection rebilled and one unresolved, a bank payment and a cheque waiting to clear.

Every step goes through the services as the user a screen would act as (reception, doctor,
cashier, accountant), after the permission check of the matching endpoint.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.billing.models import InvoiceLine
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
from apps.claims import services as cs
from apps.claims.models import Claim, ClaimLine, ClaimStatus, PayerPayment
from apps.core.e2e.fixtures import Json, Params, fixture, run_nested
from apps.core.models import User
from apps.core.services import require_permission
from apps.payments.models import Bank
from domain import claims as dclaims
from domain.errors import DomainError

PRICE_LIST = "CLM70"
CASH_LIST = "CASH"
SCREENS_PAYER = "CLMSCR"
STAGES = ("accrued", "draft", "submitted", "answered")
DEFAULT_SERVICES = ("PRC-ECG", "LAB-CBC", "LAB-FBS")


def _price_list(actor: User) -> PriceList:
    """A payer price list at cash prices, effective today (created once)."""
    today = timezone.localdate()
    plist, _ = PriceList.objects.update_or_create(
        code=PRICE_LIST,
        defaults={
            "name_ar": "أسعار تأمين اختبار المطالبات",
            "name_en": "Claims test insurance prices",
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
            note="Cash prices (claims e2e)",
            today=today,
        )
    return plist


def _payer(code: str, actor: User) -> Payer:
    """A payer that pays 70% of every line at cash prices (idempotent per code)."""
    today = timezone.localdate()
    number = code.removeprefix("CLM")
    payer, _ = Payer.objects.update_or_create(
        code=code,
        defaults={
            "name_ar": f"تأمين المطالبات {number}",
            "name_en": f"Claims insurance {number}",
            "kind": PayerKind.INSURANCE,
            "price_list": _price_list(actor),
            "contract_no": f"CT-{number}",
            "contract_start": date(today.year, 1, 1),
            "claim_period": ClaimPeriod.MONTHLY,
            "requires_card_number": False,
            "address": "Khartoum 2, Street 15",
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
            "note": "70% of every line (claims e2e)",
        },
    )
    return payer


def _new_payer_code() -> str:
    taken = Payer.objects.filter(code__startswith="CLM").count()
    n = taken + 1
    while Payer.objects.filter(code=f"CLM{n:03d}").exists():
        n += 1
    return f"CLM{n:03d}"


def _invoice(payer: Payer, services: list[str]) -> Json:
    """A covered patient's visit with ``services`` invoiced and approved; returns refs."""
    made = run_nested("patient", {"payer": payer.code})
    visit = run_nested("visit", {"patient": made["patient"]["id"], "coverage": payer.code})
    vid = visit["visit"]["id"]
    run_nested("order", {"visit": vid, "items": [{"service": s} for s in services]})
    approved = run_nested("approve_invoice", {"visit": vid, "services": services})
    return {"patient": made["patient"], "visit": visit["visit"], "invoice": approved["invoice"]}


def _answer(claim: Claim, outcomes: list[str], actor: User) -> Claim:
    """Record ``outcomes`` (accepted, partial, rejected) on the claim's lines in order; a
    partial accepts half (rounded down to whole pounds), a rejection says why."""
    require_permission(actor, "claims.record_response")
    lines = list(claim.lines.order_by("id"))
    responses = []
    for line, outcome in zip(lines, outcomes, strict=False):
        half = (line.amount_claimed / 2).quantize(Decimal("1"))
        accepted = dclaims.response_amount(outcome, line.amount_claimed, half)
        reason = "" if outcome == "accepted" else "Not covered by the contract"
        responses.append(cs.ClaimResponse(line.pk, accepted, reason=reason, reference="RA-E2E"))
    return cs.record_responses(claim, responses, actor=actor)


def _claim_json(claim: Claim | None) -> Json | None:
    if claim is None:
        return None
    return {
        "id": claim.pk,
        "number": claim.number,
        "status": claim.status,
        "lines": [
            {
                "id": cl.pk,
                "invoice_line_id": cl.invoice_line_id,
                "amount": f"{cl.amount_claimed:.2f}",
                "status": cl.status,
            }
            for cl in claim.lines.order_by("id")
        ],
    }


@fixture(
    "claims_case",
    summary=(
        "A new 70% payer, a covered patient and an approved invoice of `services` (default "
        "PRC-ECG, LAB-CBC, LAB-FBS), taken to `stage`: accrued (default), draft, submitted or "
        "answered (`outcomes` per line: accepted, partial, rejected; default all accepted). "
        "Returns the payer, patient, visit, invoice and claim."
    ),
    params=("stage", "services", "outcomes"),
)
def claims_case(p: Params) -> Json:
    actor = p.actor("accountant")
    stage = p.choice("stage", STAGES, "accrued")
    services = [str(s) for s in p.items("services")] or list(DEFAULT_SERVICES)
    outcomes = [str(o) for o in p.items("outcomes")] or ["accepted"] * len(services)
    for outcome in outcomes:
        if outcome not in dclaims.RESPONSE_OUTCOMES:
            raise DomainError("FIXTURE_PARAM_INVALID", "Unknown outcome", outcome=outcome)
    payer = _payer(_new_payer_code(), p.user("admin", "admin"))
    made = _invoice(payer, services)
    claim: Claim | None = None
    if stage != "accrued":
        require_permission(actor, "claims.manage")
        today = timezone.localdate()
        claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=actor)
        if stage in ("submitted", "answered"):
            claim = cs.submit_claim(claim, actor=actor)
        if stage == "answered":
            claim = _answer(claim, outcomes, actor)
    return {
        "payer": {"id": payer.pk, "code": payer.code, "name_en": payer.name_en},
        **made,
        "claim": _claim_json(claim),
    }


@fixture(
    "claims_screens",
    summary=(
        "Populated claim screens for the responsive matrix, built once (idempotent, as "
        "`accountant`): accrued shares, a draft claim, an answered claim (accepted, partial, "
        "rejected and rebilled, rejected unresolved), a bank payment and a cheque waiting to "
        "clear. Returns the payer and both claims."
    ),
    params=(),
)
def claims_screens(p: Params) -> Json:
    actor = p.actor("accountant")
    # Workers resolve their routes at the same time: one builds, the others read.
    list(User.objects.select_for_update().filter(pk=actor.pk).values_list("pk", flat=True))
    payer = _payer(SCREENS_PAYER, p.user("admin", "admin"))
    today = timezone.localdate()
    answered = (
        Claim.objects.filter(payer=payer, status=ClaimStatus.RESPONDED).order_by("id").first()
    )
    if answered is None:
        require_permission(actor, "claims.manage")
        _invoice(payer, ["PRC-ECG", "LAB-CBC", "LAB-RFT", "LAB-UA"])
        claim = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=actor)
        cs.submit_claim(claim, actor=actor)
        answered = _answer(claim, ["accepted", "partial", "rejected", "rejected"], actor)
        rebill = ClaimLine.objects.filter(claim=answered).order_by("id")[2]
        require_permission(actor, "claims.resolve_rejection")
        cs.resolve_rejection(
            rebill,
            resolution="rebilled",
            actor=actor,
            reason_code="NOT_COVERED",
            note="",
            approver=p.user("manager", "manager"),
        )
        require_permission(actor, "claims.record_payer_payment")
        first = ClaimLine.objects.filter(claim=answered).order_by("id")[0]
        cs.record_payer_payment(
            payer=payer,
            amount=Decimal("5000.00"),
            received_on=today,
            actor=actor,
            bank=Bank.objects.get(code="BOK"),
            reference=f"RA-{payer.code}-1",
            claim_amounts={answered.pk: Decimal("5000.00")},
        )
        cs.record_payer_payment(
            payer=payer,
            amount=Decimal("2000.00"),
            received_on=today,
            actor=actor,
            method="cheque",
            reference=f"CHQ-{payer.code}-1",
            allocations={first.pk: Decimal("2000.00")},
        )
    draft = Claim.objects.filter(payer=payer, status=ClaimStatus.DRAFT).order_by("id").first()
    if draft is None:
        _invoice(payer, ["PRC-ECG", "LAB-FBS"])
        draft = cs.build_claim(payer=payer, period_start=today, period_end=today, actor=actor)
    if not InvoiceLine.objects.filter(payer=payer, claim_lines__isnull=True).exists():
        _invoice(payer, ["LAB-BFMP"])  # stays accrued: the batch builder has a line to show
    return {
        "payer": {"id": payer.pk, "code": payer.code},
        "draft_claim": {"id": draft.pk, "number": draft.number},
        "answered_claim": {"id": answered.pk, "number": answered.number},
        "payments": PayerPayment.objects.filter(payer=payer).count(),
    }
