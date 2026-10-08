"""pg_trgm and the IMMUTABLE search normalization functions (FEATURES 0.9).

Used by generated columns (patients, payments, claims) and their trigram/btree indexes, and
by queries through ``apps.core.db.NormalizeText`` / ``NormalizePhone`` / ``NormalizeReference``,
so stored values and search terms are folded the same way.

* ``hs_normalize_text``: lower case; Arabic alef/hamza variants to ا, ى and Persian ی to ي,
  ة to ه, ؤ to و, ئ to ي, Persian ک to ك; diacritics (tanween, harakat, shadda, sukun,
  superscript alef) and tatweel removed; Arabic-Indic digits to 0-9; whitespace collapsed.
* ``hs_normalize_phone``: digits only (Arabic-Indic and Persian digits mapped), ``00249`` /
  ``249`` country prefixes folded to the national ``0``.
* ``hs_normalize_reference``: digits mapped, upper case, letters and digits only.
"""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations

# Pairs: from-letter -> to-letter. Characters listed after the pairs are deleted.
_FOLD_FROM = "أإآٱىیةؤئک" + "٠١٢٣٤٥٦٧٨٩" + "۰۱۲۳۴۵۶۷۸۹"
_FOLD_TO = "ااااييهويك" + "0123456789" + "0123456789"
# U+064B..U+0652 harakat/tanween/shadda/sukun, U+0670 superscript alef, U+0640 tatweel.
_DELETE = "".join(chr(c) for c in range(0x064B, 0x0653)) + "ٰـ"

_DIGITS_FROM = "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹"
_DIGITS_TO = "01234567890123456789"

CREATE_SQL = [
    f"""
CREATE OR REPLACE FUNCTION hs_normalize_text(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT btrim(regexp_replace(
        translate(lower(value), '{_FOLD_FROM}{_DELETE}', '{_FOLD_TO}'),
        '\\s+', ' ', 'g'))
$$""",
    f"""
CREATE OR REPLACE FUNCTION hs_normalize_phone(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT CASE
        WHEN d LIKE '00249%' THEN '0' || substr(d, 6)
        WHEN d LIKE '249%' AND length(d) >= 12 THEN '0' || substr(d, 4)
        ELSE d
    END
    FROM (SELECT regexp_replace(translate(value, '{_DIGITS_FROM}', '{_DIGITS_TO}'),
                                '[^0-9]', '', 'g') AS d) AS digits
$$""",
    f"""
CREATE OR REPLACE FUNCTION hs_normalize_reference(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT upper(regexp_replace(translate(value, '{_DIGITS_FROM}', '{_DIGITS_TO}'),
                                '[^0-9A-Za-z]', '', 'g'))
$$""",
]

DROP_SQL = [
    "DROP FUNCTION IF EXISTS hs_normalize_reference(text)",
    "DROP FUNCTION IF EXISTS hs_normalize_phone(text)",
    "DROP FUNCTION IF EXISTS hs_normalize_text(text)",
]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_unset_preferences"),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(CREATE_SQL, DROP_SQL),
    ]
