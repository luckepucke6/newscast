"""Embedding-based deduplication using cosine similarity (no numpy)."""
import logging
import math
import time

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_embeddings(texts: list, client, model: str, cost_tracker=None, max_retries: int = 3) -> list:
    last_exc = None
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(model=model, input=texts)
            if cost_tracker:
                cost_tracker.add_embedding(response.usage.total_tokens)
            return [item.embedding for item in response.data]
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            logger.warning("embeddings försök %d misslyckades: %s — väntar %ds", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"embeddings: alla försök misslyckades: {last_exc}")


def cluster_deduplicate(
    articles: list,
    client,
    cfg: dict,
    cost_tracker=None,
    threshold: float = None,
) -> list:
    """
    Tar bort artiklar som täcker samma nyhet via OpenAI embeddings + cosine similarity.
    Returnerar en dedad lista med unika artiklar.
    """
    if len(articles) <= 1:
        return articles

    if threshold is None:
        threshold = cfg.get("dedup", {}).get("similarity_threshold", 0.85)
    model = cfg["openai"]["embedding_model"]

    texts = [f"{a['title']} {a['summary']}" for a in articles]

    try:
        embeddings = _get_embeddings(texts, client, model, cost_tracker)
    except Exception as e:
        logger.error("Dedup misslyckades, kör utan: %s", e)
        return articles

    kept_indices = []
    removed_count = 0

    for i, emb_i in enumerate(embeddings):
        is_duplicate = False
        for j in kept_indices:
            sim = _cosine_similarity(emb_i, embeddings[j])
            if sim >= threshold:
                logger.debug(
                    "Dedup: '%s' liknar '%s' (sim=%.3f) — tar bort",
                    articles[i]["title"][:60],
                    articles[j]["title"][:60],
                    sim,
                )
                is_duplicate = True
                removed_count += 1
                break
        if not is_duplicate:
            kept_indices.append(i)

    logger.info("Dedup: %d artiklar kvar av %d (%d dubbletter borttagna)", len(kept_indices), len(articles), removed_count)
    return [articles[i] for i in kept_indices]
