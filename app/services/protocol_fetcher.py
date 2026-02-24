import httpx
import logging
from bs4 import BeautifulSoup
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from urllib.parse import urljoin
from app.core.config import SESSIONNET_BASE_URL
from app.models import Protocol
from app.services.duplicate_detector import check_duplicate
from app.utils.sessionnet import calculate_sessionnet_params

logger = logging.getLogger(__name__)


async def fetch_protocols_job(db_session: AsyncSession):
    """Job to fetch protocols from SessionNet."""
    logger.info("Starting protocol fetch job")

    params = calculate_sessionnet_params()
    protocols_found = await fetch_and_parse_protocols(params, db_session)

    logger.info(f"Protocol fetch job completed. Found {protocols_found} new protocols")
    return protocols_found


async def fetch_and_parse_protocols(params: dict, db_session: AsyncSession) -> int:
    """
    Fetch protocols from SessionNet and save to database.
    Returns number of new protocols added.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{SESSIONNET_BASE_URL}si0046.asp",
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch protocols: {e}")
            return 0

    soup = BeautifulSoup(response.text, 'lxml')
    protocols = parse_protocol_list(soup)

    new_count = 0
    for protocol_data in protocols:
        # Check if protocol already exists
        existing = await db_session.execute(
            select(Protocol).where(Protocol.getfile_id == protocol_data['getfile_id'])
        )
        if existing.scalar_one_or_none():
            logger.debug(f"Protocol {protocol_data['getfile_id']} already exists, skipping")
            continue

        # Download PDF text
        pdf_text = await download_pdf_text(protocol_data['pdf_url'])
        if not pdf_text:
            logger.warning(f"Could not download PDF for protocol {protocol_data['getfile_id']}")
            continue

        # Check for duplicates
        is_duplicate = await check_duplicate(pdf_text, db_session)
        if is_duplicate:
            logger.warning(f"Duplicate detected for protocol {protocol_data['getfile_id']}, skipping")
            continue

        # Create protocol record
        protocol = Protocol(
            session_date=protocol_data['session_date'],
            title=protocol_data['title'],
            getfile_id=protocol_data['getfile_id'],
            pdf_text=pdf_text,
            processed=False
        )
        db_session.add(protocol)
        new_count += 1
        logger.info(f"Added new protocol: {protocol_data['title']} ({protocol_data['session_date']})")

    await db_session.commit()
    return new_count


def extract_protocol_documents(row, base_url: str) -> list[dict]:
    """Extract protocol documents from a table row."""
    documents = []

    # Only search in document cell (4th column) to avoid matching unrelated links
    cells = row.find_all("td")
    if len(cells) < 4:
        return documents

    document_cell = cells[3]

    for link in document_cell.find_all("a", href=True):
        href = link["href"]

        if "getfile.asp" not in href:
            continue

        link_text = link.get_text(strip=True)

        # Icon suchen im gleichen Dokument-Container
        parent = link.find_parent("div")
        icon = parent.find("i") if parent else None
        icon_text = icon.get_text(strip=True) if icon else ""

        if "Protokoll" in link_text or icon_text in {"NÖ", "NS"}:

            getfile_id = extract_getfile_id(href)

            documents.append({
                "title": link_text,
                "url": urljoin(base_url, href),
                "getfile_id": getfile_id
            })

    return documents


def parse_protocol_list(soup: BeautifulSoup) -> list[dict]:
    """Parse the protocol list from SessionNet HTML."""
    protocols = []

    # Find all table rows with protocol data
    # This is a placeholder - actual parsing depends on SessionNet HTML structure
    rows = soup.find_all('tr', class_='smc-t-r-l')

    for row in rows:
        try:
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            # Extract date
            date_text = cells[0].get_text(strip=True)
            import re
            date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', date_text)
            if not date_match:
                logger.warning(f"Could not extract date from: {date_text}")
                continue
            date_str = date_match.group(1)
            session_date = datetime.strptime(date_str, '%d.%m.%Y').date()

            # Extract title from link in cells[1], fallback to cell text
            link = cells[1].find("a", href=True)
            title = link.get_text(strip=True) if link else cells[1].get_text(strip=True)

            # Extract protocol documents from the row
            documents = extract_protocol_documents(row, SESSIONNET_BASE_URL)

            # Use the first protocol document found
            if not documents:
                logger.warning(f"No protocol document found for row with date {session_date}")
                continue

            pdf_url = documents[0]["url"]
            getfile_id = documents[0]["getfile_id"]

            protocols.append({
                'session_date': session_date,
                'title': title,
                'pdf_url': pdf_url,
                'getfile_id': getfile_id
            })
        except Exception as e:
            logger.warning(f"Error parsing protocol row: {e}")
            continue

    return protocols


def extract_getfile_id(url: str) -> int:
    """Extract getfile_id from SessionNet URL."""
    import re
    match = re.search(r'id=([0-9]+)', url)
    if match:
        return int(match.group(1))
    raise ValueError(f"Could not extract getfile_id from URL: {url}")


async def download_pdf_text(pdf_url: str, max_retries: int = 3) -> str | None:
    """Download PDF and extract text content."""
    import fitz  # PyMuPDF
    import io

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                response = await client.get(pdf_url, timeout=60.0)
                response.raise_for_status()

                # Extract text from PDF
                pdf_bytes = response.content
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")

                text = ""
                for page in doc:
                    text += page.get_text()  # type: ignore

                doc.close()
                return text

            except Exception as e:
                logger.warning(f"PDF download attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to download PDF after {max_retries} attempts")
                    return None

    return None