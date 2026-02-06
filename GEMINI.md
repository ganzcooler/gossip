# GEMINI.md - Project Context

This document provides a comprehensive overview of the "gossip" project for AI-assisted development.

## Project Overview

This project is a Python-based pipeline designed to automate the creation of journalistic-style blog posts and associated images from PDF documents. It appears to be tailored for generating local news content from official documents like city council meeting minutes.

The core workflow is as follows:
1.  **PDF Ingestion:** It processes PDF files from the `pdf_files/` directory.
2.  **Text Extraction:** Text is extracted from the PDFs using the `PyMuPDF` library.
3.  **AI Article Generation:** The extracted text is fed to a Google GenAI model (`gemini-3-pro-preview`) using a detailed German prompt (from `src/prompts.py`) to generate multiple, slightly ironic, journalistic articles in HTML format.
4.  **AI Image Generation:** For each article, a separate AI prompt is generated (`gemini-2.5-flash`) and then used to create a hero image in **4:5 aspect ratio** with a text-to-image model (`gemini-2.5-flash-image`).
5.  **Instagram Formatting:** A final step processes the generated images and articles, overlaying them with the article headline and a logo (`res/logo-gossip.png`) to create Instagram-ready posts. Since images are generated in 4:5, no further cropping is required.
6.  **AI Caption Generation:** For each article, an Instagram caption is generated using a GenAI model.

The generated content is saved in the `articles/` (HTML), `generated_images/` (raw generated images), and `insta_images/` (Instagram-formatted images and captions) directories.

### Key Technologies
- **Backend:** Python
- **AI:** Google GenAI (Gemini & Imagen)
- **PDF Processing:** PyMuPDF
- **Image Manipulation:** Pillow
- **Dependencies:** `requirements.txt` (google-genai, python-dotenv, beautifulsoup4, PyMuPDF, pydantic, Pillow)

## Building and Running

### 1. Installation
Install the required Python packages:
```bash
pip install -r requirements.txt
```

### 2. Configuration
The application requires a Google API key. Create a `.env` file in the project root directory with the following structure:

```env
GOOGLE_API_KEY="your_api_key_here"
```

### 3. Execution
The main entry point is `main.py`.

- **To run the full pipeline (PDF -> Articles -> Images -> Instagram Posts -> Captions):**
  Place your PDF files in the `pdf_files/` directory and run:
  ```bash
  python main.py
  ```

- **To run only specific steps of the pipeline:**
  Use the `--steps` flag to select which steps to run.
  ```bash
  python main.py --steps
  ```

## Development Conventions

- **Modular Structure:** The code is well-organized into a `src/` directory with clear separation of concerns:
    - `pipeline.py`: Core orchestration logic.
    - `config.py`: Centralized configuration for paths, model names, and API settings.
    - `prompts.py`: Contains the large, detailed prompts for the AI models. This is the heart of the content's tone and style.
    - `insta_images.py`: Logic dedicated to formatting images for Instagram.
    - `models.py`: Defines Pydantic models for data validation and serialization.
    - `tags.py`: Manages content tagging for generated articles.
    - `utils.py`: Contains various utility functions used across the project.
    - `pipeline_steps/`: A directory containing individual steps of the content generation pipeline:
        - `check_existing_articles.py`: Checks for already generated articles to prevent reprocessing.
        - `extract_text.py`: Extracts text content from PDF documents.
        - `find_pdf_files.py`: Locates PDF files in the input directory.
        - `generate_articles.py`: Generates journalistic articles using an AI model.
        - `generate_image_prompt.py`: Creates prompts for AI image generation.
        - `generate_image.py`: Generates hero images based on AI prompts in 4:5 format.
        - `generate_insta_caption.py`: Generates Instagram captions for the articles.
        - `save_article.py`: Saves the generated HTML articles to files.
        - `save_image.py`: Saves the generated images to files.
        - `setup_logger.py`: Configures the logging system for the pipeline.
- **Configuration:** All major settings (file paths, model names, API delays) are managed in `src/config.py`.
- **Logging:** The pipeline implements comprehensive logging, outputting to both the console and a timestamped log file in the `logs/` directory for each run.
- **Idempotency:** The pipeline has checks to avoid re-generating articles and images that already exist for a given PDF, making it safe to re-run.
- **Entry Point:** The primary entry point is `main.py`, which uses `argparse` for command-line argument handling.