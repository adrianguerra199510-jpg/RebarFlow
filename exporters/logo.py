"""Logo del encabezado de las planillas: normalización de la imagen que elige el usuario y tamaño de impresión."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

#: Tamaño máximo (px) con que se guarda el logo en el proyecto: suficiente para imprimirlo nítido sin inflar el archivo.
MAX_LOGO_PX = (640, 240)


class LogoError(ValueError):
    """La imagen elegida no se pudo leer como logo."""


def normalize_logo(data: bytes) -> bytes:
    """PNG (con transparencia) del logo, reducido a :data:`MAX_LOGO_PX`. Acepta PNG, JPG, BMP, GIF, WebP…

    Lanza :class:`LogoError` si ``data`` no es una imagen.
    """
    try:
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError) as error:
        raise LogoError("No se pudo leer la imagen: use un archivo PNG, JPG, BMP, GIF o WebP.") from error
    image.thumbnail(MAX_LOGO_PX, Image.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def fitted_size(png: bytes, max_width: float, max_height: float) -> tuple[float, float]:
    """Ancho y alto de impresión del logo: el mayor tamaño que cabe en el recuadro sin deformarlo."""
    with Image.open(BytesIO(png)) as image:
        width, height = image.size
    scale = min(max_width / width, max_height / height)
    return width * scale, height * scale
