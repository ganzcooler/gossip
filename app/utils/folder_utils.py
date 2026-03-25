import re
from datetime import date
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# Umlaut replacement map for folder name normalization
_UMLAUT_MAP = {
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
    'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
}


def normalize_for_folder_name(title: str) -> str:
    """
    Normalize a title for use in folder names.
    
    Applies umlaut replacement, converts spaces to underscores,
    lowercases, removes special characters, and truncates to 80 chars.
    
    Args:
        title: The protocol title to normalize
        
    Returns:
        Normalized string suitable for folder names
    """
    normalized = title
    for umlaut, replacement in _UMLAUT_MAP.items():
        normalized = normalized.replace(umlaut, replacement)
    
    # Spaces to underscores
    normalized = normalized.replace(' ', '_')
    
    # Lowercase
    normalized = normalized.lower()
    
    # Remove special characters
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    
    # Max 80 characters
    return normalized[:80]


def create_protocol_folder(base_dir: Path, session_date: date, title: str) -> Path:
    """
    Create a normalized folder name for a protocol.
    Format: YYMMDD_normalized_title
    """
    normalized = normalize_for_folder_name(title)
    
    # Date prefix
    folder_name = f"{session_date.strftime('%y%m%d')}_{normalized}"

    folder_path = base_dir / folder_name

    if folder_path.exists():
        logger.error(f"Folder already exists: {folder_path}")
        raise FileExistsError(f"Folder {folder_path} already exists")

    folder_path.mkdir(parents=True, exist_ok=False)
    return folder_path


def ensure_directories(base_paths: list[Path]):
    """Ensure all required directories exist."""
    for path in base_paths:
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directory exists: {path}")