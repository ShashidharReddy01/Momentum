"""Phase 7.5 S75-02 (spec §4.6, §11.2): bombs refused fast, encryption detected, the timeout
respected, EXIF stripped, and nothing in a file ever executed."""

from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
import time

import pytest
from PIL import Image

from momentum.files import cache
from momentum.files.parse import parse_bytes
from momentum.files.render import LONG_EDGE, render_image, render_pdf_page
from momentum.files.safety import UnsafeFile, check_image_header
from tests.conftest import make_settings
from tests.fixtures.files import build


@pytest.mark.parametrize(
    ("builder", "name", "mime", "warning"),
    [
        (build.zip_bomb_ratio, "bomb.xlsx", "application/octet-stream", "zip bomb"),
        (build.zip_bomb_declared, "bomb.zip", "application/zip", "more than 250 MB"),
        (build.docx_xml_bomb, "lol.docx", "application/octet-stream", "XML declarations"),
        (build.xml_bomb, "lol.xml", "application/xml", "entities"),
    ],
)
def test_bombs_are_refused_fast(builder, name: str, mime: str, warning: str) -> None:  # type: ignore[no-untyped-def]
    data = builder()
    t = time.monotonic()
    r = parse_bytes(data, name, mime)
    assert time.monotonic() - t < 2
    assert r.status == "failed"
    assert any(warning in w for w in r.model.file.warnings), r.model.file.warnings


def test_encrypted_files_are_reported_never_unlocked() -> None:
    for data, name in (
        (build.pdf_encrypted(), "locked.pdf"),
        (build.xlsx_encrypted(), "locked.xlsx"),
    ):
        r = parse_bytes(data, name, "application/octet-stream")
        assert r.status == "encrypted"
        assert r.model.file.encrypted
        assert any("password" in w and "without a password" in w for w in r.model.file.warnings)
        assert not r.model.blocks and not r.model.sheets


async def test_the_parse_timeout_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*_a: object, **_k: object) -> None:
        time.sleep(1.5)

    monkeypatch.setattr(cache, "parse_bytes", slow)
    settings = make_settings(file_parse_timeout_s=0.2)
    src = cache.FileSource(
        workspace_id=__import__("uuid").uuid4(),
        storage_key="x",
        filename="big.xlsx",
        mime="application/octet-stream",
        size=1,
    )
    t = time.monotonic()
    r = await cache.parse_with_timeout(b"data", src, settings)
    assert time.monotonic() - t < 1.0
    assert r.status == "failed" and cache.TIMEOUT_MESSAGE in r.model.file.warnings
    await asyncio.sleep(1.4)  # let the abandoned worker thread finish before the next test


def test_rendering_strips_exif_and_caps_size() -> None:
    src = build.png_with_exif()
    assert Image.open(io.BytesIO(src)).getexif()  # the sample really carries EXIF
    out = render_image(src)
    im = Image.open(io.BytesIO(out.jpeg))
    assert im.format == "JPEG"
    assert not im.getexif()
    assert "exif" not in im.info and "icc_profile" not in im.info
    big = Image.new("RGB", (4000, 1000), (10, 20, 30))
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    r = render_image(buf.getvalue())
    assert (r.width, r.height) == (LONG_EDGE, 392)
    page = render_pdf_page(build.pdf_contract(), 1)
    assert max(page.width, page.height) <= LONG_EDGE and page.locator == "p1"


def test_images_over_40_megapixels_are_refused_from_the_header() -> None:
    huge = Image.new("1", (8000, 6000))
    buf = io.BytesIO()
    huge.save(buf, format="PNG")
    with pytest.raises(UnsafeFile):
        check_image_header(buf.getvalue())
    r = parse_bytes(buf.getvalue(), "huge.png", "image/png")
    assert r.status == "failed" and any("40-megapixel" in w for w in r.model.file.warnings)


def test_nothing_is_ever_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Macros with Shell, downloads and file writes are read and described; no process starts and
    no Office automation is loaded."""
    calls: list[str] = []

    def refuse(name: str):  # type: ignore[no-untyped-def]
        def _f(*_a: object, **_k: object) -> None:
            calls.append(name)
            raise AssertionError(f"{name} called while reading a file")

        return _f

    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess.Popen"))
    monkeypatch.setattr(os, "system", refuse("os.system"))
    monkeypatch.setattr(os, "popen", refuse("os.popen"))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", refuse("os.startfile"))
    for data, name in (
        (build.docm_with_macro(), "macro.docm"),
        (build.xlsm_with_macro(), "macro.xlsm"),
        (build.csv_semicolon(), "formula.csv"),
        (build.pdf_contract(), "contract.pdf"),
    ):
        r = parse_bytes(data, name, "application/octet-stream")
        assert r.status == "ok", (name, r.error)
    assert calls == []
    assert not any(m.startswith(("win32com", "pythoncom", "comtypes")) for m in sys.modules)
    macro = parse_bytes(build.docm_with_macro(), "macro.docm", "x").model.macros
    assert any("Shell" in m.code for m in macro.modules)  # reported as text
