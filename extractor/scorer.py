from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from config.settings import SCORER_MIN_SCORE, SCORER_MAX_GAP, SCORER_CONTEXT
from config.signals import SIGNALS
from extractor.parser import PageResult


def _strip_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )


@dataclass
class PageScore:
    page_num: int
    confidence: float
    text: str
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def dominant_type(self) -> Optional[str]:
        content = {k: v for k, v in self.scores.items() if k != "blacklist"}
        if not content:
            return None
        best = max(content, key=content.get)
        if self.scores.get("blacklist", 0) >= content[best]:
            return None
        return best if content[best] >= SCORER_MIN_SCORE else None


@dataclass
class Block:
    block_type: str
    pages: list[PageScore]

    @property
    def text(self) -> str:
        return "\n\n".join(
            f"[Página {p.page_num}]\n{p.text}"
            for p in self.pages
        )

    @property
    def page_range(self) -> tuple[int, int]:
        nums = [p.page_num for p in self.pages]
        return min(nums), max(nums)


def score_page(page: PageResult) -> PageScore:
    text_norm = _strip_tildes(page.text)
    scores = {
        block_type: round(
            sum(w for pattern, w in signals if re.search(pattern, text_norm)),
            2,
        )
        for block_type, signals in SIGNALS.items()
    }
    return PageScore(page_num=page.page_num, confidence=page.confidence,
                     text=page.text, scores=scores)


def group_into_blocks(scored: list[PageScore]) -> list[Block]:
    typed = {
        p.page_num: (p.dominant_type, p)
        for p in scored
        if p.dominant_type is not None
    }
    if not typed:
        return []

    raw_blocks: list[tuple[str, list[PageScore]]] = []
    current_type = None
    current_block: list[PageScore] = []
    last_num = None

    for page_num in sorted(typed):
        ptype, pscore = typed[page_num]
        gap = (page_num - last_num) if last_num else 0

        if ptype == current_type and gap <= SCORER_MAX_GAP + 1:
            current_block.append(pscore)
        else:
            if current_block:
                raw_blocks.append((current_type, current_block))
            current_type = ptype
            current_block = [pscore]
        last_num = page_num

    if current_block:
        raw_blocks.append((current_type, current_block))

    page_map = {p.page_num: p for p in scored}
    blocks = []
    for btype, bpages in raw_blocks:
        first, last = bpages[0].page_num, bpages[-1].page_num
        before = [page_map[n] for n in range(first - SCORER_CONTEXT, first) if n in page_map]
        after  = [page_map[n] for n in range(last + 1, last + SCORER_CONTEXT + 1) if n in page_map]
        blocks.append(Block(block_type=btype, pages=before + bpages + after))

    return blocks