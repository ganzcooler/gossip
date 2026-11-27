"""Pure prompt builders for the stateless post-pipeline roles.

No I/O happens here; each builder returns one deterministic string. The
provider-facing JSON schema is supplied separately through the LLM port.
Every builder receives only its own step inputs: the planner gets the full
protocol, writers and fact-check get excerpts, and the caption gets metadata.

All prompts are written in English. Reader-facing text roles explicitly ask for
German values; the visual-prompt writer is the deliberate exception and asks
for English image prompts.
"""

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel

from app.core.post_models import (
    SourceExcerpt,
    SummaryBrief,
    SummaryDraft,
    TopicBrief,
    TopicDraft,
)


def _format_date(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)


def _format_german_date(value: date | datetime | str) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _json(value: BaseModel) -> str:
    return value.model_dump_json(indent=2)


def _excerpt_block(excerpts: Sequence[SourceExcerpt]) -> str:
    return "\n\n".join(
        f"[{index}] Anchor: {excerpt.anchor}\nExcerpt: {excerpt.excerpt}"
        for index, excerpt in enumerate(excerpts, start=1)
    )


def _brief_block(briefs: Sequence[SummaryBrief]) -> str:
    return "\n\n".join(
        f"[{index}] Point: {brief.point}\n"
        f"Relevance: {brief.relevance}\n"
        f"Source anchors: {' | '.join(brief.source_anchors)}"
        for index, brief in enumerate(briefs, start=1)
    )


# Shared by the Summary and topic visual-prompt builders so one style change
# cannot drift between the two families.
_PHOTOREALISM_GUARDRAILS = """- Photorealistic editorial and reportage photography with natural light, \
real materials and a believable scene.
- Continuous scene detail into every corner; no empty, flat-colour or white \
areas.
- No illustration, cartoon, drawing, watercolour or 3D render. No fabricated \
documentary evidence.
- No frame, border, passepartout, polaroid edge, picture-in-picture \
composition, collage, split screen or vignette."""


_COVER_SATIRE_INSTRUCTION = """- Give the cover a dry, gently sarcastic, slightly exaggerated editorial \
twist. Exaggerate props, scale or everyday details for visual humour, but keep \
the scene photorealistic, good-natured and free of caricatures of real people."""


def build_planner_prompt(
    *,
    protocol_title: str,
    session_date: date | datetime | str,
    protocol_text: str,
) -> str:
    """Build the editorial-planner prompt from the full protocol text."""
    date_text = _format_date(session_date)
    return f"""You are the editorial planner for Gossip Rosdorf. You read a \
municipal council protocol and plan exactly one Summary post and zero to five \
topic posts from it.

Session: {protocol_title}
Date: {date_text}

## Task

Create an editorial plan with these fields:

- summary_focus: the red thread of the Summary post in one short sentence.
- summary_title: a concrete, local title for the Summary post.
- summary_briefs: 2 to 6 Summary points. Every point has point (what happened), \
relevance (why readers in Rosdorf should care) and at least one source anchor. \
The later Summary cards also receive a one-word kicker; do not plan the kicker \
as its own field yet.
- topic_briefs: 0 to 5 topic briefs, only for topics with real deep-dive value. \
Every topic brief has slug (only [a-z0-9-]+), title, focus, relevance and at \
least one source anchor. Slugs must be unique within the plan.

Source anchors are short, exact quotes from the protocol or precise section \
labels (for example a TOP heading). They must be findable verbatim in the \
protocol so the source retriever can deterministically pull the matching \
excerpts.

## Editorial rules

- Write all reader-facing text values in German, close to the people of \
Rosdorf: factual, local, informative and slightly dry.
- No personal names. Roles, places, numbers and dates are allowed and welcome.
- No party framing, no political judgement, no irony, no exaggeration, no \
clickbait and no emojis.
- Choose only topics that were actually discussed in the protocol. Do not \
invent facts, numbers or resolutions.
- The Summary post gives an overview of the session; topic posts go deeper only \
when there is enough substance.
- The most important Summary point comes first.

## Protocol

{protocol_text}

## Output format

Answer with exactly one JSON object that matches the supplied schema. No \
Markdown, no explanations and no text outside the JSON.
"""


