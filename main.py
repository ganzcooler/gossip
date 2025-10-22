import argparse
from src.pipeline import run_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the content generation pipeline.")
    parser.add_argument(
        "--insta-only",
        action="store_true",
        help="If set, only the Instagram image generation will be run."
    )
    args = parser.parse_args()

    run_pipeline(insta_only=args.insta_only)
