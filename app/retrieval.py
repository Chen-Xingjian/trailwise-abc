"""Version-separated Qdrant Local index with explicit embedding identity."""

import hashlib
import re
import threading
import uuid
from pathlib import Path

import numpy as np
from qdrant_client import QdrantClient, models

from app.config import Settings
from app.release import Release, canonical_hash

QUERY_INSTRUCTION = "Retrieve evidence about the named Nepal trekking reference, stage endpoints, walking days or described corridor."


class HashEmbedder:
    """Lightweight lexical feature hashing for offline UI/CI; not a semantic model."""

    dimension = 512
    identity = "lexical-feature-hash-v1-512"

    def encode(self, texts: list[str], query: bool = False) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension, dtype=np.float32)
            words = re.findall(r"[a-z0-9]+", text.lower())
            for word in words:
                if word in {"the", "and", "of", "to", "for", "a", "is", "in", "what", "does"}:
                    continue
                word = word.removesuffix("s") if len(word) > 4 else word
                digest = hashlib.sha256(word.encode()).digest()
                vector[int.from_bytes(digest[:4], "little") % self.dimension] += 1
            norm = float(np.linalg.norm(vector))
            vectors.append((vector / norm if norm else vector).tolist())
        return vectors


class SentenceEmbedder:
    def __init__(self, model: str, device: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model, device=device, trust_remote_code=False)
        self.model.max_seq_length = 512
        self.dimension = self.model.get_sentence_embedding_dimension()
        self.identity = f"sentence-transformers:{model}:dim={self.dimension}:max512:{QUERY_INSTRUCTION}"
        self._lock = threading.Lock()

    def encode(self, texts: list[str], query: bool = False) -> list[list[float]]:
        prompt = f"Instruct: {QUERY_INSTRUCTION}\nQuery: " if query else None
        with self._lock:
            return self.model.encode(
                texts, prompt=prompt, normalize_embeddings=True, batch_size=4,
                show_progress_bar=False, convert_to_numpy=True,
            ).astype(np.float32).tolist()


