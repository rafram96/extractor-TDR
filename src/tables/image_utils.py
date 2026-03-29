"""
Utilidades de imagen para extracción y crop de páginas PDF.

Usa PyMuPDF (fitz) para renderizar páginas como imágenes PIL.
Incluye scale_bbox para mapear coordenadas PDF → pixel.
"""

from __future__ import annotations
import io
import logging
from dataclasses import dataclass

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class PaginaImagen:
    pagina: int         # 1-based
    imagen: Image.Image
    ancho_pdf: float    # puntos PDF (72 dpi)
    alto_pdf: float


def extraer_imagen_pagina(
    pdf_path: str,
    pagina: int,
    dpi: int = 200,
) -> PaginaImagen:
    """
    Renderiza una página del PDF como imagen PIL.

    Args:
        pdf_path: Ruta al PDF
        pagina: Número de página (1-based)
        dpi: Resolución de renderizado

    Returns:
        PaginaImagen con imagen PIL y dimensiones PDF
    """
    doc = fitz.open(pdf_path)
    try:
        # fitz usa 0-based
        page = doc[pagina - 1]
        rect = page.rect  # dimensiones en puntos PDF

        # Renderizar a imagen
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        img = Image.open(io.BytesIO(pix.tobytes("png")))
        logger.debug(
            f"[image] Pág {pagina}: {img.width}x{img.height}px "
            f"(PDF: {rect.width:.0f}x{rect.height:.0f}pt)"
        )

        return PaginaImagen(
            pagina=pagina,
            imagen=img,
            ancho_pdf=rect.width,
            alto_pdf=rect.height,
        )
    finally:
        doc.close()


def extraer_multiples_paginas(
    pdf_path: str,
    paginas: list[int],
    dpi: int = 200,
) -> list[PaginaImagen]:
    """Renderiza múltiples páginas en una sola apertura del PDF."""
    doc = fitz.open(pdf_path)
    resultado = []
    try:
        for pagina in paginas:
            page = doc[pagina - 1]
            rect = page.rect
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            resultado.append(PaginaImagen(
                pagina=pagina,
                imagen=img,
                ancho_pdf=rect.width,
                alto_pdf=rect.height,
            ))
        logger.debug(f"[image] Extraídas {len(resultado)} páginas de {pdf_path}")
        return resultado
    finally:
        doc.close()


def scale_bbox(
    bbox: tuple[float, float, float, float],
    pdf_width: float,
    pdf_height: float,
    img_width: int,
    img_height: int,
) -> tuple[int, int, int, int]:
    """
    Mapea coordenadas de bbox de espacio PDF a espacio pixel.

    Docling bbox está en coordenadas PDF (puntos, 72 dpi).
    La imagen renderizada tiene coordenadas en pixeles (dpi variable).
    """
    x1, y1, x2, y2 = bbox
    return (
        int(x1 * img_width / pdf_width),
        int(y1 * img_height / pdf_height),
        int(x2 * img_width / pdf_width),
        int(y2 * img_height / pdf_height),
    )


def crop_tabla(
    pagina_img: PaginaImagen,
    bbox: tuple[float, float, float, float],
    margen: int = 10,
) -> Image.Image:
    """
    Recorta la región de tabla de la imagen usando el bbox de Docling.

    Args:
        pagina_img: PaginaImagen con la imagen completa
        bbox: (x1, y1, x2, y2) en coordenadas PDF
        margen: pixeles extra alrededor del crop

    Returns:
        Imagen recortada de la tabla
    """
    img = pagina_img.imagen
    x1, y1, x2, y2 = scale_bbox(
        bbox,
        pagina_img.ancho_pdf,
        pagina_img.alto_pdf,
        img.width,
        img.height,
    )

    # Aplicar margen sin salir de los bordes
    x1 = max(0, x1 - margen)
    y1 = max(0, y1 - margen)
    x2 = min(img.width, x2 + margen)
    y2 = min(img.height, y2 + margen)

    cropped = img.crop((x1, y1, x2, y2))
    logger.debug(
        f"[image] Crop pág {pagina_img.pagina}: "
        f"bbox PDF=({bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}) "
        f"→ pixel=({x1},{y1},{x2},{y2}) → {cropped.width}x{cropped.height}px"
    )
    return cropped
