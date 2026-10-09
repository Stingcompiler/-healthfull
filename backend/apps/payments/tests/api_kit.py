"""Shared set-up of the cashier API tests: logged-in clients per role and a priced visit."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.catalog.models import Payer
from apps.core.models import User
from apps.orders.models import ServiceLine
from apps.patients.models import Patient
from apps.payments.tests import fin
from apps.visits.models import Visit
from conftest import TEST_PASSWORD, ApiClient

D = Decimal


@dataclass
class Actor:
    user: User
    api: ApiClient

    @property
    def username(self) -> str:
        return self.user.username


def actor(make_user: Any, username: str, *roles: str) -> Actor:
    user = make_user(username, roles=list(roles))
    client = ApiClient()
    response = client.login(username, TEST_PASSWORD)
    assert response.status_code == 200, response.content
    return Actor(user, client)


@dataclass
class Desk:
    cashier: Actor
    cashier2: Actor
    sup: Actor
    manager: Actor
    accountant: Actor
    doctor: Actor


def desk(make_user: Any) -> Desk:
    fin.seed()
    return Desk(
        cashier=actor(make_user, "cash", "cashier"),
        cashier2=actor(make_user, "cash2", "cashier"),
        sup=actor(make_user, "sup", "cashier_supervisor"),
        manager=actor(make_user, "mgr", "manager"),
        accountant=actor(make_user, "acc", "accountant"),
        doctor=actor(make_user, "doc", "doctor"),
    )


@dataclass
class InsuredVisit:
    patient: Patient
    visit: Visit
    payer: Payer
    insured: ServiceLine
    cash_line: ServiceLine


def insured_visit(doctor: User) -> InsuredVisit:
    """A visit on a 70% payer: one 10,000 line (7,000 payer / 3,000 patient) and a 2,000 one."""
    payer = fin.payer(percent="70")
    patient = fin.patient(phone="0912345678", full_name_en="Amna Yousif")
    visit = fin.visit(patient, payer_obj=payer)
    (insured,) = fin.order(visit, doctor, fin.priced("lab", "10000.00"))
    (other,) = fin.order(visit, doctor, fin.priced("procedure", "2000.00"))
    return InsuredVisit(patient, visit, payer, insured, other)


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.content
    return response.json()


def error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body
