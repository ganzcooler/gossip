import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# Database
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "gossip")
DB_USER = os.getenv("DB_USER", "gossip_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "secure_password")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# API Keys
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# SessionNet
SESSIONNET_BASE_URL = os.getenv(
    "SESSIONNET_BASE_URL",
    "https://sessionnet.owl-it.de/rosdorf/BI/"
)

# Traefik
TRAEFIK_HOST = os.getenv("TRAEFIK_HOST", "gossip.localhost")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Directories (for bind mounts)
ARTICLES_DIR = Path("/app/articles")
GENERATED_IMAGES_DIR = Path("/app/generated_images")
INSTA_IMAGES_DIR = Path("/app/insta_images")
LOGS_DIR = Path("/app/logs")