# Refactored PDF to Article Pipeline

This project processes PDF files, extracts information, stores it in a vector database, and then generates journalistic articles based on the extracted content and similar items found in the database.

The original scripts have been refactored into a more modular and configurable structure.

## Project Structure

```
.
├── src/
│   ├── config.py             # Central configuration (paths, model names, API key loading)
│   └── pipeline_steps/       # Modules for each step of the pipeline
│       ├── pdf_processor.py    # Step 1: PDF to JSON extraction
│       ├── db_loader.py        # Step 2: JSON to ChromaDB loading
│       └── article_generator.py # Step 3: Article generation from ChromaDB data
├── run_step.py             # Main script to execute pipeline steps
├── config.ini.example      # Example configuration for API keys (user should create config.ini)
├── pdf_files/              # Input directory for PDF files
├── json-files/             # Output for extracted JSON data (also used as input by db_loader)
├── articles/               # Output directory for generated articles (Markdown files)
├── chroma_db/              # Persistent storage for ChromaDB
├── logs/                   # Directory for log files from script execution
├── .gitignore              # Specifies intentionally untracked files that Git should ignore
└── README.md               # This file
```

## Setup and Configuration

1.  **Dependencies:** Ensure you have Python installed. You will need to install the necessary libraries. Key libraries include:
    *   `google-generativeai`
    *   `chromadb`
    *   `ollama`
    *   `pydantic`
    *   `python-dotenv` (if you choose to use .env files for API keys, though `config.ini` is the current method)

    You can typically install these using pip: `pip install google-generativeai chromadb ollama pydantic`

2.  **API Keys & Configuration (`config.ini`):
    *   This project requires a Google API key for the Generative AI models.
    *   Create a file named `config.ini` in the root directory of the project.
    *   Its content should be as follows (replace `your_api_key_here` with your actual Google API key):

    ```ini
    [genai]
    GOOGLE_API_KEY=your_api_key_here
    ```
    *   The `config.ini` file is listed in `.gitignore` and should not be committed to version control if it contains sensitive keys.

3.  **Ollama Setup:**
    *   Ensure Ollama is installed and running.
    *   Make sure the embedding model specified in `src/config.py` (default: `nomic-embed-text`) is available in your Ollama setup. You can pull it using `ollama pull nomic-embed-text`.

4.  **Input PDF Files:**
    *   Place the PDF files you want to process into the `pdf_files/` directory in the project root.

## Running the Pipeline

The `run_step.py` script is used to execute the different stages of the pipeline. You can run a specific step or all steps in sequence.

Available steps:
1.  `pdf_to_json`: Processes PDFs from `pdf_files/`, extracts content using GenAI, and saves them as structured JSON in `json-files/`.
2.  `json_to_db`: Loads the JSON files from `json-files/`, generates embeddings using Ollama, and stores them in ChromaDB (`chroma_db/`).
3.  `generate_articles`: Reads new entries from `json-files/`, finds related texts in ChromaDB, generates articles using GenAI, and saves them to `articles/`.
4.  `all`: Runs all the above steps in sequence: `pdf_to_json` -> `json_to_db` -> `generate_articles`.

**Command Examples:**

*   To run only the PDF to JSON processing step:
    ```bash
    python run_step.py pdf_to_json
    ```

*   To run only the JSON to ChromaDB loading step:
    ```bash
    python run_step.py json_to_db
    ```

*   To run only the article generation step:
    ```bash
    python run_step.py generate_articles
    ```

*   To run all steps in sequence:
    ```bash
    python run_step.py all
    ```

Log files for each module's execution will be stored in the `logs/` directory.

## How it Works

1.  **PDF Processing (`pdf_processor.py`):** PDFs are read, and their content is parsed by a Google Generative AI model (specified in `src/config.py`) to extract structured data (title, date, agenda items) into JSON files.
2.  **Database Loading (`db_loader.py`):** The structured text from JSON files is processed. For each relevant piece of text, an embedding is generated using an Ollama model. This text, its embedding, and associated metadata are stored in a ChromaDB vector database.
3.  **Article Generation (`article_generator.py`):** For new entries (identified from the JSON files), the system queries the ChromaDB to find semantically similar older texts from *different* source documents. This context (new entries + similar older texts) is then fed to a Google Generative AI model to produce a journalistic article.
