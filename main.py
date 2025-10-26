import sys
from src.pipeline import run_pipeline
from src.config import PROJECT_ROOT

if __name__ == "__main__":
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        print("ERROR: .env file not found in the project root.", file=sys.stderr)
        print("Please create a .env file and add your GOOGLE_API_KEY.", file=sys.stderr)
        sys.exit(1)
    
    run_pipeline()