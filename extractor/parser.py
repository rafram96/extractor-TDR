from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class PageResult:
    page_num: int
    motor: str       # "paddle" | "qwen"
    confidence: float
    text: str


_PAGE_HEADER_RE = re.compile(
    r"^## Página (\d+)\s+_([^\s·]+).*?conf\s+([\d.]+)_",
    re.MULTILINE,
)
_CODE_BLOCK_RE = re.compile(r"```\n(.*?)```", re.DOTALL)


def parse_full_text(full_text: str) -> list[PageResult]:
    """
    Convierte el full_text del motor OCR en lista de PageResult.
    Cada PageResult tiene número de página, motor, confianza y texto.
    """
    pages = []
    for m in _PAGE_HEADER_RE.finditer(full_text):
        page_num = int(m.group(1))
        motor    = m.group(2)
        conf     = float(m.group(3))
        rest     = full_text[m.end():]
        cb       = _CODE_BLOCK_RE.search(rest)
        text     = cb.group(1).strip() if cb else ""
        pages.append(PageResult(page_num, motor, conf, text))
    return pages