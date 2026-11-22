"""Behaviour tests for caption-body generation and deterministic composition."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.post_models import CaptionDraft, SummaryDraft
from app.services.caption_writer import (
    CAPTION_FIRST_LINE,
    MANUAL_LINK_HINT,
    CaptionWriterError,
    build_protocol_link,
    compose_caption,
    write_caption_body,
)
from app.services.llm_client import LLMSchemaError
from tests.support.fake_llm import FakeLLMClient

PROTOCOL_TEXT = "TOP 5 Haushalt\nDer Rat beschließt den Haushalt einstimmig.\n"


def _draft() -> SummaryDraft:
    return SummaryDraft(
        cover_title="Was der Rat in Rosdorf entschieden hat",
        points=[
            {
                "kicker": "Haushalt",
                "heading": "Der Rat hat den Haushalt beschlossen",
                "body": "x" * 120,
            },
            {
                "kicker": "Radweg",
                "heading": "Der Radweg kommt im Sommer",
                "body": "y" * 120,
            },
        ],
    )


async def test_caption_body_writer_gets_the_draft_and_metadata_only():
    fake = FakeLLMClient(
        json_responses={
            "caption_writer": [
                CaptionDraft(body="Der Rat hat den Haushalt beschlossen.")
            ]
        }
    )

    result = await write_caption_body(
        _draft(),
        fake,
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 1, 15),
    )

    assert result.body == "Der Rat hat den Haushalt beschlossen."
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.role == "caption_writer"
    assert call.schema is CaptionDraft
    assert "Gemeinderat Rosdorf" in call.prompt
    assert "15.01.2024" in call.prompt
    assert _draft().cover_title in call.prompt
    assert PROTOCOL_TEXT not in call.prompt


async def test_caption_body_writer_raises_a_clear_error_on_schema_failure():
    fake = FakeLLMClient(
        json_responses={"caption_writer": [LLMSchemaError("bad caption JSON")]}
    )

    with pytest.raises(CaptionWriterError, match="caption"):
        await write_caption_body(
            _draft(),
            fake,
            organ="Gemeinderat Rosdorf",
            session_date=date(2024, 1, 15),
        )


def test_protocol_link_is_reconstructed_from_the_getfile_id():
    protocol = SimpleNamespace(getfile_id=4711)

    link = build_protocol_link(
        protocol, base_url="https://sessionnet.example/rosdorf/BI/"
    )

    assert link == "https://sessionnet.example/rosdorf/BI/getfile.asp?id=4711"


@pytest.mark.parametrize("getfile_id", [None, ""])
def test_protocol_link_is_none_without_a_getfile_id(getfile_id):
    protocol = SimpleNamespace(getfile_id=getfile_id)

    assert build_protocol_link(protocol) is None


def test_composed_caption_starts_with_the_ai_label_and_contains_source_and_link():
    protocol = SimpleNamespace(getfile_id=4711)
    caption = compose_caption(
        body="Der Rat hat den Haushalt beschlossen.",
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 1, 15),
        protocol=protocol,
        base_url="https://sessionnet.example/rosdorf/BI/",
    )

    lines = caption.splitlines()
    assert lines[0] == CAPTION_FIRST_LINE
    assert caption.startswith("Bild: KI-generiert.\n")
    assert "Illustration: KI-generiert." not in caption
    assert "Gemeinderat Rosdorf" in caption
    assert "15.01.2024" in caption
    assert "Ratsprotokoll vom 15.01.2024" in caption
    assert (
        "https://sessionnet.example/rosdorf/BI/getfile.asp?id=4711" in caption
    )
    assert "Der Rat hat den Haushalt beschlossen." in caption
    assert MANUAL_LINK_HINT not in caption


def test_missing_link_keeps_the_caption_successful_with_a_manual_hint():
    protocol = SimpleNamespace(getfile_id=None)
    caption = compose_caption(
        body="Der Rat hat den Haushalt beschlossen.",
        organ="Gemeinderat Rosdorf",
        session_date=date(2024, 1, 15),
        protocol=protocol,
    )

    assert caption.startswith(f"{CAPTION_FIRST_LINE}\n")
    assert "Gemeinderat Rosdorf" in caption
    assert "Ratsprotokoll vom 15.01.2024" in caption
    assert MANUAL_LINK_HINT in caption
    assert "http" not in caption
