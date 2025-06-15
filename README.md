# Refactored PDF to Article Pipeline

This project processes PDF files, extracts information, stores it in a vector database, and then generates journalistic articles based on the extracted content and similar items found in the database.

The original scripts have been refactored into a more modular and configurable structure.

## Project Structure

```
.
├── src/
│   ├── config.py             # Central configuration (paths, model names, API key loading)
│   └── pipeline_steps/       # Modules for each step of the pipeline
│       ├── pdf_processor.py    # Step 1: PDF content and metadata extraction to ChromaDB.
│       ├── relevance_determiner.py # Step 2: Determines relevance of TOPs.
│       ├── reference_finder.py # Step 3: Finds similar TOPs for relevant items.
│       ├── article_writer.py   # Step 4: Generates articles (currently sets a flag).
│       └── db_loader.py        # Utility for ChromaDB interactions.
├── run_step.py             # Main script to execute pipeline steps
├── config.ini.example      # Example configuration for API keys (user should create config.ini)
├── pdf_files/              # Input directory for PDF files
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
*   `process_pdfs`: Extracts TOPs from PDF files in `pdf_files/`, processes them using GenAI, generates embeddings via Ollama, and stores them directly in ChromaDB (`chroma_db/`).
*   `determine_relevance`: Fetches TOPs from ChromaDB, uses GenAI to determine their relevance for journalistic articles, and updates the `is_relevant` metadata flag.
*   `find_references`: For TOPs marked as relevant, queries ChromaDB to find thematically similar TOPs (from different protocols if possible) and stores their IDs in the `references_top_ids` metadata.
*   `write_articles`: For relevant TOPs, "generates" articles (currently sets an `article_generated=True` flag in metadata). Uses references if available when (future) actual generation occurs.
*   `all`: Runs all the above steps in sequence: `process_pdfs` -> `determine_relevance` -> `find_references` -> `write_articles`.

**Command Examples:**

*   To run only the PDF processing step:
    ```bash
    python run_step.py process_pdfs
    ```

*   To run only the relevance determination step:
    ```bash
    python run_step.py determine_relevance
    ```

*   To run only the reference finding step:
    ```bash
    python run_step.py find_references
    ```

*   To run only the article writing step:
    ```bash
    python run_step.py write_articles
    ```

*   To run all steps in sequence:
    ```bash
    python run_step.py all
    ```

Log files for each module's execution will be stored in the `logs/` directory.

## How it Works

The pipeline processes PDF documents to identify relevant agenda items (TOPs) and prepares them for article generation.
1.  **PDF Processing (`pdf_processor.py`):** PDFs from `pdf_files/` are processed. A GenAI model extracts agenda items (TOPs) including content, title, and date. Each TOP is then stored in ChromaDB along with its metadata. Embeddings are generated via Ollama (`nomic-embed-text`) and also stored with each TOP in ChromaDB.
2.  **Relevance Determination (`relevance_determiner.py`):** Each TOP in ChromaDB is evaluated by a GenAI model (using a specific prompt for journalistic relevance) to set an `is_relevant` boolean flag in its metadata.
3.  **Reference Finding (`reference_finder.py`):** For TOPs flagged as relevant, their embeddings are used to query ChromaDB for other semantically similar TOPs (ideally from different protocols/dates). The IDs of these related TOPs are stored in the `references_top_ids` metadata field.
4.  **Article Writing (`article_writer.py`):** TOPs marked as relevant are processed. Currently, this step primarily marks the TOP by setting the `article_generated=True` flag in its metadata. In the future, this step would use the TOP's content and its found references to generate a full journalistic article with a GenAI model, saving it to the `articles/` directory.
