"""Test-only data builders for the end-to-end suite (ARCHITECTURE 6).

* :mod:`apps.core.e2e.catalog`: the realistic base catalog that ``manage.py seed_e2e`` adds
  next to the seed users (departments, doctors and schedules, services, price lists, payers,
  stock, lab tests, wards and beds, reason codes).
* :mod:`apps.core.e2e.fixtures`: named data builders run by ``manage.py e2e_fixture <name>``.
  They build rows through the services (never by writing models directly), as the user a
  real screen would act as, and print the ids for the Playwright helpers
  (``e2e/helpers/api.ts``).
* :mod:`apps.core.e2e.guard`: both commands refuse any database that is not a throwaway one.

Nothing here is imported by the application itself.
"""