def build_summary_writer_prompt(
    *,
    briefs: Sequence[SummaryBrief],
    excerpts: Sequence[SourceExcerpt],
    feedback: str | None = None,
) -> str:
    """Build the Summary-Writer prompt from Summary briefs and excerpts only."""
    feedback_block = ""
    if feedback:
        feedback_block = f"""
## Correction Note

Your previous draft was rejected:
{feedback}

Deliver a completely new, valid draft. Keep only the facts from the briefs and \
source excerpts.
"""

    return f"""You are the Summary-Writer for Gossip Rosdorf. You write the \
Summary post for one session: a cover title and two to six Summary points.

## Summary briefs

{_brief_block(briefs)}

## Source excerpts

{_excerpt_block(excerpts)}

## Task

- cover_title: a concrete, local title. It is the cover headline and must fit \
the cover (at most 3 lines).
- points: 2 to 6 Summary points in the order of the briefs. The most important \
point comes first.
- Every point has:
  - kicker: a one-word kicker, preferably a German noun, for example Haushalt \
or Radweg.
  - heading: a short, concrete heading.
  - body: 120 to 320 characters including spaces, one continuous paragraph. \
No list, no heading inside the body.

## Editorial rules

- Write all reader-facing values in German, close to the people of Rosdorf: \
factual, local, informative and slightly dry.
- No personal names. Roles, places, numbers and dates are allowed and welcome.
- No party framing, no political judgement, no irony, no exaggeration, no \
clickbait and no emojis.
- Do not invent facts, numbers or resolutions. Rely only on the briefs and the \
source excerpts.
- Write complete sentences. Do not invent abbreviations and do not copy \
verbatim quotes from the excerpts.
- The body is never shortened or rewritten later; keep the 120 to 320 \
characters safely.
{feedback_block}
## Output format

Answer with exactly one JSON object that matches the supplied schema. No \
Markdown, no explanations and no text outside the JSON.
"""


def _topic_brief_block(brief: TopicBrief) -> str:
    return (
        f"Slug: {brief.slug}\n"
        f"Working title: {brief.title}\n"
        f"Focus: {brief.focus}\n"
        f"Relevance: {brief.relevance}\n"
        f"Source anchors: {' | '.join(brief.source_anchors)}"
    )


def build_topic_writer_prompt(
    *,
    brief: TopicBrief,
    excerpts: Sequence[SourceExcerpt],
    feedback: str | None = None,
) -> str:
    """Build the topic-writer prompt from one brief and its excerpts only."""
    feedback_block = ""
    if feedback:
        feedback_block = f"""
## Correction Note

Your previous draft was rejected:
{feedback}

Deliver a completely new, valid draft. Keep only the facts from the brief and \
the source excerpts.
"""

    return f"""You are the topic writer for Gossip Rosdorf. You write exactly \
one topic post about a single topic from a session.

## Topic brief

{_topic_brief_block(brief)}

## Source excerpts

{_excerpt_block(excerpts)}

## Task

Write a complete article with exactly this structure:

- title: the article headline (H1) with 20 to 100 characters including spaces. \
It is also the cover title.
- sections: 2 to 6 topic sections. Every section has:
  - h2: the section heading with 20 to 60 characters including spaces.
  - paragraphs: a non-empty list of complete paragraphs. There is no upper \
limit for individual paragraphs.

There is no lead, no summary, no takeaway list, no kicker field and no other \
field. The entire article text from H1, H2 and paragraphs may contain at most \
3000 characters including spaces.

## Design and content rules

- Write all reader-facing values in German, close to the people of Rosdorf: \
informative, local, factual and slightly dry.
- No personal names. Roles, places, numbers and dates are allowed and welcome.
- No party framing, no political judgement, no irony, no exaggeration, no \
clickbait and no emojis.
- Do not invent facts, numbers or resolutions. Rely only on the brief and the \
source excerpts.
- Every H2 later starts a new slide; overlong paragraphs continue on follow \
slides. Therefore write complete paragraphs without manual slide breaks and \
without Markdown.
- After layout the article should produce three to seven content slides. Keep \
the text correspondingly compact and spread it across two to six sections.
{feedback_block}
## Output format

Answer with exactly one JSON object that matches the supplied schema. No \
Markdown, no explanations and no text outside the JSON.
"""


def build_fact_check_prompt(
    *, draft: BaseModel, excerpts: Sequence[SourceExcerpt]
) -> str:
    """Build the fact-check prompt from a draft and its excerpts only."""
    return f"""You are the fact checker for Gossip Rosdorf. You check a draft \
exclusively against the supplied source excerpts.

## Draft

```json
{_json(draft)}
```

## Source excerpts

{_excerpt_block(excerpts)}

## Task

Check every statement in the draft: names, roles, places, numbers, dates, \
resolutions and effects. Report only concrete problems that the source excerpts \
can prove:

- unsupported or incorrect statements,
- disallowed personal names, party framing, irony, exaggeration, clickbait or \
emojis,
- structure or budget violations that are visible in the draft.

Every issue must be a complete, actionable correction note written in German. \
If everything is supported and compliant, return an empty list. Do not make \
general remarks or recommendations without a concrete error.

## Output format

Answer with exactly one JSON object containing the field issues. No Markdown, \
no explanations and no text outside the JSON.
"""


