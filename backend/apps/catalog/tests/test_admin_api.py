"""``/api/catalog`` administration: services, price lists and versions, bulk updates, payers,
coverage rules, exclusions and the live split preview (FEATURES 5.1, 5.2, 5.5-5.8, 11.1).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.catalog import services as cat
from apps.catalog.models import PriceList, PriceListVersion
from apps.core.models import User
from apps.core.tests import builders as b
from conftest import ApiClient

pytestmark = pytest.mark.django_db


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


def _put(api: ApiClient, path: str, data: Any) -> Any:
    return api.request("PUT", path, data)


@pytest.fixture
def admin(make_user: Any) -> User:
    return make_user("boss", roles=["admin"])


@pytest.fixture
def client(api_client: ApiClient, admin: User) -> ApiClient:
    assert api_client.login("boss").status_code == 200
    return api_client


def _login(make_user: Any, username: str, role: str) -> ApiClient:
    make_user(username, roles=[role])
    api = ApiClient()
    assert api.login(username).status_code == 200
    return api


@pytest.fixture
def doctor_client(make_user: Any) -> ApiClient:
    return _login(make_user, "doc", "doctor")


@pytest.fixture
def today() -> Any:
    return timezone.localdate()


# --- Services -------------------------------------------------------------------------------


def test_service_crud(client: ApiClient) -> None:
    dept = b.department("RAD")
    created = client.post(
        "/api/catalog/services",
        {
            "code": "RAD-XRAY",
            "name_ar": "أشعة سينية",
            "name_en": "X-ray",
            "kind": "procedure",
            "department_id": dept.pk,
        },
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["department_code"] == "RAD"
    assert body["kind"] == "procedure"
    _error(
        client.post(
            "/api/catalog/services",
            {"code": "RAD-XRAY", "name_en": "Dup", "kind": "lab"},
        ),
        409,
        "SERVICE_CODE_TAKEN",
    )
    _error(
        client.post("/api/catalog/services", {"code": "NONAME", "kind": "lab"}),
        409,
        "SERVICE_NAME_REQUIRED",
    )
    edited = client.patch(
        f"/api/catalog/services/{body['id']}", {"name_en": "Chest X-ray", "department_id": None}
    )
    assert edited.status_code == 200
    assert edited.json()["name_en"] == "Chest X-ray"
    assert edited.json()["department_id"] is None

    page = client.get("/api/catalog/services?q=chest&kind=procedure").json()
    assert [s["code"] for s in page["items"]] == ["RAD-XRAY"]


def test_doctor_reads_services_without_prices_and_cannot_edit(doctor_client: ApiClient) -> None:
    b.service(kind="lab")
    page = doctor_client.get("/api/catalog/services").json()
    assert page["count"] >= 1
    assert "unit_price" not in page["items"][0]
    _error(
        doctor_client.post("/api/catalog/services", {"code": "X1", "name_en": "x", "kind": "lab"}),
        403,
        "PERMISSION_DENIED",
    )
    _error(doctor_client.get("/api/catalog/price-lists"), 403, "PERMISSION_DENIED")
    _error(doctor_client.get("/api/catalog/payers"), 403, "PERMISSION_DENIED")
    assert doctor_client.get("/api/catalog/payers/options").status_code == 200


def test_categories(client: ApiClient) -> None:
    created = client.post(
        "/api/catalog/categories", {"code": "IMAGING", "name_ar": "تصوير", "name_en": "Imaging"}
    )
    assert created.status_code == 201
    _error(
        client.post("/api/catalog/categories", {"code": "IMAGING", "name_ar": "x", "name_en": "x"}),
        409,
        "CATEGORY_CODE_TAKEN",
    )
    assert any(c["code"] == "IMAGING" for c in client.get("/api/catalog/categories").json())


# --- Price lists and versions ---------------------------------------------------------------


def _new_list(client: ApiClient, code: str = "TEST") -> dict[str, Any]:
    response = client.post(
        "/api/catalog/price-lists", {"code": code, "name_ar": "قائمة", "name_en": "List"}
    )
    assert response.status_code == 201, response.content
    return response.json()


def test_price_list_versions_and_item_editing(client: ApiClient, today: Any) -> None:
    s1, s2 = b.service(kind="lab"), b.service(kind="drug")
    plist = _new_list(client)
    assert plist["versions"] == []

    # The first version of an empty list may start today.
    first = client.post(
        f"/api/catalog/price-lists/{plist['id']}/versions",
        {"effective_from": today.isoformat()},
    )
    assert first.status_code == 201, first.content
    v1 = first.json()
    assert v1["status"] == "current"
    assert v1["editable"] is False
    _error(
        _put(
            client,
            f"/api/catalog/versions/{v1['id']}/items",
            {"items": [{"service_id": s1.pk, "unit_price": "100"}]},
        ),
        409,
        "PRICE_VERSION_LOCKED",
    )

    tomorrow = today + timedelta(days=1)
    second = client.post(
        f"/api/catalog/price-lists/{plist['id']}/versions",
        {"effective_from": tomorrow.isoformat(), "note": "new year"},
    )
    v2 = second.json()
    assert v2["status"] == "scheduled"
    assert v2["editable"] is True
    assert v2["based_on_id"] == v1["id"]
    saved = _put(
        client,
        f"/api/catalog/versions/{v2['id']}/items",
        {
            "items": [
                {"service_id": s1.pk, "unit_price": "15000"},
                {"service_id": s2.pk, "unit_price": "٢٥٠٫٥"},
            ]
        },
    )
    assert saved.status_code == 200, saved.content
    assert saved.json()["item_count"] == 2
    items = client.get(f"/api/catalog/versions/{v2['id']}/items").json()["items"]
    assert {i["service_code"]: i["unit_price"] for i in items} == {
        s1.code: "15000.00",
        s2.code: "250.50",
    }
    removed = _put(
        client,
        f"/api/catalog/versions/{v2['id']}/items",
        {"items": [{"service_id": s2.pk, "unit_price": None}]},
    )
    assert removed.json()["item_count"] == 1

    _error(
        client.post(
            f"/api/catalog/price-lists/{plist['id']}/versions",
            {"effective_from": tomorrow.isoformat()},
        ),
        409,
        "PRICE_VERSION_DATE_TAKEN",
    )
    _error(
        client.post(
            f"/api/catalog/price-lists/{plist['id']}/versions",
            {"effective_from": today.isoformat()},
        ),
        409,
        "PRICE_VERSION_BACKDATED",
    )
    _error(
        _put(
            client,
            f"/api/catalog/versions/{v2['id']}/items",
            {"items": [{"service_id": s1.pk, "unit_price": "-5"}]},
        ),
        409,
        "INVALID_PRICE",
    )
    detail = client.get(f"/api/catalog/price-lists/{plist['id']}").json()
    assert detail["current_version_id"] == v1["id"]
    assert detail["next_version_id"] == v2["id"]
    assert [v["id"] for v in detail["versions"]] == [v2["id"], v1["id"]]


def test_backdated_version_refused(client: ApiClient, today: Any) -> None:
    plist = _new_list(client)
    client.post(
        f"/api/catalog/price-lists/{plist['id']}/versions", {"effective_from": today.isoformat()}
    )
    _error(
        client.post(
            f"/api/catalog/price-lists/{plist['id']}/versions",
            {"effective_from": (today - timedelta(days=3)).isoformat()},
        ),
        409,
        "PRICE_VERSION_BACKDATED",
    )


def _seed_list(admin: User, today: Any, prices: dict[Any, str]) -> PriceList:
    plist = PriceList.objects.create(code="BULK", name_ar="ج", name_en="Bulk", kind="payer")
    cat.create_version(
        plist,
        effective_from=today,
        prices={s.pk: Decimal(p) for s, p in prices.items()},
        actor=admin,
        today=today,
    )
    return plist


def test_bulk_preview_matches_apply_and_creates_new_dated_version(
    client: ApiClient, admin: User, today: Any
) -> None:
    lab, drug = b.service(kind="lab"), b.service(kind="drug")
    plist = _seed_list(admin, today, {lab: "15000.00", drug: "333.00"})
    base = cat.effective_version(plist, today)
    start = today + timedelta(days=7)
    body = {"percent": "10", "effective_from": start.isoformat()}

    preview = client.post(f"/api/catalog/price-lists/{plist.pk}/bulk-preview", body)
    assert preview.status_code == 200, preview.content
    data = preview.json()
    rows = {r["service_code"]: r for r in data["rows"]}
    assert rows[lab.code]["old_price"] == "15000.00"
    assert rows[lab.code]["new_price"] == "16500.00"
    assert rows[drug.code]["new_price"] == "366.30"
    assert data["changed_count"] == 2
    assert data["base_version"]["id"] == base.pk
    assert PriceListVersion.objects.filter(price_list=plist).count() == 1  # nothing saved

    applied = client.post(
        f"/api/catalog/price-lists/{plist.pk}/bulk-update", {**body, "note": "+10% 2027"}
    )
    assert applied.status_code == 201, applied.content
    version = applied.json()
    assert version["effective_from"] == start.isoformat()
    assert version["percent_change"] == "10.00"
    assert version["status"] == "scheduled"
    assert version["based_on_id"] == base.pk
    new_prices = cat.version_prices(PriceListVersion.objects.get(pk=version["id"]))
    assert {sid: str(p) for sid, p in new_prices.items()} == {
        r["service_id"]: r["new_price"] for r in data["rows"]
    }
    # The base version is untouched (invariant 6).
    assert cat.version_prices(base)[lab.pk] == Decimal("15000.00")


def test_bulk_update_by_kind_with_rounding(client: ApiClient, admin: User, today: Any) -> None:
    lab, drug = b.service(kind="lab"), b.service(kind="drug")
    plist = _seed_list(admin, today, {lab: "15000.00", drug: "333.00"})
    body = {
        "percent": "7",
        "effective_from": (today + timedelta(days=2)).isoformat(),
        "kinds": ["lab"],
        "step": "500",
        "mode": "up",
    }
    rows = {
        r["service_code"]: r
        for r in client.post(f"/api/catalog/price-lists/{plist.pk}/bulk-preview", body).json()[
            "rows"
        ]
    }
    assert set(rows) == {lab.code}
    assert rows[lab.code]["new_price"] == "16500.00"


def test_bulk_update_errors(client: ApiClient, admin: User, today: Any, make_user: Any) -> None:
    lab = b.service(kind="lab")
    plist = _seed_list(admin, today, {lab: "100.00"})
    url = f"/api/catalog/price-lists/{plist.pk}/bulk-preview"
    _error(
        client.post(url, {"percent": "10", "effective_from": today.isoformat()}),
        409,
        "PRICE_VERSION_BACKDATED",
    )
    _error(
        client.post(
            url, {"percent": "10", "effective_from": (today - timedelta(days=1)).isoformat()}
        ),
        409,
        "PRICE_VERSION_BACKDATED",
    )
    _error(
        client.post(
            url, {"percent": "1,5", "effective_from": (today + timedelta(days=1)).isoformat()}
        ),
        409,
        "INVALID_AMOUNT",
    )
    cashier = _login(make_user, "till", "cashier")
    _error(
        cashier.post(url, {"percent": "10", "effective_from": today.isoformat()}),
        403,
        "PERMISSION_DENIED",
    )


def test_price_list_cannot_be_deactivated_while_payer_uses_it(client: ApiClient) -> None:
    plist = _new_list(client, "PAYLIST")
    payer = client.post(
        "/api/catalog/payers",
        {"code": "ACME", "name_ar": "أكمي", "name_en": "Acme", "price_list_id": plist["id"]},
    )
    assert payer.status_code == 201, payer.content
    _error(
        client.patch(f"/api/catalog/price-lists/{plist['id']}", {"active": False}),
        409,
        "PRICE_LIST_IN_USE",
    )
    default = PriceList.objects.get(is_default=True)
    _error(
        client.patch(f"/api/catalog/price-lists/{default.pk}", {"active": False}),
        409,
        "PRICE_LIST_DEFAULT_REQUIRED",
    )


# --- Payers, rules, exclusions and the split preview ----------------------------------------


def test_payer_rules_exclusions(client: ApiClient, today: Any) -> None:
    gyn, den = b.service(kind="procedure"), b.service(kind="procedure")
    created = client.post(
        "/api/catalog/payers",
        {
            "code": "AMANX",
            "name_ar": "أمان",
            "name_en": "Aman",
            "contract_no": "C-77",
            "contract_start": today.isoformat(),
            "contract_end": (today + timedelta(days=365)).isoformat(),
            "claim_period": "monthly",
            "email": "claims@aman.example",
        },
    )
    assert created.status_code == 201, created.content
    payer_id = created.json()["id"]
    _error(
        client.patch(
            f"/api/catalog/payers/{payer_id}",
            {"contract_end": (today - timedelta(days=1)).isoformat()},
        ),
        409,
        "PAYER_CONTRACT_DATES",
    )

    default = client.post(
        f"/api/catalog/payers/{payer_id}/rules", {"rule_kind": "percentage", "payer_percent": "70"}
    )
    assert default.status_code == 201, default.content
    assert default.json()["scope"] == "default"
    assert default.json()["payer_percent"] == "70.00"
    _error(
        client.post(
            f"/api/catalog/payers/{payer_id}/rules",
            {"rule_kind": "copay", "copay_amount": "2000"},
        ),
        409,
        "COVERAGE_RULE_DUPLICATE",
    )
    service_rule = client.post(
        f"/api/catalog/payers/{payer_id}/rules",
        {
            "rule_kind": "percentage",
            "payer_percent": "70",
            "service_id": gyn.pk,
            "requires_pre_approval": True,
        },
    )
    assert service_rule.json()["scope"] == "service"
    assert service_rule.json()["requires_pre_approval"] is True
    kind_rule = client.post(
        f"/api/catalog/payers/{payer_id}/rules",
        {"rule_kind": "ceiling", "ceiling_amount": "10000", "service_kind": "lab"},
    )
    assert kind_rule.json()["ceiling_amount"] == "10000.00"
    _error(
        client.post(
            f"/api/catalog/payers/{payer_id}/rules",
            {"rule_kind": "copay", "service_kind": "drug"},
        ),
        409,
        "COVERAGE_RULE_INCOMPLETE",
    )
    _error(
        client.post(
            f"/api/catalog/payers/{payer_id}/rules",
            {"rule_kind": "percentage", "payer_percent": "120", "service_kind": "drug"},
        ),
        409,
        "INVALID_COVERAGE_RULE",
    )
    edited = client.patch(
        f"/api/catalog/rules/{default.json()['id']}",
        {"rule_kind": "copay", "copay_amount": "2000"},
    )
    assert edited.status_code == 200, edited.content
    assert edited.json()["rule_kind"] == "copay"
    assert edited.json()["payer_percent"] is None

    exclusion = client.post(f"/api/catalog/payers/{payer_id}/exclusions", {"service_id": den.pk})
    assert exclusion.status_code == 201
    _error(
        client.post(f"/api/catalog/payers/{payer_id}/exclusions", {"service_id": den.pk}),
        409,
        "EXCLUSION_DUPLICATE",
    )
    _error(
        client.post(f"/api/catalog/payers/{payer_id}/exclusions", {}),
        409,
        "EXCLUSION_SCOPE_REQUIRED",
    )
    off = client.patch(f"/api/catalog/exclusions/{exclusion.json()['id']}", {"active": False})
    assert off.json()["active"] is False

    detail = client.get(f"/api/catalog/payers/{payer_id}").json()
    assert len(detail["coverage_rules"]) == 3
    assert len(detail["exclusions"]) == 1
    assert detail["contract_no"] == "C-77"
    listed = client.get("/api/catalog/payers?q=aman").json()
    assert listed["items"][0]["code"] == "AMANX"


@pytest.mark.parametrize(
    ("body", "payer", "patient"),
    [
        ({"rule_kind": "percentage", "payer_percent": "70"}, "7000.00", "3000.00"),
        ({"rule_kind": "copay", "copay_amount": "2000"}, "8000.00", "2000.00"),
        ({"rule_kind": "ceiling", "ceiling_amount": "6000"}, "6000.00", "4000.00"),
        (
            {"rule_kind": "ceiling", "ceiling_amount": "6000", "payer_percent": "50"},
            "5000.00",
            "5000.00",
        ),
        ({"rule_kind": "copay", "copay_amount": "20000"}, "0.00", "10000.00"),
    ],
)
def test_coverage_preview_example_split(
    client: ApiClient, body: dict[str, str], payer: str, patient: str
) -> None:
    response = client.post("/api/catalog/coverage/preview", {**body, "gross": "10000"})
    assert response.status_code == 200, response.content
    assert response.json() == {"gross": "10000.00", "payer_share": payer, "patient_share": patient}


def test_coverage_preview_errors(client: ApiClient, doctor_client: ApiClient) -> None:
    _error(
        client.post("/api/catalog/coverage/preview", {"rule_kind": "percentage"}),
        409,
        "COVERAGE_RULE_INCOMPLETE",
    )
    _error(
        doctor_client.post(
            "/api/catalog/coverage/preview", {"rule_kind": "percentage", "payer_percent": "70"}
        ),
        403,
        "PERMISSION_DENIED",
    )


def test_preview_and_invoice_split_agree(admin: User, today: Any) -> None:
    """The live example uses the very rule that splits invoice lines (no screen arithmetic)."""
    payer = b.payer(requires_card_number=False)
    service = b.service(kind="lab")
    rule = cat.add_coverage_rule(
        admin, payer.pk, rule_kind="percentage", payer_percent=Decimal("70")
    )
    resolved = cat.resolve_coverage(payer, service)
    assert resolved.rule == rule
    preview = cat.preview_coverage(
        rule_kind="percentage", gross=Decimal("10000.00"), payer_percent=Decimal("70")
    )
    from domain import coverage as dc

    assert dc.split_line(Decimal("10000.00"), Decimal("0.00"), resolved.domain_rule) == preview


def test_effective_version_prices_are_read_only(admin: User, today: Any) -> None:
    """A version that has started may already be frozen on invoices: edits are refused."""
    from domain.errors import DomainError

    version = b.price_version()  # effective since 2020
    with pytest.raises(DomainError) as exc:
        cat.edit_version_prices(admin, version.pk, {b.service().pk: Decimal("1.00")}, today=today)
    assert exc.value.code == "PRICE_VERSION_LOCKED"
