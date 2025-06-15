import argparse
import sys
import pathlib

# Ensure src directory is in sys.path for module imports
project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

try:
    from src.pipeline_steps import pdf_processor
    from src.pipeline_steps import relevance_determiner
    from src.pipeline_steps import reference_finder
    from src.pipeline_steps import article_writer
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
        choices=['process_pdfs', 'determine_relevance', 'find_references', 'write_articles', 'all'],
        help='The pipeline step to execute: "process_pdfs" (extracts from PDFs and stores in DB), "determine_relevance", "find_references", "write_articles", or "all" to run all steps in sequence.'
    )

    args = parser.parse_args()

    # Initialize a general logger for run_step.py itself, if desired
    # log = config.get_logger('run_step', 'logs/run_step.log') # Example

    print(f"Executing step: {args.step}")

    if args.step == 'process_pdfs':
        pdf_processor.run_pdf_extraction_and_storage()
    elif args.step == 'determine_relevance':
        relevance_determiner.run_relevance_determination()
    elif args.step == 'find_references':
        reference_finder.run_reference_finding()
    elif args.step == 'write_articles':
        article_writer.run_article_writing()
    elif args.step == 'all':
        print("Running step: process_pdfs")
        pdf_processor.run_pdf_extraction_and_storage()
        print("Running step: determine_relevance")
        relevance_determiner.run_relevance_determination()
        print("Running step: find_references")
        reference_finder.run_reference_finding()
        print("Running step: write_articles")
        article_writer.run_article_writing()
    else:
        # This case should not be reached due to argparse choices
        print(f"Error: Unknown step '{args.step}'. Please choose from the available steps.")
        parser.print_help()
        sys.exit(1)

    print(f"Step '{args.step}' completed.")

if __name__ == "__main__":
    main()