def build_repair_prompt(
    *,
    draft: BaseModel,
    issues: Sequence[str],
    excerpts: Sequence[SourceExcerpt],
) -> str:
    """Build the one repair prompt from the draft, issues and excerpts only."""
    issue_block = "\n".join(f"- {issue}" for issue in issues)
    return f"""You are the repair step for Gossip Rosdorf. Correct the draft \
minimally and only on the basis of the reported problems and source excerpts.

## Draft

```json
{_json(draft)}
```

## Reported problems

{issue_block}

## Source excerpts

{_excerpt_block(excerpts)}

## Rules

- Fix every reported problem. Do not invent new facts, numbers or resolutions.
- Keep the structure and every unaffected formulation.
- Remove personal names, party framing, irony, exaggeration, clickbait and \
emojis.
- Shorten or extend the text only as far as the problems and the schema require.
- Return the complete corrected draft, not only the changes.
- All reader-facing text in the corrected draft must be German.

## Output format

Answer with exactly one JSON object that matches the supplied schema. No \
Markdown, no explanations and no text outside the JSON.
"""


def build_caption_prompt(
    *,
    draft: BaseModel,
    organ: str,
    session_date: date | datetime | str,
) -> str:
    """Build the caption-body prompt from the draft and metadata only."""
    return f"""You are the caption writer for Gossip Rosdorf. Write the plain \
text of the Instagram caption for an already finished post.

## Metadata

- Organ: {organ}
- Session date: {_format_german_date(session_date)}

## Draft

```json
{_json(draft)}
```

## Task

- Write one to three short sentences as the caption body: what happened and why \
it matters for Rosdorf?
- Use only facts from the draft. Do not invent anything.
- Write the caption body in German.
- No personal names, no party framing, no political judgement, no irony, no \
exaggeration, no clickbait and no emojis.
- No source link, no source note and no AI note; those parts are added \
deterministically.
- No hashtags.

## Output format

Answer with exactly one JSON object containing the field body. No Markdown, no \
explanations and no text outside the JSON.
"""


