"""Tests for the image generation wrapper used by the two-post pipeline."""

from unittest.mock import patch

from app.core import config
from app.services import post_image_generator
from app.services.openrouter_client import ImageGenerationResult


@patch("app.services.post_image_generator.openrouter_client.generate_image_result")
def test_generate_image_bytes_passes_model_and_resolution(mock_generate):
    mock_generate.return_value = ImageGenerationResult(
        image_bytes=b"image-bytes",
        usage={},
    )

    result = post_image_generator.generate_image_bytes("A test prompt", "4:5")

    assert result == b"image-bytes"
    kwargs = mock_generate.call_args.kwargs
    assert kwargs["model"] == config.OPENROUTER_IMAGE_MODEL
    assert kwargs["resolution"] == config.OPENROUTER_IMAGE_RESOLUTION
    assert kwargs["aspect_ratio"] == "4:5"
