"""
Knowledge Base — indexes Title 24, PINs, and CANs into ChromaDB for RAG retrieval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import config

try:
    import chromadb
    from chromadb.utils import embedding_functions
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


class HCAIKnowledgeBase:
    """
    Builds and queries a vector store of HCAI regulatory content.

    Each document entry in the store contains:
      - id       : unique identifier (e.g. "T24-420.3", "PIN-25-04")
      - document : the full regulatory text passage
      - metadata : { "source": "Title 24 Part 2", "section": "420.3", "type": "mandatory" }
    """

    COLLECTION = config.RAG_COLLECTION_NAME

    def __init__(self, persist_dir: str | Path | None = None) -> None:
        if not HAS_CHROMA:
            raise ImportError("chromadb is required: pip install chromadb")

        persist_path = str(persist_dir or config.CHROMA_DB_DIR)
        self._client = chromadb.PersistentClient(path=persist_path)
        ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION,
            embedding_function=ef,
        )

    def load_from_files(
        self,
        title24_file: str | Path | None = None,
        pins_file: str | Path | None = None,
    ) -> int:
        """Index regulatory documents from JSON files. Returns documents added."""
        added = 0

        for filepath, doc_type in [
            (title24_file or config.TITLE24_REFS_FILE, "Title 24"),
            (pins_file or config.PINS_FILE, "PIN/CAN"),
        ]:
            path = Path(filepath)
            if not path.exists():
                continue
            with open(path) as f:
                entries = json.load(f)

            ids, docs, metas = [], [], []
            for entry in entries:
                doc_id = entry["id"]
                # Skip if already indexed
                existing = self._collection.get(ids=[doc_id])
                if existing["ids"]:
                    continue
                ids.append(doc_id)
                docs.append(entry["text"])
                metas.append({
                    "source": entry.get("source", doc_type),
                    "section": entry.get("section", ""),
                    "type": entry.get("type", "regulatory"),
                    "discipline": entry.get("discipline", "General"),
                })

            if ids:
                self._collection.add(documents=docs, ids=ids, metadatas=metas)
                added += len(ids)

        return added

    def query(self, query_text: str, top_k: int = config.RAG_TOP_K) -> list[dict]:
        """Return top-k most relevant regulatory passages."""
        results = self._collection.query(
            query_texts=[query_text],
            n_results=top_k,
        )
        passages = []
        for i, doc in enumerate(results["documents"][0]):
            passages.append({
                "text": doc,
                "id": results["ids"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return passages

    def count(self) -> int:
        return self._collection.count()
