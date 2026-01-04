"""Image utility helpers for resizing and preparing images for Telegram."""

import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


def resize_image(
    image_path: Path,
    scale: float = 0.5,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> io.BytesIO:
    """
    Resize an image by a scale factor or to fit within max dimensions.

    Args:
        image_path: Path to the source image file.
        scale: Scale factor (0.5 = half size). Used if max_width/max_height not set.
        max_width: Optional maximum width in pixels.
        max_height: Optional maximum height in pixels.

    Returns:
        BytesIO buffer containing the resized PNG image, ready for Telegram.
    """
    try:
        with Image.open(image_path) as img:
            original_width, original_height = img.size

            if max_width or max_height:
                # Resize to fit within max dimensions while preserving aspect ratio
                new_width = max_width or original_width
                new_height = max_height or original_height
                img.thumbnail((new_width, new_height), Image.Resampling.LANCZOS)
            else:
                # Resize by scale factor
                new_width = int(original_width * scale)
                new_height = int(original_height * scale)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Save to BytesIO buffer
            buffer = io.BytesIO()
            img.save(buffer, format="PNG", optimize=True)
            buffer.seek(0)

            logger.debug(
                "Resized image from %dx%d to %dx%d",
                original_width,
                original_height,
                img.size[0],
                img.size[1],
            )

            return buffer
    except Exception:
        logger.exception("Failed to resize image %s", image_path)
        raise


def get_resized_brand_image(image_path: Path, scale: float = 0.5) -> io.BytesIO:
    """
    Get the brand image resized to the specified scale.

    Args:
        image_path: Path to the brand image.
        scale: Scale factor (default 0.5 = half size).

    Returns:
        BytesIO buffer containing the resized image.
    """
    return resize_image(image_path, scale=scale)
