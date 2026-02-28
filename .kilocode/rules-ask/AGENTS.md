# AGENTS.md - Ask Mode

This file provides guidance to agents when answering questions about this repository.

## Documentation Context

**Key Documentation Files:**
- `README.md` - Architecture overview, deployment instructions
- `GEMINI.md` - Detailed workflow for AI content generation
- `plans/containerization-plan.md` - Migration from standalone to FastAPI

**Project Structure Clarifications:**
- `app/` = FastAPI web application (new, containerized)
- `src/` = Legacy standalone pipeline (still functional)
- Both can write to same directories but shouldn't run simultaneously

**Content Generation Flow:**
1. SessionNet → Protocol fetcher (`app/services/protocol_fetcher.py`)
2. PDF text → Article generation (`src/pipeline_steps/generate_articles.py`)
3. Article → Image prompt → Image generation (4:5 aspect ratio)
4. Image + Headline + Logo → Instagram-ready image (`src/insta_images.py`)
5. Article → Instagram caption

**AI Prompts:**
- German-language journalistic prompts in `src/prompts.py`
- Tone: slightly ironic, local news style
- Output: HTML format articles

**API Endpoints:**
- `GET /api/health` - Health check
- `GET /api/protocols` - List protocols (query: `processed=true/false`)
- `GET /api/protocols/{id}` - Single protocol details

**No Test Framework:**
- Project lacks automated tests
- Manual testing via `python main.py --steps`