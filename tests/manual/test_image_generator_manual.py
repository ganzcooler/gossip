"""
Manual tests for image generation with real API calls.

Run: pytest -m manual
"""
import os

import pytest

from app.services.image_generator import generate_image

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not os.getenv("OPENROUTER_API_KEY"),
        reason="requires OPENROUTER_API_KEY for a real OpenRouter call",
    ),
]


def test_generate_image_real_api_call():
    """Test that generate_image returns non-empty bytes from a real API call."""
    prompt = (
        "A realistic photograph of a modern city hall building "
        "with clear blue sky and green trees in front"
    )

    image_bytes = generate_image(prompt)

    assert isinstance(image_bytes, bytes), "Result should be bytes"
    assert len(image_bytes) > 0, "Generated image should not be empty"
    assert len(image_bytes) > 1024, (
        f"Generated image should be larger than 1KB, got {len(image_bytes)} bytes"
    )


def test_generate_image_returns_valid_image_data():
    """Test that the generated image data has valid image magic bytes."""
    prompt = "A simple blue square on white background"

    image_bytes = generate_image(prompt)

    assert len(image_bytes) > 0, "Generated image should not be empty"

    magic_bytes = image_bytes[:4]
    valid_magic = {
        b"\x89PNG": "PNG",
        b"\xff\xd8\xff\xe0": "JPEG",
        b"\xff\xd8\xff\xe1": "JPEG (EXIF)",
    }

    matched = False
    for magic, fmt in valid_magic.items():
        if magic_bytes.startswith(magic):
            matched = True
            break

    assert matched, (
        f"Unexpected image format. First 8 bytes: {magic_bytes.hex()}"
    )
