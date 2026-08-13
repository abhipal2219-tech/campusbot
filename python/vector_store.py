"""
vector_store.py
---------------
Simple TF-IDF Vector Database — no external ML libraries needed.
Uses only Python standard library (math, re, collections).
"""

import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    """Lowercase, remove punctuation, split into word tokens."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


class VectorStore:
    """
    A simple in-memory TF-IDF vector database.

    Usage:
        db = VectorStore()
        db.add_document("The cafeteria is on the ground floor", {"source": "rooms"})
        results = db.search("where is food", top_k=3)
    """

    def __init__(self):
        self.documents: list[str] = []          # raw text of each chunk
        self.metadata: list[dict] = []          # metadata dict per chunk
        self.tf_vectors: list[dict] = []        # TF vector per chunk
        self.idf: dict[str, float] = {}         # IDF weight per term
        self.vocab: set[str] = set()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def add_document(self, text: str, metadata: dict = None):
        """Add one document chunk to the store."""
        tokens = tokenize(text)
        tf = self._compute_tf(tokens)
        self.documents.append(text)
        self.metadata.append(metadata or {})
        self.tf_vectors.append(tf)
        self.vocab.update(tf.keys())
        # IDF is rebuilt lazily on first search
        self._idf_dirty = True

    def build_index(self):
        """Compute IDF weights across all documents (call after bulk add)."""
        N = len(self.documents)
        if N == 0:
            return
        df: dict[str, int] = Counter()
        for tf in self.tf_vectors:
            for term in tf:
                df[term] += 1
        self.idf = {
            term: math.log((N + 1) / (count + 1)) + 1  # smoothed IDF
            for term, count in df.items()
        }
        self._idf_dirty = False

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Return top_k most relevant chunks for the query.

        Returns a list of dicts:
          {"text": ..., "score": ..., "metadata": ...}
        """
        if self._idf_dirty:
            self.build_index()

        query_tokens = tokenize(query)
        query_tf = self._compute_tf(query_tokens)
        query_vec = self._tfidf_vector(query_tf)

        scored = []
        for i, tf in enumerate(self.tf_vectors):
            doc_vec = self._tfidf_vector(tf)
            score = self._cosine_similarity(query_vec, doc_vec)
            scored.append((score, i))

        scored.sort(reverse=True)
        results = []
        for score, idx in scored[:top_k]:
            if score > 0:
                results.append({
                    "text": self.documents[idx],
                    "score": round(score, 4),
                    "metadata": self.metadata[idx],
                })
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_tf(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts = Counter(tokens)
        total = len(tokens)
        return {term: count / total for term, count in counts.items()}

    def _tfidf_vector(self, tf: dict[str, float]) -> dict[str, float]:
        return {
            term: tf_val * self.idf.get(term, 0)
            for term, tf_val in tf.items()
        }

    @staticmethod
    def _cosine_similarity(vec_a: dict, vec_b: dict) -> float:
        # dot product
        common = set(vec_a) & set(vec_b)
        if not common:
            return 0.0
        dot = sum(vec_a[t] * vec_b[t] for t in common)
        norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
        norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def __len__(self):
        return len(self.documents)

    def __repr__(self):
        return f"VectorStore({len(self)} documents, {len(self.vocab)} unique terms)"
