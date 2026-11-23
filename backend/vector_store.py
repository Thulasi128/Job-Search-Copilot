"""Local ChromaDB vector store management, collection migration, and chunk similarity search."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import chromadb
from chromadb.api import ClientAPI
from chromadb.utils import embedding_functions

from backend.config import get_settings
from backend.models.profile import Profile

logger = logging.getLogger(__name__)

PROFILE_CHUNKS_COLLECTION = "profile_chunks"
_embedding_model_singleton = None


def get_embedding_model():
    """Lazy singleton loader for the local SentenceTransformer model."""
    global _embedding_model_singleton
    if _embedding_model_singleton is None:
        from sentence_transformers import SentenceTransformer
        settings = get_settings()
        logger.info("Loading SentenceTransformer singleton for %s", settings.EMBEDDING_MODEL)
        _embedding_model_singleton = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _embedding_model_singleton


def get_embedding_function(model_name: Optional[str] = None):
    """Return the local SentenceTransformer embedding function for ChromaDB.

    Args:
        model_name: Optional model name override. Defaults to Settings.EMBEDDING_MODEL.

    Returns:
        SentenceTransformerEmbeddingFunction: ChromaDB compatible embedding function.
    """
    settings = get_settings()
    selected_model = model_name or settings.EMBEDDING_MODEL
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=selected_model)


def get_chroma_client(persist_directory: Optional[str] = None) -> ClientAPI:
    """Return a persistent ChromaDB client for the configured directory.

    Args:
        persist_directory: Optional directory path. Defaults to Settings.CHROMA_DIR.

    Returns:
        ClientAPI: ChromaDB persistent client.
    """
    settings = get_settings()
    path = persist_directory or settings.CHROMA_DIR
    return chromadb.PersistentClient(path=path)


def distance_to_similarity(
    distance: float,
    sim_low: Optional[float] = None,
    sim_high: Optional[float] = None,
) -> Tuple[float, float]:
    """Convert Chroma cosine distance to bounded raw and calibrated similarity.

    Chroma cosine distance d = 1 - cos(theta) in [0, 2].
    Raw similarity s = clamp(1.0 - d, 0.0, 1.0).
    Calibrated similarity = clamp((s - sim_low) / (sim_high - sim_low), 0.0, 1.0).

    Args:
        distance: Cosine distance from Chroma.
        sim_low: Lower calibration bound. Defaults to Settings.SIM_LOW.
        sim_high: Upper calibration bound. Defaults to Settings.SIM_HIGH.

    Returns:
        Tuple[float, float]: (raw_similarity, calibrated_similarity)
    """
    settings = get_settings()
    low = sim_low if sim_low is not None else settings.SIM_LOW
    high = sim_high if sim_high is not None else settings.SIM_HIGH

    raw_sim = max(0.0, min(1.0, 1.0 - distance))
    if high <= low:
        calibrated_sim = raw_sim
    else:
        calibrated_sim = max(0.0, min(1.0, (raw_sim - low) / (high - low)))

    return round(raw_sim, 4), round(calibrated_sim, 4)


def ensure_cosine_collection(
    client: ClientAPI,
    embedding_fn: Any,
) -> Any:
    """Ensure the profile_chunks collection uses cosine space (hnsw:space = cosine).

    If the existing collection uses L2 or another metric, deletes and recreates it with cosine.

    Args:
        client: Active ChromaDB client.
        embedding_fn: Embedding function to attach to the collection.

    Returns:
        Collection: Active ChromaDB collection with cosine distance metric.
    """
    try:
        existing = client.get_collection(
            name=PROFILE_CHUNKS_COLLECTION,
            embedding_function=embedding_fn,
        )
        metadata = existing.metadata or {}
        if metadata.get("hnsw:space") != "cosine":
            logger.warning(
                "Chroma collection '%s' metric is '%s' instead of 'cosine'. Recreating collection...",
                PROFILE_CHUNKS_COLLECTION,
                metadata.get("hnsw:space"),
            )
            client.delete_collection(name=PROFILE_CHUNKS_COLLECTION)
            return client.create_collection(
                name=PROFILE_CHUNKS_COLLECTION,
                embedding_function=embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        return existing
    except Exception:
        # Collection does not exist yet; create with cosine
        return client.get_or_create_collection(
            name=PROFILE_CHUNKS_COLLECTION,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )


def delete_profile_chunks(
    profile_id: str,
    persist_directory: Optional[str] = None,
) -> None:
    """Delete all indexed chunks for a given profile ID.

    Args:
        profile_id: Identifier of the candidate profile.
        persist_directory: Optional ChromaDB storage directory override.
    """
    client = get_chroma_client(persist_directory)
    try:
        collection = client.get_collection(name=PROFILE_CHUNKS_COLLECTION)
        collection.delete(where={"profile_id": profile_id})
        logger.info("Cleared existing chunks for profile_id=%s in ChromaDB", profile_id)
    except Exception as exc:
        logger.debug("No existing collection or chunks to delete: %s", exc)


def index_profile_chunks(
    profile: Profile,
    persist_directory: Optional[str] = None,
    embedding_fn: Optional[Any] = None,
) -> int:
    """Index profile skills, projects, and experiences into ChromaDB with cosine metric.

    Deletes all previous chunks for this profile ID prior to insertion to prevent duplicates.

    Args:
        profile: Parsed Profile instance.
        persist_directory: Optional ChromaDB storage directory.
        embedding_fn: Optional embedding function override.

    Returns:
        int: Number of chunks indexed.
    """
    client = get_chroma_client(persist_directory)
    fn = embedding_fn or get_embedding_function()
    collection = ensure_cosine_collection(client, fn)

    profile_id = profile.id or "default_profile"

    try:
        collection.delete(where={"profile_id": profile_id})
    except Exception as exc:
        logger.debug("Existing chunk cleanup notice: %s", exc)

    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[dict] = []

    if profile.skills:
        ids.append(f"{profile_id}_skills")
        documents.append(f"Candidate Skills: {', '.join(profile.skills)}")
        metadatas.append({"profile_id": profile_id, "chunk_type": "skills"})

    for idx, project in enumerate(profile.projects):
        bullets_text = " ".join(project.bullets)
        tech_text = ", ".join(project.tech)
        doc = f"Project: {project.title}. Technologies: {tech_text}. Details: {bullets_text}"
        ids.append(f"{profile_id}_project_{idx}")
        documents.append(doc)
        metadatas.append({
            "profile_id": profile_id,
            "chunk_type": "project",
            "title": project.title,
        })

    for idx, exp in enumerate(profile.experience):
        bullets_text = " ".join(exp.bullets)
        end = exp.end_date or "Present"
        doc = f"Experience: {exp.role} at {exp.company} ({exp.start_date} - {end}). Details: {bullets_text}"
        ids.append(f"{profile_id}_experience_{idx}")
        documents.append(doc)
        metadatas.append({
            "profile_id": profile_id,
            "chunk_type": "experience",
            "company": exp.company,
        })

    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("Successfully indexed %d chunks for profile_id=%s", len(ids), profile_id)

    return len(ids)


def query_profile_chunks_sync(
    query_text: str,
    top_k: int = 3,
    persist_directory: Optional[str] = None,
    embedding_fn: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Synchronously query the profile_chunks collection for the top matching chunks.

    Args:
        query_text: The search query text (e.g. required skills + summary).
        top_k: Number of nearest neighbors to retrieve.
        persist_directory: Optional directory override.
        embedding_fn: Optional embedding function override.

    Returns:
        List[Dict[str, Any]]: List of matched chunk details with raw and calibrated similarities.
    """
    client = get_chroma_client(persist_directory)
    fn = embedding_fn or get_embedding_function()
    collection = ensure_cosine_collection(client, fn)

    count = collection.count()
    if count == 0:
        return []

    n_results = min(top_k, count)
    results = collection.query(
        query_texts=[query_text],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    matched_chunks: List[Dict[str, Any]] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, distances):
        raw_sim, cal_sim = distance_to_similarity(dist)
        matched_chunks.append({
            "document": doc,
            "metadata": meta,
            "distance": round(dist, 4),
            "raw_similarity": raw_sim,
            "calibrated_similarity": cal_sim,
        })

    return matched_chunks


async def query_profile_chunks(
    query_text: str,
    top_k: int = 3,
    persist_directory: Optional[str] = None,
    embedding_fn: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Asynchronously query the profile_chunks collection using a thread worker to keep the event loop free."""
    return await asyncio.to_thread(
        query_profile_chunks_sync,
        query_text=query_text,
        top_k=top_k,
        persist_directory=persist_directory,
        embedding_fn=embedding_fn,
    )
