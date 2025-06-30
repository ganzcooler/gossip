import argparse
import sys
import pathlib

# Ensure src directory is in sys.path for module imports
project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

try:
    from src.pipeline_steps import pdf_processor
    from src.pipeline_steps import article_writer
    # relevance_determiner, reference_finder, image_generator are removed as they were ChromaDB dependent
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
        choices=['process_pdfs', 'write_articles', 'all'],
        help='The pipeline step to execute: "process_pdfs", "write_articles", or "all" to run all steps in sequence.'
    )

    args = parser.parse_args()

    # Initialize a general logger for run_step.py itself, if desired
    # log = config.get_logger('run_step', 'logs/run_step.log') # Example

    print(f"Executing step: {args.step}")

    # Global variable to hold data between steps if 'all' is chosen
    processed_data = None

    if args.step == 'process_pdfs':
        # When run individually, pdf_processor just extracts and logs (or returns if captured)
        # It doesn't inherently store for the next step unless part of 'all'
        print("Running step: PDF Text Extraction")
        processed_data = pdf_processor.run_pdf_text_extraction()
        if processed_data:
            print(f"PDF processing complete. Extracted text from {len(processed_data)} files.")
        else:
            print("PDF processing complete. No data extracted or an error occurred.")
    # Removed determine_relevance, find_references, generate_images steps as they were ChromaDB dependent
    elif args.step == 'write_articles':
        # When run individually, this step won't have `processed_data` from pdf extraction.
        # It will log that it needs data or try to run with empty input.
        print("Running step: Article Writing")
        print("Warning: Running 'write_articles' individually expects prior PDF processing.")
        print("This run might not produce articles if no data is available from a previous step in this session.")
        # article_writer.run_article_writing({}) # Example: Call with empty dict
        # Or, ideally, this step would load from a known file if run standalone,
        # but current design passes data in memory.
        # For now, let's make it clear it needs input.
        # To make it runnable standalone for testing, one might add a way to load dummy data here.
        # However, the primary path is via 'all'.
        # For now, we call it with None, and it should handle it gracefully (e.g. log and exit)
        article_writer.run_article_writing(extracted_texts=None) # Or an empty dict: {}
    elif args.step == 'all':
        print("Running all steps in sequence...")

        print("\nStep 1: PDF Text Extraction")
        extracted_pdf_texts = pdf_processor.run_pdf_text_extraction()
        if not extracted_pdf_texts:
            print("PDF text extraction failed or produced no data. Halting 'all' pipeline.")
            sys.exit(1)
        print(f"PDF text extraction complete. Extracted text from {len(extracted_pdf_texts)} files.")

        # These steps are no longer part of the primary flow as per requirements.
        # They could be re-integrated or removed entirely later.
        # print("\nStep X: Determine Relevance (SKIPPED as per new requirements)")
        # relevance_determiner.run_relevance_determination() # This would need input if it were to run

        # print("\nStep Y: Find References (SKIPPED as per new requirements)")
        # reference_finder.run_reference_finding() # This would need input

        print("\nStep 2: Article Writing")
        article_writer.run_article_writing(extracted_texts=extracted_pdf_texts)
        print("Article writing complete.")

        # print("\nStep Z: Generate Images (SKIPPED as per new requirements)")
        # image_generator.run_image_generation() # This would need input from articles

        print("\n'all' steps execution finished.")
    else:
        # This case should not be reached due to argparse choices
        print(f"Error: Unknown step '{args.step}'. Please choose from the available steps.")
        parser.print_help()
        sys.exit(1)

    print(f"Step '{args.step}' completed.")

if __name__ == "__main__":
    main()
