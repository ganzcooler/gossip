# Gossip Project

This project is a Python-based pipeline designed to automate the creation of journalistic-style blog posts and associated images from PDF documents. It is tailored for generating local news content from official documents like city council meeting minutes.

The system now runs as a containerized FastAPI application with automated scheduling, PostgreSQL database, and web-based API.

## Architecture

```
┌─────────────────┐     ┌─────────────────────────────────────────┐
│  Cloudflare     │────▶│  Traefik Reverse Proxy (HTTPS)          │
│  Tunnel         │     └─────────────────────────────────────────┘
└─────────────────┘                          │
                                             ▼
                              ┌──────────────────────────────┐
                              │  FastAPI Application         │
                              │  - APScheduler (Cron Jobs)   │
                              │  - Protocol Fetcher          │
                              │  - Protocol Processor        │
                              │  - REST API                  │
                              └──────────────────────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
           ┌─────────────┐         ┌─────────────────┐    ┌─────────────────┐
           │  PostgreSQL │         │  Bind Mounts    │    │  SessionNet     │
           │  Database   │         │  - articles/    │    │  (External)     │
           └─────────────┘         │  - generated_   │    └─────────────────┘
                                   │    images/      │
                                   │  - insta_images/│
                                   │  - logs/        │
                                   └─────────────────┘
```

## Core Workflow

### Automated Pipeline (Scheduled)
1. **Protocol Fetching** (10:00 & 17:00 daily): Fetches new protocols from SessionNet
2. **Duplicate Detection**: Checks for similar protocols (95% similarity threshold) in the last 3 months
3. **Protocol Processing** (10:30 & 17:30 daily): Generates articles, images, and Instagram posts

### Manual Pipeline (Legacy)
The original standalone pipeline is still available:
1. **PDF Ingestion:** Processes PDF files from the `pdf_files/` directory
2. **Text Extraction:** Text is extracted using `PyMuPDF`
3. **AI Article Generation:** Google GenAI (`gemini-2.5-pro`) generates journalistic articles
4. **AI Image Generation:** `gemini-2.5-flash` creates prompts, `imagen-3.0-generate-002` generates images
5. **Instagram Formatting:** Images cropped to 4:5 with headline overlay and logo

## Key Technologies
- **Backend:** Python, FastAPI, SQLAlchemy (async)
- **Database:** PostgreSQL 16 with Alembic migrations
- **Scheduler:** APScheduler (cron-based)
- **Containerization:** Docker, Docker Compose, Traefik
- **AI:** Google GenAI (Gemini & Imagen)
- **PDF Processing:** PyMuPDF
- **Image Manipulation:** Pillow
- **HTTP Client:** httpx

## Project Structure

```
.
├── app/                          # FastAPI Application
│   ├── main.py                   # Entry point with lifespan events
│   ├── config.py                 # Configuration management
│   ├── database.py               # SQLAlchemy async setup
│   ├── models.py                 # Database models (Protocol, Article)
│   ├── scheduler.py              # APScheduler configuration
│   ├── logging_config.py         # Logging setup
│   ├── api/
│   │   └── routes.py             # REST API endpoints
│   ├── services/
│   │   ├── protocol_fetcher.py   # SessionNet integration
│   │   ├── protocol_processor.py # Article generation
│   │   └── duplicate_detector.py # Similarity detection
│   └── utils/
│       ├── folder_utils.py       # Directory management
│       └── sessionnet.py         # SessionNet utilities
├── src/                          # Legacy pipeline (still functional)
├── alembic/                      # Database migrations
├── Dockerfile
├── docker-compose.yaml
├── requirements.txt
└── .env.example
```

## Deployment (Docker)

### 1. Prerequisites
- Docker and Docker Compose installed
- External Traefik network created:
  ```bash
  docker network create traefik
  ```

### 2. Configuration
Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
# Edit .env with your values
```

Required environment variables:
```
# Database
DB_HOST=postgres
DB_PORT=5432
DB_NAME=gossip
DB_USER=gossip_user
DB_PASSWORD=secure_password

# API Keys
GOOGLE_API_KEY=your_google_api_key

# SessionNet
SESSIONNET_BASE_URL=https://sessionnet.owl-it.de/rosdorf/BI/

# Traefik
TRAEFIK_HOST=gossip.yourdomain.com

# Logging
LOG_LEVEL=INFO
```

### 3. Start the Application
```bash
docker-compose up -d
```

The application will:
- Start PostgreSQL database
- Run database migrations automatically
- Start the FastAPI application on port 8000
- Begin scheduled jobs (protocol fetching at 10:00/17:00, processing at 10:30/17:30)

### 4. API Endpoints
- `GET /` - Application info
- `GET /api/health` - Health check
- `GET /api/protocols` - List protocols (with pagination and filter)
- `GET /api/protocols/{id}` - Get specific protocol
- `GET /api/protocols/{id}/articles` - Get articles for a protocol
- `GET /api/stats` - System statistics
- `GET /docs` - Swagger UI documentation

## Development (Local)

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Database Setup
Start PostgreSQL locally or use Docker:
```bash
docker run -d --name postgres \
  -e POSTGRES_DB=gossip \
  -e POSTGRES_USER=gossip_user \
  -e POSTGRES_PASSWORD=secure_password \
  -p 5432:5432 postgres:16
```

Run migrations:
```bash
alembic upgrade head
```

### 3. Run the Application
```bash
uvicorn app.main:app --reload
```

## Legacy Manual Pipeline

The original standalone pipeline is still available via `main.py`:

- **Run full pipeline:**
  ```bash
  python main.py
  ```

- **Run specific steps:**
  ```bash
  python main.py --steps
  ```

## Scheduler Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| fetch_protocols | 10:00 & 17:00 | Fetch new protocols from SessionNet |
| process_protocols | 10:30 & 17:30 | Process unprocessed protocols |

## Security Notes
- PostgreSQL is only accessible within the internal Docker network
- No database ports are exposed externally
- HTTPS is enforced via Traefik/Cloudflare
- Secrets are managed via `.env` file (never commit to git)
