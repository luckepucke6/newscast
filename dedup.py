"""Title-based deduplication using difflib sequence matching."""
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def cluster_deduplicate(
    articles: list,
    cfg: dict,
    threshold: float = None,
) -> list:
    """
    Tar bort artiklar med liknande titlar via difflib SequenceMatcher.
    Returnerar en dedad lista med unika artiklar.
    """
    if len(articles) <= 1:
        return articles

    if threshold is None:
        threshold = cfg.get("dedup", {}).get("similarity_threshold", 0.7)

    kept_indices = []
    removed_count = 0

    for i, article in enumerate(articles):
        is_duplicate = False
        for j in kept_indices:
            sim = _title_similarity(article["title"], articles[j]["title"])
            if sim >= threshold:
                logger.debug(
                    "Dedup: '%s' liknar '%s' (sim=%.3f) — tar bort",
                    article["title"][:60],
                    articles[j]["title"][:60],
                    sim,
                )
                is_duplicate = True
                removed_count += 1
                break
        if not is_duplicate:
            kept_indices.append(i)

    logger.info(
        "Dedup: %d artiklar kvar av %d (%d dubbletter borttagna)",
        len(kept_indices), len(articles), removed_count,
    )
    return [articles[i] for i in kept_indices]
