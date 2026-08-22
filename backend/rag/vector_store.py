"""ChromaDB vector store for verified ABIs and security invariants."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from pathlib import Path
from typing import List, Optional

from backend.config import RAG_DATA_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

ABI_FILES = [
    ("erc20", "erc20_abi.json"),
    ("uniswap_v2_router", "uniswap_v2_router_abi.json"),
    ("uniswap_v3_router", "uniswap_v3_router_abi.json"),
    ("aave_v3_pool", "aave_v3_pool_abi.json"),
]


class HashingEmbeddingFunction:
    """Lightweight bag-of-tokens embedding — no ONNX / network download required."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    @staticmethod
    def name() -> str:
        return "aegis-hashing"

    def get_config(self) -> dict:
        return {"dim": self.dim}

    @staticmethod
    def build_from_config(config: dict) -> "HashingEmbeddingFunction":
        return HashingEmbeddingFunction(dim=int(config.get("dim", 384)))

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        if not tokens:
            return vec
        for tok in tokens:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return [self._embed_one(t) for t in input]

    def embed_query(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        """Chroma expects Embeddings (batch), same shape as __call__."""
        return self(input)


class VectorStore:
    """Ingests ABI + invariant documents and exposes semantic query_specs()."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        data_dir: Optional[Path] = None,
        *,
        in_memory: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.data_dir = data_dir or RAG_DATA_DIR
        self.in_memory = in_memory
        self._collection = None
        self._fallback_docs: List[dict] = []
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            embedding_fn = HashingEmbeddingFunction()

            if self.in_memory:
                client = chromadb.Client(
                    ChromaSettings(anonymized_telemetry=False)
                )
            else:
                Path(self.settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(
                    path=self.settings.chroma_persist_dir,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )

            self._collection = client.get_or_create_collection(
                name=self.settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
                embedding_function=embedding_fn,
            )
            if self._collection.count() == 0:
                self.ingest_fixtures()
            logger.info(
                "Chroma collection '%s' ready (%s docs)",
                self.settings.chroma_collection,
                self._collection.count(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Chroma unavailable (%s) — using in-process keyword fallback",
                exc,
            )
            self._collection = None
            self._load_fallback_docs()

    def ingest_fixtures(self) -> int:
        """Load sample ABIs and security invariants into the vector store."""
        docs, ids, metadatas = [], [], []

        for protocol, filename in ABI_FILES:
            path = self.data_dir / filename
            if not path.exists():
                continue
            abi = json.loads(path.read_text(encoding="utf-8"))
            methods = [
                entry.get("name")
                for entry in abi
                if entry.get("type") == "function" and entry.get("name")
            ]
            text = (
                f"Verified ABI for {protocol}. "
                f"Valid function names: {', '.join(methods)}. "
                f"Raw ABI JSON: {json.dumps(abi)[:1500]}"
            )
            docs.append(text)
            ids.append(f"abi-{protocol}")
            metadatas.append({"kind": "abi", "protocol": protocol})

        inv_path = self.data_dir / "security_invariants.json"
        if inv_path.exists():
            payload = json.loads(inv_path.read_text(encoding="utf-8"))
            for item in payload.get("invariants", []):
                tags = ", ".join(item.get("tags", []))
                text = f"[{item['id']}] {item['text']} Tags: {tags}"
                docs.append(text)
                ids.append(item["id"])
                metadatas.append({"kind": "invariant", "id": item["id"]})

        if not docs:
            return 0

        if self._collection is not None:
            # Upsert-friendly: delete existing ids then add
            try:
                self._collection.delete(ids=ids)
            except Exception:  # noqa: BLE001
                pass
            self._collection.add(documents=docs, ids=ids, metadatas=metadatas)
        else:
            self._fallback_docs = [
                {"id": i, "text": d, "meta": m}
                for i, d, m in zip(ids, docs, metadatas)
            ]

        return len(docs)

    def _load_fallback_docs(self) -> None:
        self._fallback_docs = []
        # Reuse ingest path without chroma
        saved = self._collection
        self._collection = None
        self.ingest_fixtures()
        self._collection = saved

    def query_specs(self, query: str, top_k: int = 3) -> List[str]:
        """Retrieve top-k security specs / ABI snippets for a query."""
        if not query.strip():
            return []

        if self._collection is not None:
            try:
                result = self._collection.query(
                    query_texts=[query],
                    n_results=top_k,
                )
                docs = result.get("documents") or [[]]
                return list(docs[0] or [])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chroma query failed: %s", exc)

        return self._keyword_query(query, top_k)

    def _keyword_query(self, query: str, top_k: int) -> List[str]:
        if not self._fallback_docs:
            self._load_fallback_docs()

        tokens = {t.lower() for t in query.replace(",", " ").split() if len(t) > 2}
        scored: List[tuple[int, str]] = []
        for doc in self._fallback_docs:
            text = doc["text"]
            lower = text.lower()
            score = sum(1 for t in tokens if t in lower)
            # Boost exact method / protocol hits
            if "transfer" in query.lower() and "transfer" in lower:
                score += 2
            if "approve" in query.lower() and "approve" in lower:
                score += 2
            if "swap" in query.lower() and "uniswap" in lower:
                score += 2
            if "hallucin" in query.lower() or "safeTransfer" in query:
                if "hallucination" in lower or "method" in lower:
                    score += 3
            scored.append((score, text))

        scored.sort(key=lambda x: x[0], reverse=True)
        hits = [t for s, t in scored if s > 0][:top_k]
        if not hits:
            # Always return some grounding context
            hits = [d["text"] for d in self._fallback_docs[:top_k]]
        return hits
