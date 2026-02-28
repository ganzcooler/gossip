# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

A FastAPI-based automation system that generates journalistic blog posts and Instagram content from city council meeting protocols (PDFs). Uses Google GenAI (Gemini & Imagen) for content generation.

## Architecture

**Unified Structure:**
- `app/` - FastAPI application with async SQLAlchemy, APScheduler, PostgreSQL
- `app/core/` - Core configuration, models, prompts, and tags
- `app/services/` - Business logic including article/image generation and Instagram content creation
- `app/api/` - API routes including manual pipeline triggers

**Key Pattern:** Synchronous AI operations run in thread pools via `asyncio.get_event_loop().run_in_executor()`

## Commands

```bash
# Docker deployment
pip install -r requirements.txt   # Install deps
docker network create traefik     # Required before compose
docker-compose up -d              # Start app + postgres
```

## API Endpoints

**Pipeline Triggers (Manual):**
- `POST /api/pipeline/fetch` - Fetch protocols from SessionNet
- `POST /api/pipeline/process` - Process unprocessed protocols
- `POST /api/pipeline/run` - Run full pipeline (fetch + process)
- `GET /api/pipeline/status` - Get pipeline status

**Data Endpoints:**
- `GET /api/health` - Health check
- `GET /api/protocols` - List protocols
- `GET /api/protocols/{id}` - Get specific protocol
- `GET /api/protocols/{id}/articles` - Get articles for protocol
- `GET /api/stats` - System statistics

## Critical Conventions

**Directory Structure:**
- `app/` uses absolute paths (`/app/articles`, `/app/logs`) for Docker bind mounts
- `res/` directory contains fonts and logo for Instagram image generation

**Async/Sync Pattern:**
- AI generation functions in `app/services/` are synchronous
- Must be wrapped with `asyncio.get_event_loop().run_in_executor()` for FastAPI use
- See `app/services/protocol_processor.py` for examples

**Scheduler Jobs:**
- Fetch protocols: 10:00 & 17:00 daily
- Process protocols: 10:30 & 17:30 daily
- Jobs auto-start with FastAPI lifespan events
- Can also be triggered manually via API endpoints

**AI Model Configuration:**
- Article generation: `gemini-3-pro-preview`
- Image prompt: `gemini-2.5-flash`
- Image generation: `gemini-2.5-flash-image` (4:5 aspect ratio)

## Environment

Copy `.env.example` to `.env`. Required vars:
- `GOOGLE_API_KEY` - Required for all AI operations
- `DATABASE_URL` - PostgreSQL connection (asyncpg format)
- `SESSIONNET_BASE_URL` - Source for council protocols

## Testing

No test framework configured. Project lacks automated tests.
