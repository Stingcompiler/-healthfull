"""``/api/catalog``: services, price lists and versions, payers, coverage rules and exclusions.

FEATURES 5.1, 5.2, 5.5-5.8 and 11.1. Routers stay thin: each operation checks one permission,
parses its schema (money strings through ``domain.money.money``) and calls one function of
``apps.catalog.services``; every rule and amount comes from ``domain.pricing`` and
``domain.coverage``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Status

from api.errors import PermissionRequired
from api.pagination import paginate
from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.catalog import services
from apps.catalog.models import CoverageRule, Exclusion, Payer, Service, ServiceCategory
from apps.catalog.schemas import (
    ActiveParams,
    BulkPreviewOut,
    BulkUpdateIn,
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    CoveragePreviewIn,
    CoveragePreviewOut,
    CoverageRuleIn,
    CoverageRuleOut,
    CoverageRulePatch,
    ExclusionIn,
    ExclusionOut,
    ExclusionPatch,
    PayerIn,
    PayerListOut,
    PayerListParams,
    PayerOut,
    PayerPatch,
    PayerSummaryOut,
    PriceChangesIn,
    PriceItemOut,
    PriceListIn,
    PriceListOut,
    PriceListPatch,
    ServiceIn,
    ServiceListParams,
    ServiceOut,
    ServicePatch,
    VersionIn,
    VersionItemParams,
    VersionOut,
)
from apps.core.models import User
from domain.money import money
from domain.pricing import RoundMode

catalog_router = Router(tags=["catalog"])
add_ping(catalog_router, "catalog")

_READ: dict[int, type[ErrorOut]] = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE: dict[int, type[ErrorOut]] = {**ERROR_RESPONSES, 404: ErrorOut}

_AMOUNT_FIELDS = ("payer_percent", "copay_amount", "ceiling_amount")


def _actor(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("catalog.view")
    return user


def _dec(value: str | None) -> Decimal | None:
    """A client amount or percent string as a 2-place Decimal (409 ``INVALID_AMOUNT``)."""
    return None if value is None else money(value)


def _amounts(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (_dec(v) if k in _AMOUNT_FIELDS else v) for k, v in data.items()}


# --- Services and categories ----------------------------------------------------------------


@catalog_router.get(
    "/services",
    response={200: Page[ServiceOut], **_READ},
    operation_id="catalog_list_services",
    summary="Catalog services by text, kind, department, category and active flag (paged)",
)
@require_perm("catalog.view")
def list_services(request: HttpRequest, params: Query[ServiceListParams]) -> dict[str, Any]:
    rows = services.list_services(
        q=params.q,
        kind=params.kind,
        department_id=params.department_id,
        category_id=params.category_id,
        active=params.active,
    )
    return paginate(rows, params.page, params.page_size)


@catalog_router.post(
    "/services",
    response={201: ServiceOut, **_WRITE},
    operation_id="catalog_create_service",
    summary="Add a catalog service (its kind never changes)",
    description=(
        "409 INVALID_CODE, SERVICE_CODE_TAKEN, SERVICE_NAME_REQUIRED, DEPARTMENT_INACTIVE, "
        "CATEGORY_INACTIVE."
    ),
)
@require_perm("catalog.manage")
def create_service(request: HttpRequest, payload: ServiceIn) -> Status[Service]:
    return Status(201, services.create_service(_actor(request), **payload.dict()))


@catalog_router.get(
    "/services/{service_id}",
    response={200: ServiceOut, **_READ},
    operation_id="catalog_get_service",
    summary="One catalog service",
)
@require_perm("catalog.view")
def get_service(request: HttpRequest, service_id: int) -> Service:
    return services.get_service(service_id)


@catalog_router.patch(
    "/services/{service_id}",
    response={200: ServiceOut, **_WRITE},
    operation_id="catalog_update_service",
    summary="Edit a service's names, department, category, description, order or active flag",
)
@require_perm("catalog.manage")
def update_service(request: HttpRequest, service_id: int, payload: ServicePatch) -> Service:
    return services.update_service(_actor(request), service_id, **payload.changes())


@catalog_router.get(
    "/categories",
    response={200: list[CategoryOut], **_READ},
    operation_id="catalog_list_categories",
    summary="Service categories",
)
@require_perm("catalog.view")
def list_categories(request: HttpRequest, params: Query[ActiveParams]) -> list[ServiceCategory]:
    return list(services.list_categories(active=params.active))


@catalog_router.post(
    "/categories",
    response={201: CategoryOut, **_WRITE},
    operation_id="catalog_create_category",
    summary="Add a service category",
    description="409 INVALID_CODE, CATEGORY_CODE_TAKEN.",
)
@require_perm("catalog.manage")
def create_category(request: HttpRequest, payload: CategoryIn) -> Status[ServiceCategory]:
    return Status(201, services.create_category(_actor(request), **payload.dict()))


@catalog_router.patch(
    "/categories/{category_id}",
    response={200: CategoryOut, **_WRITE},
    operation_id="catalog_update_category",
    summary="Rename, reorder or (de)activate a category",
)
@require_perm("catalog.manage")
def update_category(
    request: HttpRequest, category_id: int, payload: CategoryPatch
) -> ServiceCategory:
    return services.update_category(_actor(request), category_id, **payload.changes())


# --- Price lists and versions ---------------------------------------------------------------


@catalog_router.get(
    "/price-lists",
    response={200: list[PriceListOut], **_READ},
    operation_id="catalog_list_price_lists",
    summary="Price lists with their version timelines (current and scheduled versions)",
)
@require_perm("catalog.view_prices")
def list_price_lists(request: HttpRequest, params: Query[ActiveParams]) -> list[Any]:
    return services.list_price_lists(active=params.active)


@catalog_router.post(
    "/price-lists",
    response={201: PriceListOut, **_WRITE},
    operation_id="catalog_create_price_list",
    summary="Add a price list (prices come in dated versions)",
    description="409 INVALID_CODE, PRICE_LIST_CODE_TAKEN.",
)
@require_perm("catalog.manage_prices")
def create_price_list(request: HttpRequest, payload: PriceListIn) -> Status[Any]:
    return Status(201, services.create_price_list(_actor(request), **payload.dict()))


@catalog_router.get(
    "/price-lists/{price_list_id}",
    response={200: PriceListOut, **_READ},
    operation_id="catalog_get_price_list",
    summary="One price list with its version timeline",
)
@require_perm("catalog.view_prices")
def get_price_list(request: HttpRequest, price_list_id: int) -> Any:
    return services.get_price_list(price_list_id)


@catalog_router.patch(
    "/price-lists/{price_list_id}",
    response={200: PriceListOut, **_WRITE},
    operation_id="catalog_update_price_list",
    summary="Rename or (de)activate a price list",
    description="409 PRICE_LIST_DEFAULT_REQUIRED, PRICE_LIST_IN_USE (an active payer uses it).",
)
@require_perm("catalog.manage_prices")
def update_price_list(request: HttpRequest, price_list_id: int, payload: PriceListPatch) -> Any:
    return services.update_price_list(_actor(request), price_list_id, **payload.changes())


@catalog_router.post(
    "/price-lists/{price_list_id}/versions",
    response={201: VersionOut, **_WRITE},
    operation_id="catalog_create_price_version",
    summary="Add a dated version, copying the version effective then (or copy_from_id)",
    description=(
        "Editable until it starts. 409 PRICE_VERSION_BACKDATED (before tomorrow, except a "
        "list's first version today), PRICE_VERSION_DATE_TAKEN, PRICE_LIST_INACTIVE."
    ),
)
@require_perm("catalog.manage_prices")
def create_price_version(
    request: HttpRequest, price_list_id: int, payload: VersionIn
) -> Status[Any]:
    version = services.add_version(_actor(request), price_list_id, **payload.dict())
    return Status(201, services.get_version(version.pk))


@catalog_router.get(
    "/versions/{version_id}",
    response={200: VersionOut, **_READ},
    operation_id="catalog_get_price_version",
    summary="One price list version (status, editable, item count)",
)
@require_perm("catalog.view_prices")
def get_price_version(request: HttpRequest, version_id: int) -> Any:
    return services.get_version(version_id)


@catalog_router.get(
    "/versions/{version_id}/items",
    response={200: Page[PriceItemOut], **_READ},
    operation_id="catalog_list_price_items",
    summary="Prices of one version, by text and kind (paged)",
)
@require_perm("catalog.view_prices")
def list_price_items(
    request: HttpRequest, version_id: int, params: Query[VersionItemParams]
) -> dict[str, Any]:
    services.get_version(version_id)  # 404 for an unknown version
    rows = services.version_items(version_id, q=params.q, kind=params.kind)
    return paginate(rows, params.page, params.page_size)


@catalog_router.put(
    "/versions/{version_id}/items",
    response={200: VersionOut, **_WRITE},
    operation_id="catalog_set_price_items",
    summary="Set or remove prices of a version that has not started yet",
    description=(
        "null removes a service. 409 PRICE_VERSION_LOCKED once the version is effective "
        "(create a new version), INVALID_PRICE, INVALID_AMOUNT, SERVICE_UNKNOWN."
    ),
)
@require_perm("catalog.manage_prices")
def set_price_items(request: HttpRequest, version_id: int, payload: PriceChangesIn) -> Any:
    prices = {item.service_id: _dec(item.unit_price) for item in payload.items}
    return services.edit_version_prices(_actor(request), version_id, prices)


def _bulk_args(payload: BulkUpdateIn) -> dict[str, Any]:
    return {
        "percent": money(payload.percent),
        "effective_from": payload.effective_from,
        "step": money(payload.step),
        "mode": RoundMode(payload.mode),
        "kinds": payload.kinds,
        "service_ids": payload.service_ids,
    }


@catalog_router.post(
    "/price-lists/{price_list_id}/bulk-preview",
    response={200: BulkPreviewOut, **_WRITE},
    operation_id="catalog_preview_bulk_update",
    summary="Before and after prices of a bulk percentage update (saves nothing)",
    description=(
        "Same base version, rounding and date rules as bulk-update. 409 "
        "PRICE_VERSION_BACKDATED, PRICE_VERSION_DATE_TAKEN, NO_EFFECTIVE_PRICE_LIST, "
        "INVALID_PERCENT, INVALID_ROUNDING_STEP."
    ),
)
@require_perm("catalog.manage_prices")
def preview_bulk_update(
    request: HttpRequest, price_list_id: int, payload: BulkUpdateIn
) -> dict[str, Any]:
    preview = services.preview_bulk_update(price_list_id, **_bulk_args(payload))
    return {
        "base_version": preview.base,
        "effective_from": preview.effective_from,
        "percent": f"{preview.percent:.2f}",
        "changed_count": preview.changed_count,
        "rows": [
            {
                "service_id": row.service.pk,
                "service_code": row.service.code,
                "service_name_ar": row.service.name_ar,
                "service_name_en": row.service.name_en,
                "service_kind": row.service.kind,
                "old_price": str(row.old_price),
                "new_price": str(row.new_price),
                "changed": row.changed,
            }
            for row in preview.rows
        ],
    }


@catalog_router.post(
    "/price-lists/{price_list_id}/bulk-update",
    response={201: VersionOut, **_WRITE},
    operation_id="catalog_apply_bulk_update",
    summary="Create a new dated version with prices changed by a percentage",
    description="The base version never changes. Errors as bulk-preview.",
)
@require_perm("catalog.manage_prices")
def apply_bulk_update(
    request: HttpRequest, price_list_id: int, payload: BulkUpdateIn
) -> Status[Any]:
    row = services.apply_bulk_update(
        _actor(request), price_list_id, note=payload.note, **_bulk_args(payload)
    )
    return Status(201, row)


# --- Payers, coverage rules and exclusions ----------------------------------------------------


@catalog_router.get(
    "/payers",
    response={200: Page[PayerListOut], **_READ},
    operation_id="catalog_list_payers",
    summary="Payers with contract dates and price list (paged)",
)
@require_perm("catalog.manage_payers")
def list_payers(request: HttpRequest, params: Query[PayerListParams]) -> dict[str, Any]:
    rows = services.list_payers(q=params.q, active=params.active)
    return paginate(rows, params.page, params.page_size)


@catalog_router.get(
    "/payers/options",
    response={200: list[PayerSummaryOut], **_READ},
    operation_id="catalog_list_payer_options",
    summary="Active payers for pickers (no contract or contact details)",
)
@require_perm("catalog.view")
def list_payer_options(request: HttpRequest) -> list[Payer]:
    return list(services.list_payers(active=True))


@catalog_router.post(
    "/payers",
    response={201: PayerOut, **_WRITE},
    operation_id="catalog_create_payer",
    summary="Add a payer with its contract information",
    description=(
        "409 INVALID_CODE, PAYER_CODE_TAKEN, PAYER_CONTRACT_DATES, PRICE_LIST_INACTIVE, "
        "INVALID_EMAIL."
    ),
)
@require_perm("catalog.manage_payers")
def create_payer(request: HttpRequest, payload: PayerIn) -> Status[Payer]:
    data = payload.dict()
    code = data.pop("code")
    return Status(201, services.create_payer(_actor(request), code=code, **data))


@catalog_router.get(
    "/payers/{payer_id}",
    response={200: PayerOut, **_READ},
    operation_id="catalog_get_payer",
    summary="One payer with its coverage rules and exclusions",
)
@require_perm("catalog.manage_payers")
def get_payer(request: HttpRequest, payer_id: int) -> Payer:
    return services.get_payer(payer_id)


@catalog_router.patch(
    "/payers/{payer_id}",
    response={200: PayerOut, **_WRITE},
    operation_id="catalog_update_payer",
    summary="Edit a payer's contract, price list, contact or active flag",
)
@require_perm("catalog.manage_payers")
def update_payer(request: HttpRequest, payer_id: int, payload: PayerPatch) -> Payer:
    return services.update_payer(_actor(request), payer_id, **payload.changes())


@catalog_router.post(
    "/payers/{payer_id}/rules",
    response={201: CoverageRuleOut, **_WRITE},
    operation_id="catalog_create_coverage_rule",
    summary="Add a coverage rule for a service, a kind of service, or the payer default",
    description=(
        "409 COVERAGE_SCOPE_INVALID, COVERAGE_RULE_DUPLICATE, COVERAGE_RULE_INCOMPLETE, "
        "INVALID_COVERAGE_RULE, INVALID_AMOUNT."
    ),
)
@require_perm("catalog.manage_payers")
def create_coverage_rule(
    request: HttpRequest, payer_id: int, payload: CoverageRuleIn
) -> Status[CoverageRule]:
    data = _amounts(payload.dict())
    return Status(201, services.add_coverage_rule(_actor(request), payer_id, **data))


@catalog_router.patch(
    "/rules/{rule_id}",
    response={200: CoverageRuleOut, **_WRITE},
    operation_id="catalog_update_coverage_rule",
    summary="Change a rule's kind, amounts, pre-approval flag, note or active flag",
    description="New amounts apply to invoices approved from now on (invariant 2).",
)
@require_perm("catalog.manage_payers")
def update_coverage_rule(
    request: HttpRequest, rule_id: int, payload: CoverageRulePatch
) -> CoverageRule:
    return services.update_coverage_rule(_actor(request), rule_id, **_amounts(payload.changes()))


@catalog_router.post(
    "/payers/{payer_id}/exclusions",
    response={201: ExclusionOut, **_WRITE},
    operation_id="catalog_create_exclusion",
    summary="Exclude a service or kind of service: 100% to the patient",
    description="409 EXCLUSION_SCOPE_REQUIRED, COVERAGE_SCOPE_INVALID, EXCLUSION_DUPLICATE.",
)
@require_perm("catalog.manage_payers")
def create_exclusion(
    request: HttpRequest, payer_id: int, payload: ExclusionIn
) -> Status[Exclusion]:
    return Status(201, services.add_exclusion(_actor(request), payer_id, **payload.dict()))


@catalog_router.patch(
    "/exclusions/{exclusion_id}",
    response={200: ExclusionOut, **_WRITE},
    operation_id="catalog_update_exclusion",
    summary="Edit an exclusion's note or switch it on or off",
)
@require_perm("catalog.manage_payers")
def update_exclusion(request: HttpRequest, exclusion_id: int, payload: ExclusionPatch) -> Exclusion:
    return services.update_exclusion(_actor(request), exclusion_id, **payload.changes())


@catalog_router.post(
    "/coverage/preview",
    response={200: CoveragePreviewOut, **_WRITE},
    operation_id="catalog_preview_coverage",
    summary="Split of an example line under a rule being edited (e.g. 10,000 at 70%)",
    description="Saves nothing. 409 COVERAGE_RULE_INCOMPLETE, INVALID_COVERAGE_RULE.",
)
@require_perm("catalog.manage_payers")
def preview_coverage(request: HttpRequest, payload: CoveragePreviewIn) -> dict[str, str]:
    data = _amounts(payload.dict())
    split = services.preview_coverage(
        rule_kind=data["rule_kind"],
        gross=money(data["gross"]),
        payer_percent=data["payer_percent"],
        copay_amount=data["copay_amount"],
        ceiling_amount=data["ceiling_amount"],
    )
    return {
        "gross": str(split.gross),
        "payer_share": str(split.payer_share),
        "patient_share": str(split.patient_share),
    }
