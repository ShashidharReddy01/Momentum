"""Rich text sanitizing, text extraction and hashing (core/richtext.py)."""

from __future__ import annotations

import pytest

from momentum.core.errors import ValidationFailed
from momentum.core.richtext import doc_hash, plain_text, preview, sanitize_doc


def doc(*content: dict) -> dict:  # type: ignore[type-arg]
    return {"type": "doc", "content": list(content)}


def para(text: str, **mark: object) -> dict:  # type: ignore[type-arg]
    node: dict = {"type": "text", "text": text}  # type: ignore[type-arg]
    if mark:
        node["marks"] = [mark]
    return {"type": "paragraph", "content": [node]}


def test_keeps_supported_content_and_extracts_text() -> None:
    d = doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Plan"}]},
        {
            "type": "taskList",
            "content": [
                {"type": "taskItem", "attrs": {"checked": True}, "content": [para("Draft")]},
                {"type": "taskItem", "attrs": {"checked": 0}, "content": [para("Review")]},
            ],
        },
        para("see docs", type="link", attrs={"href": "https://example.test/x"}),
    )
    clean = sanitize_doc(d)
    assert clean is not None
    assert clean["content"][1]["content"][1]["attrs"] == {"checked": False}
    assert plain_text(clean) == "Plan\nDraft\nReview\nsee docs"
    assert preview(clean, 12) == "Plan Draft …"


@pytest.mark.parametrize(
    "href", ["javascript:alert(1)", " JAVASCRIPT:x", "data:text/html,x", "vbscript:x", 42]
)
def test_unsafe_links_are_dropped_but_text_kept(href: object) -> None:
    clean = sanitize_doc(doc(para("click", type="link", attrs={"href": href})))
    assert clean == doc({"type": "paragraph", "content": [{"type": "text", "text": "click"}]})


def test_unknown_attrs_and_marks_are_removed() -> None:
    clean = sanitize_doc(
        doc(
            {
                "type": "paragraph",
                "attrs": {"style": "x"},
                "content": [
                    {"type": "text", "text": "a", "marks": [{"type": "bold"}, {"type": "script"}]}
                ],
            }
        )
    )
    assert clean == doc(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "a", "marks": [{"type": "bold"}]}],
        }
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "paragraph"},
        {"type": "doc", "content": [{"type": "iframe"}]},
        {"type": "doc", "content": "x"},
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 7}}]},
        "text",
    ],
)
def test_invalid_documents_are_rejected(bad: object) -> None:
    with pytest.raises(ValidationFailed):
        sanitize_doc(bad)


def test_limits() -> None:
    deep: dict = {"type": "paragraph"}  # type: ignore[type-arg]
    for _ in range(40):
        deep = {"type": "blockquote", "content": [deep]}
    with pytest.raises(ValidationFailed):
        sanitize_doc(doc(deep))
    with pytest.raises(ValidationFailed):
        sanitize_doc(doc(para("x" * 300_000)))


def test_empty_documents_become_none_and_hash_is_stable() -> None:
    assert sanitize_doc(doc({"type": "paragraph"})) is None
    assert sanitize_doc(doc(para("   "))) is None
    assert sanitize_doc(None) is None
    a = sanitize_doc(doc(para("hi")))
    b = {
        "content": [{"content": [{"text": "hi", "type": "text"}], "type": "paragraph"}],
        "type": "doc",
    }
    assert doc_hash(a) == doc_hash(b) != "" and doc_hash(None) == ""
