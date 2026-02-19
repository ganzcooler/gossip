# AGENTS.md - Code Mode

This file provides guidance to agents when working with code in this repository.

## Code-Specific Rules

**Async/Sync Bridge Pattern:**
- Pipeline steps in `src/pipeline_steps/` are synchronous and MUST be wrapped for FastAPI
- Use pattern from [`app/services/pipeline_adapter.py`](app/services/pipeline_adapter.py:23):
  ```python
  loop = asyncio.get_event_loop()
  result = await loop.run_in_executor(None, sync_function, args)
  ```

**Path Handling:**
- `app/` uses absolute paths (`/app/articles`) for Docker bind mounts
- `src/` uses `PROJECT_ROOT` relative paths for local execution
- Never mix the two path systems in the same context

**Database Models:**
- SQLAlchemy models in [`app/models.py`](app/models.py:1) use explicit indexes via `__table_args__`
- Foreign keys use `ondelete="CASCADE"` for proper cleanup
- Relationships use `back_populates` for bidirectional access

**AI Model Names:**
- Article generation: `gemini-3-pro-preview`
- Image prompt: `gemini-2.5-flash`
- Image generation: `gemini-2.5-flash-image` (4:5 aspect ratio required)

**Pipeline Steps (synchronous in src/):**
- [`src/pipeline_steps/generate_articles.py`](src/pipeline_steps/generate_articles.py:1) - Returns `List[SingleArticle]`
- [`src/pipeline_steps/generate_image.py`](src/pipeline_steps/generate_image.py:1) - Returns bytes
- [`src/pipeline_steps/generate_insta_caption.py`](src/pipeline_steps/generate_insta_caption.py:1) - Returns string

**Instagram Image Formatting:**
- Uses 4:5 aspect ratio (no cropping needed)
- [`src/insta_images.py`](src/insta_images.py:1) overlays headline + logo
- Fonts loaded from `res/` directory