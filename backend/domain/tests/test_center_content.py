"""Website content rules (ADR 0029 H): capped bilingual rows, a plain maps link, re-approval of
edited testimonials, and image checks by content."""

from __future__ import annotations

import struct
import zlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.center_content import (
    FACILITIES_MAX,
    FACILITY_ROW,
    REASON_ROW,
    REASONS_MAX,
    approval_lapses_on_edit,
    maps_link,
    parse_rows,
)
from domain.errors import DomainError
from domain.images import MAX_SIDE, inspect_image


def _code(fn, *args) -> str:
    with pytest.raises(DomainError) as exc:
        fn(*args)
    return exc.value.code


# --- rows ---------------------------------------------------------------------------------

_text = st.text(max_size=80)
_facility = st.fixed_dictionaries({"name_ar": _text, "name_en": _text})


@given(st.lists(_facility, max_size=FACILITIES_MAX + 5))
def test_facility_rows_are_capped_and_need_a_name(rows: list[dict[str, str]]) -> None:
    named = all(r["name_ar"].strip() or r["name_en"].strip() for r in rows)
    if len(rows) <= FACILITIES_MAX and named:
        out = parse_rows(rows, FACILITY_ROW)
        assert len(out) == len(rows)
        for got, given_row in zip(out, rows, strict=True):
            assert got == {k: v.strip() for k, v in given_row.items()}
    else:
        assert _code(parse_rows, rows, FACILITY_ROW) == "CENTER_ROWS_INVALID"


def test_reasons_are_at_most_eight() -> None:
    row = {"title_en": "Open late", "text_en": "Until 10 pm"}
    assert len(parse_rows([row] * REASONS_MAX, REASON_ROW)) == REASONS_MAX
    assert _code(parse_rows, [row] * (REASONS_MAX + 1), REASON_ROW) == "CENTER_ROWS_INVALID"


@pytest.mark.parametrize(
    "row",
    [
        {"title_en": "x" * 81},
        {"title_en": "ok", "text_en": "y" * 201},
        {"title_en": "ok", "price": "100"},  # unknown keys are refused, never stored
        {"title_en": 5},
        {"text_en": "no title"},
        "not an object",
    ],
)
def test_bad_reason_rows_are_refused(row: object) -> None:
    assert _code(parse_rows, [row], REASON_ROW) == "CENTER_ROWS_INVALID"


def test_missing_keys_become_empty_text() -> None:
    assert parse_rows([{"title_ar": " لماذا "}], REASON_ROW) == [
        {"title_ar": "لماذا", "title_en": "", "text_ar": "", "text_en": ""}
    ]


# --- maps link ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://maps.google.com/?q=15.5,32.5",
        "https://www.openstreetmap.org/#map=17/15.59/32.53",
        "https://maps.app.goo.gl/abc123",
    ],
)
def test_https_map_links_are_kept(url: str) -> None:
    assert maps_link(f"  {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        "http://maps.google.com/",
        "javascript:alert(1)",
        "https://user:pw@maps.example.com/",
        "https://localhost/",
        "https://maps.example.com:8443/",
        "https://maps.example.com/a b",
        "https://خرائط.example/",
        "https://" + "a" * 500 + ".com",
        "//maps.example.com/",
    ],
)
def test_other_links_are_refused(url: str) -> None:
    assert _code(maps_link, url) == "CENTER_MAPS_URL_INVALID"


@given(st.text(max_size=60))
def test_maps_link_is_total(raw: str) -> None:
    code = None
    out = ""
    try:
        out = maps_link(raw)
    except DomainError as exc:
        code = exc.code
    assert code in {None, "CENTER_MAPS_URL_INVALID"}
    assert out == "" or out.startswith("https://")


def test_empty_maps_link_stays_empty() -> None:
    assert maps_link("   ") == ""


# --- testimonials -------------------------------------------------------------------------

_words = st.fixed_dictionaries(
    {k: st.text(max_size=5) for k in ("text_ar", "text_en", "author_ar", "author_en")}
)


@given(_words, _words)
def test_new_words_need_a_new_approval(before: dict[str, str], after: dict[str, str]) -> None:
    assert approval_lapses_on_edit(before, after) == (before != after)
    assert not approval_lapses_on_edit(before, dict(before))


def test_order_or_visibility_keeps_the_approval() -> None:
    words = {"text_en": "Kind staff", "author_en": "A."}
    assert not approval_lapses_on_edit(
        {**words, "sort_order": 1, "active": True}, {**words, "sort_order": 5, "active": False}
    )


# --- images -------------------------------------------------------------------------------


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(width: int = 2, height: int = 3) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def jpeg(width: int = 4, height: int = 5) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    sos = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"
    return (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 4)
        + b"JF"
        + sof
        + sos
        + b"\x00" * 8
        + b"\xff\xd9"
    )


def webp(width: int = 6, height: int = 7) -> bytes:
    body = b"\x00" * 4 + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    chunk = b"VP8X" + struct.pack("<I", len(body)) + body
    payload = b"WEBP" + chunk + b"\x00" * 8
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def test_real_images_are_read_by_their_bytes() -> None:
    assert inspect_image(png(2, 3)) == inspect_image(png(2, 3))
    p = inspect_image(png(2, 3))
    assert (p.ext, p.content_type, p.width, p.height) == ("png", "image/png", 2, 3)
    j = inspect_image(jpeg(4, 5))
    assert (j.ext, j.content_type, j.width, j.height) == ("jpg", "image/jpeg", 4, 5)
    w = inspect_image(webp(6, 7))
    assert (w.ext, w.content_type, w.width, w.height) == ("webp", "image/webp", 6, 7)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"GIF89a" + b"\x00" * 20,
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,  # a signature with nothing behind it
        png()[:-6],  # cut short
        png()[:20] + b"\xff" + png()[21:],  # a damaged header (CRC)
        jpeg()[:-2],  # no end marker
        webp()[:-1],  # RIFF length does not match
        b"%PDF-1.7\n",
    ],
)
def test_fake_or_damaged_images_are_refused(data: bytes) -> None:
    assert _code(inspect_image, data) == "MEDIA_INVALID_IMAGE"


def test_huge_dimensions_are_refused() -> None:
    assert _code(inspect_image, png(MAX_SIDE + 1, 1)) == "MEDIA_IMAGE_TOO_BIG"


@given(st.binary(max_size=200))
def test_inspection_is_total(data: bytes) -> None:
    code = None
    try:
        info = inspect_image(data)
    except DomainError as exc:
        code = exc.code
    else:
        assert 1 <= info.width <= MAX_SIDE
        assert 1 <= info.height <= MAX_SIDE
    assert code in {None, "MEDIA_INVALID_IMAGE", "MEDIA_IMAGE_TOO_BIG"}


@given(st.binary(max_size=64))
def test_bytes_after_a_png_signature_never_crash(tail: bytes) -> None:
    code = None
    try:
        inspect_image(b"\x89PNG\r\n\x1a\n" + tail)
    except DomainError as exc:
        code = exc.code
    assert code in {"MEDIA_INVALID_IMAGE", "MEDIA_IMAGE_TOO_BIG"}
