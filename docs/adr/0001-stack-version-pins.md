# 0001: Stack version pins

Date: 2026-10-06. Status: accepted.

## Context
STACK.md asks for boring, long-supported majors because the system must run unattended in clinics for years. Latest releases at decision time: Django 6.1, TypeScript 7.0, TanStack Table 9.

## Decision
- Django 5.2 LTS (supported to April 2028). django-pghistory and django-pgtrigger are proven on it.
- Python 3.12 via uv.
- TypeScript 5.9 (TypeScript 7 native compiler is new; editor and lint tooling still settling).
- TanStack Table 8 (v9 is a fresh major with API changes).
- React 19, Vite, Tailwind v4, TanStack Router and Query at current stable majors.
- PostgreSQL 16 (matches local and target servers).

## Consequences
Upgrade to Django 6.x LTS and TS 7 is a planned, separate task after the pilot.
Docker is not installed on the development machine: compose files are written and linted but container runs are verified in CI, not locally.
