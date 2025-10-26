import pathlib
import html
import logging
from src import config
from src.models import SingleArticle
from src.utils import sanitize_filename

def save_article(article: SingleArticle, pdf_filename: str, logger: logging.Logger):
    """Saves the article as an HTML file."""
    sane_pdf_name = sanitize_filename(pathlib.Path(pdf_filename).stem)
    sane_headline = sanitize_filename(article.ueberschrift)

    # Create a unique filename for each article
    short_headline = "_".join(sane_headline.split('-')[:5])
    if not short_headline: short_headline = "article"

    base_filename = f"{sane_pdf_name}_{short_headline}"

    articles_dir = config.PROJECT_ROOT / config.ARTICLES_DIR_NAME
    articles_dir.mkdir(parents=True, exist_ok=True)

    html_filepath = articles_dir / f"{base_filename}.html"
    counter = 1
    while html_filepath.exists():
        html_filepath = articles_dir / f"{base_filename}_{counter}.html"
        counter += 1

    html_content = f"<h1>{html.escape(article.ueberschrift)}</h1>\n{article.inhalt}"
    try:
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Saved HTML article to: {html_filepath}")
    except IOError as e:
        logger.error(f"Error saving HTML article to {html_filepath}: {e}", exc_info=True)
