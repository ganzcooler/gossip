import argparse
import sys
import pathlib

# Ensure src directory is in sys.path for module imports
project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

try:
    from src.pipeline_steps import pdf_processor
    from src.pipeline_steps import db_loader
    from src.pipeline_steps import article_generator
    from src import config # To initialize logging or access other configs if needed directly
except ImportError as e:
    print(f"Error: Could not import pipeline step modules or config: {e}")
    print("Please ensure that the 'src' directory and its contents are structured correctly and a 'config.ini' file exists.")
    sys.exit(1)

def main():
    """Main entry point to run specific pipeline steps."""
    parser = argparse.ArgumentParser(description='Run individual steps of the data processing pipeline.')
    parser.add_argument(
        'step',
        choices=['pdf_to_json', 'json_to_db', 'generate_articles', 'all'],
        help='The pipeline step to execute. "all" runs all steps in sequence.'
    )
    parser.add_argument(
        '--start_date',
        type=str,
        default=None,
        help='Start date for filtering protocols (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end_date',
        type=str,
        default=None,
        help='End date for filtering protocols (YYYY-MM-DD)'
    )

    args = parser.parse_args()

    # Initialize a general logger for run_step.py itself, if desired
    # log = config.get_logger('run_step', 'logs/run_step.log') # Example

    print(f"Executing step: {args.step}")

    if args.step == 'pdf_to_json':
        pdf_processor.run_pdf_to_json_conversion()
    elif args.step == 'json_to_db':
        db_loader.run_json_to_chroma_loading()
    elif args.step == 'generate_articles':
        article_generator.run_article_generation(
            start_date=args.start_date,
            end_date=args.end_date
        )
    elif args.step == 'all':
        print("Running step: pdf_to_json")
        pdf_processor.run_pdf_to_json_conversion()
        print("Running step: json_to_db")
        db_loader.run_json_to_chroma_loading()
        print("Running step: generate_articles")
        article_generator.run_article_generation(
            start_date=args.start_date,
            end_date=args.end_date
        )
    else:
        # This case should not be reached due to argparse choices
        print(f"Error: Unknown step '{args.step}'. Please choose from the available steps.")
        parser.print_help()
        sys.exit(1)

    print(f"Step '{args.step}' completed.")

if __name__ == "__main__":
    main()
