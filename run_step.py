import argparse
import sys
import pathlib

# Ensure src directory is in sys.path for module imports
project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

try:
    from src.pipeline_steps import pdf_processor
    from src.pipeline_steps import article_writer
    from src.pipeline_steps import image_generator # Added back image_generator
    # relevance_determiner, reference_finder are removed as they were ChromaDB dependent
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
        choices=['process_pdfs', 'write_articles', 'generate_images', 'all'],
        help='The pipeline step to execute: "process_pdfs", "write_articles", "generate_images", or "all" to run all steps in sequence.'
    )

    args = parser.parse_args()

    # Initialize a general logger for run_step.py itself, if desired
    # log = config.get_logger('run_step', 'logs/run_step.log') # Example
    log = config.get_logger('run_step', 'logs/run_step.log') # Initialize logger for run_step

    log.info(f"Executing step: {args.step}")

    if args.step == 'process_pdfs':
        log.info("Running step: PDF Text Extraction")
        pdf_processor.run_pdf_text_extraction() # No return value, writes to files
        # Check if files were created in extracted_texts_dir
        extracted_texts_dir = config.PROJECT_ROOT / config.EXTRACTED_TEXTS_DIR_NAME
        if not extracted_texts_dir.is_dir() or not any(extracted_texts_dir.iterdir()):
            log.warning(f"PDF processing complete, but no files found in {extracted_texts_dir}. Check logs for details.")
        else:
            log.info(f"PDF processing complete. Text files should be in '{config.EXTRACTED_TEXTS_DIR_NAME}'.")

    elif args.step == 'write_articles':
        log.info("Running step: Article Writing")
        # article_writer now reads from the directory specified in config or passed as argument
        article_writer.run_article_writing()
        log.info(f"Article writing process initiated. Check '{config.ARTICLES_DIR_NAME}' for HTML articles and logs for details.")

    elif args.step == 'generate_images':
        log.info("Running step: Image Generation")
        image_generator.run_image_generation()
        log.info(f"Image generation process initiated. Check '{config.IMAGES_DIR_NAME}' for images and logs for details.")

    elif args.step == 'all':
        log.info("Running all steps in sequence...")

        log.info("\nStep 1: PDF Text Extraction")
        pdf_processor.run_pdf_text_extraction()
        # Optional: Check if extracted_texts directory was populated before proceeding
        extracted_texts_dir = config.PROJECT_ROOT / config.EXTRACTED_TEXTS_DIR_NAME
        if not extracted_texts_dir.is_dir() or not any(extracted_texts_dir.glob('*.txt')):
            log.error(f"PDF text extraction may have failed or produced no data in {extracted_texts_dir}. Halting 'all' pipeline. Check pdf-processing.log.")
            sys.exit(1)
        log.info(f"PDF text extraction complete. Text files should be in '{config.EXTRACTED_TEXTS_DIR_NAME}'.")

        # These steps are no longer part of the primary flow as per requirements.
        # print("\nStep X: Determine Relevance (SKIPPED as per new requirements)")
        # relevance_determiner.run_relevance_determination() # This would need input if it were to run

        # print("\nStep Y: Find References (SKIPPED as per new requirements)")
        # reference_finder.run_reference_finding() # This would need input

        log.info("\nStep 2: Article Writing")
        article_writer.run_article_writing() # Reads from the configured directory
        log.info(f"Article writing process initiated. Check '{config.ARTICLES_DIR_NAME}' for HTML articles and logs for details.")

        log.info("\nStep 3: Image Generation")
        image_generator.run_image_generation()
        log.info(f"Image generation process initiated. Check '{config.IMAGES_DIR_NAME}' for images and logs for details.")


        log.info("\n'all' steps execution finished.")
    else:
        # This case should not be reached due to argparse choices
        log.error(f"Error: Unknown step '{args.step}'. Please choose from the available steps.")
        parser.print_help()
        sys.exit(1)

    log.info(f"Step '{args.step}' completed.")

if __name__ == "__main__":
    main()
