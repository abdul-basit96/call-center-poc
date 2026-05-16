import logging
import os
from typing import List, Optional

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Multilingual model to support both Arabic and English semantic search
# Default matches pgvector(1024) in database/init.sql (BGE-M3).
_MODEL_NAME = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
_model: SentenceTransformer | None = None


def is_embedding_loaded() -> bool:
    return _model is not None


def preload_embedding_model() -> None:
    """Load embedding weights at startup (required)."""
    global _model
    if _model is not None:
        return
    logger.info("Loading local embedding model: %s", _MODEL_NAME)
    _model = SentenceTransformer(_MODEL_NAME)
    # Warm up once so device selection / compile happens at startup, not on first tool call.
    _model.encode("warmup", show_progress_bar=False)


def get_embedding(text: str) -> Optional[List[float]]:
    """Return an embedding vector. Model must already be loaded via preload."""
    if _model is None:
        raise RuntimeError(
            "Embedding model is not loaded. Startup preload must run before get_embedding."
        )
    try:
        embedding = _model.encode(text, show_progress_bar=False)
        return embedding.tolist()
    except Exception as e:
        logger.error("Failed to generate embedding: %s", e)
        return None
