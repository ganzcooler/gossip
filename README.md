# PDF to Article and Image Pipeline

This project automates the process of converting PDF documents into a series of articles and accompanying images. It extracts the text from PDFs, uses a generative AI to write multiple articles based on the content, and then generates a unique image for each article.

Additionally, it includes a separate script to create Instagram-ready images from the generated articles.

## Project Structure

```
.
├── src/
│   ├── config.py             # Central configuration for paths, model names, and API keys.
│   ├── pipeline.py           # Core logic for the PDF-to-article-and-image pipeline.
│   ├── insta_images.py       # Logic for creating Instagram images.
│   └── prompts.py            # Contains the prompts used for the generative AI.
├── run_pipeline.py         # Main script to execute the full pipeline.
├── run_insta_images.py     # Script to generate Instagram images.
├── pdf_files/              # Input directory for your PDF files.
├── articles/               # Output directory for generated articles (as HTML files).
├── images/                 # Output directory for generated article images.
├── generated_images/       # Output directory for Instagram-formatted images.
├── res/                    # Resources like fonts and logos.
├── logs/                   # Directory for log files.
├── requirements.txt        # Project dependencies.
├── .gitignore              # Files to be ignored by Git.
└── README.md               # This file.
```

## Setup and Configuration

1.  **Dependencies:** Install the required Python libraries using the `requirements.txt` file:
    ```bash
    pip install -r requirements.txt
    ```

2.  **API Keys (`.env` file):**
    *   This project requires a Google API key for the generative AI models.
    *   Create a file named `.env` in the root directory of the project.
    *   Add your Google API key to the `.env` file as follows:
        ```
        GOOGLE_API_KEY="your_api_key_here"
        ```
    *   The `.env` file is included in `.gitignore` to ensure your API key is not committed to version control.

3.  **Input PDF Files:**
    *   Place the PDF files you want to process into the `pdf_files/` directory.

## Running the Pipeline

To generate articles and images from the PDFs in the `pdf_files/` directory, run the main pipeline script:

```bash
python run_pipeline.py
```

This will:
1.  Extract text from each PDF.
2.  Generate a set of articles for each PDF.
3.  Save the articles as HTML files in the `articles/` directory.
4.  Generate a corresponding image for each article and save it in the `images/` directory.

Log files for the pipeline are stored in the `logs/` directory.

## How it Works

The pipeline is designed to be straightforward:

1.  **Text Extraction:** The script iterates through all PDF files in the `pdf_files/` directory and extracts the complete text content from each file.
2.  **Article Generation:** The extracted text is passed to a generative AI model, which generates a series of journalistic articles. The structure and content of these articles are guided by a prompt defined in `src/prompts.py`. The number of articles and their tone can be adjusted by modifying the prompt.
3.  **Image Generation:** For each generated article, a new prompt is created to generate a relevant image. This image is then saved, linking it to the article by filename.

## Generating Instagram Images

This project also includes a script to convert the generated articles and images into a format suitable for Instagram.

To generate these images, run the following command:
```bash
python run_insta_images.py
```
This script will:
1.  Find all images in the `images/` directory.
2.  For each image, find the corresponding HTML article in the `articles/` directory.
3.  Extract the headline from the article.
4.  Crop the image to a 4:5 aspect ratio.
5.  Overlay the headline and a logo onto the image.
6.  Save the final image in the `generated_images/` directory.
