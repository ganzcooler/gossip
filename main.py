import sys
import argparse
from src.pipeline import run_pipeline
from src.config import PROJECT_ROOT

def get_pipeline_steps():
    return [
        "Generate articles",
        "Generate image prompt",
        "Generate image",
        "Create Instagram images",
        "Generate Instagram captions"
    ]

def main():
    parser = argparse.ArgumentParser(description="Gossip Project Pipeline")
    parser.add_argument("--steps", action="store_true", help="Run specific pipeline steps.")
    args = parser.parse_args()

    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        print("ERROR: .env file not found in the project root.", file=sys.stderr)
        print("Please create a .env file and add your GOOGLE_API_KEY.", file=sys.stderr)
        sys.exit(1)

    selected_steps = None
    if args.steps:
        pipeline_steps = get_pipeline_steps()
        print("Available pipeline steps:")
        for i, step in enumerate(pipeline_steps):
            print(f"{i + 1}: {step}")

        while True:
            try:
                step_input = input("Enter the numbers of the steps to run, separated by commas (e.g., 1,3,5): ")
                selected_indices = [int(x.strip()) for x in step_input.split(',') if x.strip()]
                if all(1 <= i <= len(pipeline_steps) for i in selected_indices):
                    selected_steps = [pipeline_steps[i - 1] for i in selected_indices]
                    break
                else:
                    print("Invalid input. Please enter numbers from the list.", file=sys.stderr)
            except ValueError:
                print("Invalid input. Please enter numbers separated by commas.", file=sys.stderr)
    
    run_pipeline(selected_steps=selected_steps)

if __name__ == "__main__":
    main()