def build_topic_visual_prompt(
    draft: TopicDraft,
    pair_count: int,
    *,
    has_single: bool = False,
    feedback: str | None = None,
) -> str:
    """Build the topic visual-prompt prompt from the topic draft only.

    The writer gets the immutable article draft and the number of artwork
    prompts needed for the pair grid. If the content slide count is odd, it
    also writes exactly one prompt for the central 360x1350 single strip.
    """
    if pair_count < 1:
        raise ValueError("pair_count must be at least 1")

    single_count = 1 if has_single else 0
    total_prompts = 1 + pair_count + single_count
    artwork_word = "prompt" if pair_count == 1 else "prompts"
    single_phrase = (
        "1 single_prompt for the unpaired last slide"
        if has_single
        else "0 single_prompt values (set single_prompt to null)"
    )
    single_feedback = (
        " and a non-empty single_prompt"
        if has_single
        else ""
    )

    feedback_block = ""
    if feedback:
        feedback_block = f"""
## Correction Note

Your previous attempt was rejected:
{feedback}

Deliver completely new, valid image prompts. The JSON object must contain \
exactly {total_prompts} image prompts: 1 cover_prompt, {pair_count} \
artwork_prompts{single_feedback}. Every artwork prompt must describe one \
continuous photograph and must not mention seams, panels, splits, halves, \
diptychs, triptychs or left/right portions. Each artwork prompt produces a \
separate image; do not combine two pair scenes into one prompt.
"""

    single_task = ""
    single_guardrail = ""
    prompt_values = "cover_prompt and artwork_prompts values"
    if has_single:
        prompt_values = (
            "cover_prompt, artwork_prompts and single_prompt values"
        )
        single_task = (
            "\n- single_prompt: an English-only prompt for the last, odd "
            "slide. The image is 4:5; keep all important motifs in the middle "
            "third of the frame because the outer areas may be cropped. "
            "Describe one continuous scene."
        )
        single_guardrail = (
            "\n- The single_prompt must describe one continuous scene with a "
            "complete, detailed middle; no calm, empty or deliberately cleared "
            "area and no visible centre panel."
        )

    return f"""You are the visual-prompt writer for Gossip Rosdorf. You write \
image prompts for the cover and the artwork of a topic post.

## Topic draft

```json
{_json(draft)}
```

## Required output

Return exactly {total_prompts} image prompts in the JSON object:
- 1 cover_prompt.
- {pair_count} artwork_{artwork_word}, one separate prompt per 4:5 image pair.
- {single_phrase}.

Every artwork prompt is a separate image. Do not combine the scenes of two \
image pairs into one prompt.

## Task

- cover_prompt: an English-only prompt for the cover in 4:5 feed format. The \
cover later carries the title, logo, organ badge and kicker. Give the cover a \
dry, gently sarcastic, slightly exaggerated editorial twist: exaggerate props, \
scale or everyday details for visual humour, but keep the scene photorealistic, \
good-natured and free of caricatures of real people.
- artwork_prompts: exactly {pair_count} separate {artwork_word}, one per 4:5 \
artwork pair. Every prompt must describe one ordinary, uninterrupted photograph \
with a single continuous scene. Do not describe separate panels, halves or a \
diptych within one prompt, and do not combine multiple pair scenes into one \
prompt. The renderer performs any later cropping invisibly.{single_task}
- All {prompt_values} must be English only.

## Design guardrails

{_PHOTOREALISM_GUARDRAILS}
- A lively, believable civic scene with a continuous horizon and natural \
texture, matching the article topic and a municipal council session in Rosdorf.
- Adults of different ages may appear naturally, including in the foreground. \
Candid, everyday moments are welcome. Do not show recognizable minors.
- Text, letters, numbers, signs, documents, displays, logos, coats of arms and \
lettering that naturally belong to the scene are allowed. Do not add blanket \
bans such as "no logos", "no coats of arms" or "no lettering"; scene logos, \
coats of arms and lettering are expressly allowed.
- People may appear only as fictional adults who fit naturally into the scene. \
Do not depict recognizable real politicians or public figures, party symbols \
or campaign branding.
- Keep faces and key subjects away from the extreme outer edges. Leave calm, \
naturally textured space for the logo, title and organ badge, but do not empty \
the scene for it.
- Every artwork prompt must be one single continuous photograph. Keep \
important motifs away from the extreme outer edges of the 4:5 frame. Do not add \
a vertical divider or any composition that looks like two separate pictures.
- 4:5 feed composition.
- No added graphic overlays, watermarks or composited branding; branding comes \
exclusively from the renderer.
{single_guardrail}
- No added text that looks like a layout element, caption bar or UI overlay.
{feedback_block}
## Output format

Answer with exactly one JSON object that matches the supplied schema. No \
Markdown, no explanations and no text outside the JSON.
"""


def build_summary_visual_prompt(draft: SummaryDraft) -> str:
    """Build the Summary visual-prompt prompt from the Summary draft only."""
    return f"""You are the visual-prompt writer for Gossip Rosdorf. You write \
exactly one image prompt for the cover of the Summary post.

## Summary draft

```json
{_json(draft)}
```

## Task

- Return exactly one image prompt: cover_prompt. The Summary cards reuse this \
cover image.
- cover_prompt: an English-only prompt for photorealistic editorial and \
reportage photography in 9:16 story format.
- The cover_prompt must be English only.

## Design guardrails

{_PHOTOREALISM_GUARDRAILS}
- A lively, believable civic scene with a continuous horizon and natural \
texture, fitting a municipal council session in Rosdorf.
- Adults of different ages may appear naturally, including in the foreground. \
Candid, everyday moments are welcome. Do not show recognizable minors.
- Text, letters, numbers, signs, documents, displays, logos, coats of arms and \
lettering that naturally belong to the scene are allowed. Do not add blanket \
bans such as "no logos", "no coats of arms" or "no lettering"; scene logos, \
coats of arms and lettering are expressly allowed.
- People may appear only as fictional adults who fit naturally into the scene. \
Do not depict recognizable real politicians or public figures, party symbols \
or campaign branding.
- Keep faces and key subjects away from the extreme frame edges. Leave calm, \
naturally textured space for the logo, title and organ badge, but do not empty \
the scene for it.
- 9:16 story composition; no critical content at the very edge.
- No added graphic overlays, watermarks or composited branding; branding comes \
exclusively from the renderer.
{_COVER_SATIRE_INSTRUCTION}

## Output format

Answer with exactly one JSON object that matches the supplied schema. No \
Markdown, no explanations and no text outside the JSON.
"""
