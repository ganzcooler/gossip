# PDF to Article and Image Pipeline

This project automates the process of converting PDF documents into a series of articles, accompanying images, and Instagram-ready posts. It extracts text from PDFs, uses a generative AI to write multiple articles, generates a unique image for each article, and finally formats those images with text overlays for social media.

## Setup and Configuration

1.  **Dependencies:** Install the required Python libraries:
    ```bash
    pip install -r requirements.txt
    ```

2.  **API Key (`.env` file):**
    *   This project requires a Google API key for the generative AI models.
    *   Create a file named `.env` in the root directory. The application will not start if this file is missing.
    *   Add your Google API key to the `.env` file:
        ```
        GOOGLE_API_KEY="your_api_key_here"
        ```

3.  **Input PDF Files:**
    *   Place the PDF files you want to process into the `pdf_files/` directory.

## Running the Pipeline

To generate articles and images from the PDFs in the `pdf_files/` directory, run the main script:

```bash
python main.py
```

The script will perform all steps automatically:
1.  Extract text from each PDF.
2.  Generate a set of articles for each PDF.
3.  Save the articles as HTML files in the `articles/` directory.
4.  Generate a corresponding image for each article and save it in the `generated_images/` directory.
5.  Create Instagram-formatted posts from the articles and images, saving them in the `insta_images/` directory.

The pipeline is idempotent, meaning it will automatically skip PDFs for which all articles and images have already been successfully generated. Log files for each run are stored in the `logs/` directory.

## How it Works

The pipeline is designed as a series of modular steps orchestrated by `src/pipeline.py`:

1.  **Text Extraction:** The script iterates through all PDF files in the `pdf_files/` directory and extracts the complete text content.
2.  **Article Generation:** The extracted text is passed to a generative AI model, which creates a series of journalistic articles based on the detailed prompts in `src/prompts.py`.
3.  **Image Generation:** For each generated article, a new prompt is created to generate a relevant hero image.
4.  **Instagram Formatting:** After all articles and images are generated, the script processes them into a format suitable for Instagram, overlaying the article headline and a logo onto a cropped version of the image.