"""Lightweight RAG over user-uploaded docs (per session).

Local sentence-transformer embeddings + Chroma. No external key. Retrieval is
kept fast (<~150 ms) so it fits inside the copilot latency budget. Ingest
supports PDF / DOCX / TXT.
"""
from __future__ import annotations

import logging
import os
import uuid

import chromadb

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _read_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(path).paragraphs)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    words, chunks, i = text.split(), [], 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return [c for c in chunks if c.strip()]


class RAGPipeline:
    def __init__(self, collection: str = "meeting_ctx") -> None:
        s = get_settings()
        self._client = chromadb.PersistentClient(path=s.chroma_db_path)
        # Chroma's default embedding fn (all-MiniLM-L6-v2) runs locally.
        self._collection = self._client.get_or_create_collection(name=collection)

    def ingest_file(self, path: str) -> int:
        text = _read_file(path)
        return self.ingest_text(text, source=os.path.basename(path))

    def ingest_text(self, text: str, source: str = "note") -> int:
        chunks = _chunk(text)
        if not chunks:
            return 0
        self._collection.add(
            documents=chunks,
            ids=[f"{source}-{uuid.uuid4().hex[:8]}-{i}" for i in range(len(chunks))],
            metadatas=[{"source": source} for _ in chunks],
        )
        logger.info("📚 RAG ingested %d chunks from %s", len(chunks), source)
        return len(chunks)

    def retrieve(self, query: str, k: int = 4) -> list[str]:
        if not query.strip():
            return []
        try:
            res = self._collection.query(query_texts=[query], n_results=k)
        except Exception as e:
            logger.debug("RAG retrieve error: %s", e)
            return []
        docs = res.get("documents") or [[]]
        return docs[0] if docs else []

    def context_block(self, query: str, k: int = 4) -> str:
        hits = self.retrieve(query, k)
        return "\n---\n".join(hits) if hits else ""
