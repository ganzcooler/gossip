"""Caption body generation plus deterministic caption composition.

The LLM only writes the short body. The AI disclosure, Organ, session date,
source line, and SessionNet link are added deterministically so the first
caption line is always exact and a missing link can never fail an otherwise
valid post (it becomes a manual-fix hint instead).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from pydantic import BaseModel, ValidationError

from app.core import config
from app.core.post_models import CaptionDraft
from app.core.post_prompts import build_caption_prompt
from app.services.llm_client import LLMAuthenticationError, LLMClient, LLMError

CAPTION_BODY_ROLE = "caption_writer"
CAPTION_FIRST_LINE = "Illustration: KI-generiert."
MANUAL_LINK_HINT = (
    "Hinweis: Der SessionNet-Link fehlt und muss manuell ergänzt werden."
)


class CaptionWriterError(Exception):
    """The caption-body call did not produce a valid CaptionDraft."""


def _german_date(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    return str(value)


async def write_caption_body(
    draft: BaseModel,
    llm: LLMClient,
    *,
    organ: str,
    session_date: date | datetime | str,
    role: str = CAPTION_BODY_ROLE,
) -> CaptionDraft:
    """Generate the caption body from the draft and metadata only."""
    prompt = build_caption_prompt(
        draft=draft, organ=organ, session_date=session_date
    )
    try:
        response = await llm.generate_json(
            role=role, prompt=prompt, schema=CaptionDraft
        )
        if isinstance(response, CaptionDraft):
            return response
        return CaptionDraft.model_validate(response)
    except LLMAuthenticationError:
        raise
    except (LLMError, ValidationError, TypeError, ValueError) as exc:
        raise CaptionWriterError(f"Caption writer failed: {exc}") from exc


def build_protocol_link(
    protocol: Any, *, base_url: str | None = None
) -> str | None:
    """Reconstruct the SessionNet PDF link, or return ``None``.

    The ID is the stored ``getfile_id``; no URL is scraped or guessed. A
    missing ID or an unusable base URL is a manual caption hint, not an error.
    """
    getfile_id = getattr(protocol, "getfile_id", None)
    if getfile_id is None or str(getfile_id).strip() == "":
        return None

    base = config.SESSIONNET_BASE_URL if base_url is None else base_url
    if not base or not str(base).strip():
        return None

    link = urljoin(str(base), f"getfile.asp?id={getfile_id}")
    if not link.startswith(("http://", "https://")):
        return None
    return link


def compose_caption(
    *,
    body: str,
    organ: str,
    session_date: date | datetime | str,
    protocol: Any,
    base_url: str | None = None,
) -> str:
    """Compose the final caption with disclosure, metadata, source and link."""
    date_text = _german_date(session_date)
    link = build_protocol_link(protocol, base_url=base_url)

    blocks = [
        CAPTION_FIRST_LINE,
        f"{organ} · Sitzung vom {date_text}",
        body.strip(),
        f"Quelle: Ratsprotokoll vom {date_text}",
        link if link is not None else MANUAL_LINK_HINT,
    ]
    return "\n\n".join(blocks) + "\n"


__all__ = [
    "CAPTION_BODY_ROLE",
    "CAPTION_FIRST_LINE",
    "MANUAL_LINK_HINT",
    "CaptionWriterError",
    "build_protocol_link",
    "compose_caption",
    "write_caption_body",
]
