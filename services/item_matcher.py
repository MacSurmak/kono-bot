import re
from typing import List, Dict, Any, Set
from rapidfuzz import fuzz

SCORE_EXACT_ARTICLE = 100.0
SCORE_DIMENSION_BONUS = 15.0
SCORE_DIMENSION_PENALTY = 35.0
DEFAULT_CANDIDATES_LIMIT = 3
MIN_ACCEPTABLE_SCORE = 45.0

NOISE_WORDS: Set[str] = {
    "акция",
    "упак",
    "упаковка",
    "пачка",
    "пач",
    "пак",
    "бут",
    "бутылка",
    "шт",
    "кор",
    "коробка",
    "гост",
    "ту",
    "б/уп",
    "артикул",
    "арт",
    "россия",
    "китай",
    "япония",
    "тайланд",
    "корея",
    "для",
    "со",
    "вкусом",
}


def clean_raw_name(text: str) -> str:
    """Removes packaging boilerplate and stop words from supplier descriptions."""
    clean_text = text.replace("\xa0", " ")
    tokens = re.findall(r"[a-zA-Zа-яА-Я0-9%хx/.,]+", clean_text)
    meaningful = [tok for tok in tokens if tok.lower() not in NOISE_WORDS]
    return " ".join(meaningful)


def extract_dimensions_and_numbers(text: str) -> set:
    """Extracts numeric values, volume metrics, and dimensions (e.g. 110x160, 330, 240)."""
    return set(re.findall(r"\b\d+(?:[xх]\d+)?\b", text.lower()))


def find_catalog_candidates(
    raw_name: str,
    article: str,
    catalog: List[Dict[str, Any]],
    limit: int = DEFAULT_CANDIDATES_LIMIT,
) -> List[Dict[str, Any]]:
    """Evaluates iiko catalog products using exact article matches, dimension preservation, and token-set scoring."""
    # Tier 1: Exact article / SKU match from vendor invoice
    clean_article = article.strip().lower() if article else ""
    if clean_article:
        exact_sku_matches = [
            p for p in catalog if p.get("article", "").strip().lower() == clean_article
        ]
        if exact_sku_matches:
            return [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "article": p.get("article", ""),
                    "score": SCORE_EXACT_ARTICLE,
                }
                for p in exact_sku_matches[:limit]
            ]

    # Tier 2: Token-set scoring with dimensional cross-check
    cleaned_raw = clean_raw_name(raw_name)
    raw_nums = extract_dimensions_and_numbers(raw_name)

    scored = []
    for p in catalog:
        p_name = p["name"]
        score = float(fuzz.token_set_ratio(cleaned_raw, p_name))

        # Check dimension / number alignment
        p_nums = extract_dimensions_and_numbers(p_name)
        if raw_nums and p_nums:
            if raw_nums == p_nums:
                score = min(100.0, score + SCORE_DIMENSION_BONUS)
            elif not (raw_nums & p_nums):
                # Penalize conflicting dimensions (e.g. 110x160 vs 120x175)
                score = max(0.0, score - SCORE_DIMENSION_PENALTY)

        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"id": p["id"], "name": p["name"], "article": p.get("article", ""), "score": s}
        for s, p in scored[:limit]
    ]