def trip_budget_question(question: str) -> bool:
    text = question.casefold().replace("-", " ")
    # A numbered stage ("day five") is not a trip-wide time budget ("five days").
    calendar = (r"\b(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|several|few|a)\s+"
                r"(?:days?|weeks?)|weekends?|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
    transit = r"\b(?:travel(?:ling|ing)?|transport(?:ation)?|transfers?|journeys?|flights?|driv(?:e|ing)|getting to|door to door)\b"
    whole_trip = r"\b(?:full|whole|itinerary|holiday|vacation|round trip|plan(?:ning)?|fit)\b"
    return all(re.search(pattern, text) for pattern in (calendar, transit, whole_trip))


class Retriever:
    def __init__(self, release: Release, settings: Settings):
        self.release = release
        self._fact_scopes = {f["fact_id"]: f["scope"]["measurement_scope"] for f in release.facts}
        self._itinerary_refs = {f["scope"]["reference_id"] for f in release.facts
                                if f["scope"]["measurement_scope"] == "reference_itinerary"}
        self.embedder = (
            HashEmbedder() if settings.embedding_mode == "hash"
            else SentenceEmbedder(settings.embedding_model, settings.embedding_device)
        )
        fingerprint = release.index_fingerprint(self.embedder.identity)
        self.fingerprint = fingerprint
        db_path = Path(settings.runtime_dir) / "qdrant" / fingerprint
        db_path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(db_path))
        self.collection = "reviewed_facts"
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=self.embedder.dimension, distance=models.Distance.COSINE),
            )
            vectors = self.embedder.encode([c["text"] for c in release.chunks])
            self.client.upsert(self.collection, points=[
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["chunk_id"])),
                    vector=vector, payload=chunk,
                ) for chunk, vector in zip(release.chunks, vectors, strict=True)
            ])
        count = self.client.count(self.collection, exact=True).count
        if count != len(release.chunks):
            raise ValueError("Index count differs from the reviewed release; rebuild in a new runtime directory.")
        self._chunks_by_point = {
            str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["chunk_id"])): chunk for chunk in release.chunks
        }
        seen = set()
        offset = None
        while True:
            rows, offset = self.client.scroll(
                self.collection, limit=128, offset=offset, with_payload=True, with_vectors=False
            )
            for row in rows:
                point_id = str(row.id)
                expected = self._chunks_by_point.get(point_id)
                if expected is None or canonical_hash(row.payload) != canonical_hash(expected):
                    self.client.close()
                    raise ValueError("Stored index payload differs from the reviewed release; rebuild the index.")
                seen.add(point_id)
            if offset is None:
                break
        if seen != set(self._chunks_by_point):
            self.client.close()
            raise ValueError("Stored index IDs differ from the reviewed release.")
        self.count = count

    def _named_sequence(self, question: str, reference_id: str | None) -> str | None:
        """Narrow a simple list-of-stops question only when one published sequence fits."""
        text = question.casefold()
        daily = re.search(r"\b(daily stops|walking stages|overnight stops|stop each day|stop every day)\b", text)
        places = re.search(r"\b(which|what) (places|villages|stops)\b", text)
        if not (daily or places) or re.search(r"\b(time|hours?|distance|ascent|weather|gear|open|safe|cost|why|how)\b", text):
            return None
        matches = []
        for fact in self.release.facts:
            scope = fact["scope"]
            if reference_id and reference_id != scope["reference_id"]:
                continue
            if fact["value"]["kind"] != "ordered_sequence":
                continue
            if bool(daily) != (fact["predicate"] == "walking_boundary"):
                continue
            start, end = scope["walk_start"], scope["walk_finish"]
            if not start or not end:
                continue
            start_pos = text.find(start.casefold())
            end_pos = text.find(end.casefold())
            if start_pos < 0 or ("between " in text and end_pos < start_pos):
                continue
            if end_pos < 0 and not re.search(r"\bfrom " + re.escape(start.casefold()) + r"[?.!\s]*$", text):
                continue
            matches.append(fact["fact_id"])
        return matches[0] if len(matches) == 1 else None

    def search(self, question: str, limit: int = 3, reference_id: str | None = None) -> list[dict]:
        filters = None
        if reference_id:
            filters = models.Filter(must=[models.FieldCondition(
                key="reference_id", match=models.MatchValue(value=reference_id)
            )])
        sequence = self._named_sequence(question, reference_id)
        if sequence:
            filters = models.Filter(must=[models.FieldCondition(
                key="fact_id", match=models.MatchValue(value=sequence)
            )])
        itinerary = reference_id
        if itinerary is None and len(self._itinerary_refs) == 1:
            itinerary = next(iter(self._itinerary_refs))
        plan = itinerary in self._itinerary_refs and trip_budget_question(question)
        points = self.client.query_points(
            self.collection, query=self.embedder.encode([question], query=True)[0],
            query_filter=filters, limit=self.count if plan else limit, with_payload=True,
        ).points
        hits = [{**self._chunks_by_point[str(point.id)], "score": float(point.score)}
                for point in points if point.score > 0]
        if not plan:
            return hits

        # Keep similarity order within each aspect of a whole-trip planning question.
        scoped = [h for h in hits if h["reference_id"] == itinerary]
        route = [h for h in scoped if self._fact_scopes[h["fact_id"]] == "reference_itinerary"]
        prep = [h for h in scoped if self._fact_scopes[h["fact_id"]] == "general_preparation"]
        if not route or not prep:
            return hits[:limit]
        priority = route[:1] + prep[:1] + route[1:2]
        used = {h["fact_id"] for h in priority}
        return (priority + [h for h in hits if h["fact_id"] not in used])[:limit]

    def close(self):
        self.client.close()
