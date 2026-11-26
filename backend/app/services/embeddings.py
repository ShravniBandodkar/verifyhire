"""Text embeddings + vector index.

Default embedder is a dependency-free, deterministic feature-hashing model (word + bigram +
canonical-skill features, L2 normalised, 384-d) so search works offline in ~1 ms. The
`VectorIndex` uses pgvector (HNSW, cosine) when running on PostgreSQL with the extension,
otherwise an in-process NumPy matrix. Both expose the same search() call.
"""
import hashlib
import logging
import re

import numpy as np
from sqlalchemy import text

from ..core.db import IS_POSTGRES, engine

log = logging.getLogger("vector")
DIM = 384

SKILL_ALIASES = {
    "reactjs": "react", "react.js": "react", "nodejs": "node", "node.js": "node", "js": "javascript",
    "ts": "typescript", "golang": "go", "k8s": "kubernetes", "postgres": "postgresql", "gcp": "google cloud",
    "aws": "amazon web services", "ml": "machine learning", "nextjs": "next.js", "llm": "large language models",
    "fullstack": "full stack", "full-stack": "full stack", "springboot": "spring boot",
}
KNOWN_SKILLS = sorted({
    "python", "java", "javascript", "typescript", "react", "node", "next.js", "angular", "vue", "go", "rust",
    "c++", "c#", "kotlin", "swift", "flutter", "react native", "django", "fastapi", "flask", "spring boot",
    "postgresql", "mysql", "mongodb", "redis", "kafka", "elasticsearch", "docker", "kubernetes", "terraform",
    "amazon web services", "google cloud", "azure", "graphql", "rest", "microservices", "langchain", "rag",
    "machine learning", "deep learning", "pytorch", "tensorflow", "large language models", "sql", "tailwind",
    "html", "css", "ci/cd", "linux", "devops", "data engineering", "spark", "airflow", "figma", "full stack",
    "system design", "distributed systems", "iot", "selenium", "playwright", "jenkins", "git",
}, key=len, reverse=True)


def normalize_skill(s: str) -> str:
    s = s.strip().lower()
    return SKILL_ALIASES.get(s, s)


def extract_skills(text_: str) -> list[str]:
    t = " " + re.sub(r"[^a-z0-9+#./ ]", " ", text_.lower()) + " "
    for a, canon in SKILL_ALIASES.items():
        t = re.sub(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", canon, t)
    found = []
    for sk in KNOWN_SKILLS:
        if re.search(rf"(?<![a-z0-9]){re.escape(sk)}(?![a-z0-9+#])", t):
            found.append(sk)
    return found


def _h(tok: str) -> tuple[int, float]:
    d = hashlib.md5(tok.encode()).digest()
    return int.from_bytes(d[:4], "little") % DIM, 1.0 if d[4] & 1 else -1.0


def embed(text_: str) -> list[float]:
    v = np.zeros(DIM, dtype=np.float32)
    words = [normalize_skill(w) for w in re.findall(r"[a-z0-9+#.]+", text_.lower())]
    for w in words:
        i, s = _h("w:" + w); v[i] += s
    for a, b in zip(words, words[1:]):
        i, s = _h(f"b:{a}_{b}"); v[i] += 0.5 * s
    for sk in extract_skills(text_):  # skills get extra weight
        i, s = _h("s:" + sk); v[i] += 2.5 * s
    n = np.linalg.norm(v)
    return (v / n).round(5).tolist() if n else v.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return float(np.dot(np.asarray(a), np.asarray(b)))


class VectorIndex:
    def __init__(self):
        self.pg = False
        self._mem: dict[str, np.ndarray] = {}
        if IS_POSTGRES:
            try:
                with engine.begin() as c:
                    c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    c.execute(text(f"CREATE TABLE IF NOT EXISTS candidate_vectors (user_id varchar(32) primary key, vec vector({DIM}))"))
                    c.execute(text("CREATE INDEX IF NOT EXISTS candidate_vectors_hnsw ON candidate_vectors USING hnsw (vec vector_cosine_ops)"))
                self.pg = True
                log.info("Vector index: pgvector HNSW")
            except Exception as e:
                log.warning("pgvector unavailable, using in-memory index: %s", e)

    @property
    def backend(self) -> str:
        return "pgvector-hnsw" if self.pg else "numpy-inmemory"

    def upsert(self, user_id: str, vec: list[float]):
        if self.pg:
            try:
                with engine.begin() as c:
                    c.execute(text("INSERT INTO candidate_vectors (user_id, vec) VALUES (:u, :v) "
                                   "ON CONFLICT (user_id) DO UPDATE SET vec = EXCLUDED.vec"),
                              {"u": user_id, "v": str(vec)})
                return
            except Exception as e:
                log.warning("pgvector upsert failed: %s", e)
        self._mem[user_id] = np.asarray(vec, dtype=np.float32)

    def search(self, vec: list[float], allowed_ids: list[str] | None, k: int = 50) -> list[tuple[str, float]]:
        if self.pg:
            try:
                q = "SELECT user_id, 1 - (vec <=> :v) AS sim FROM candidate_vectors"
                params = {"v": str(vec), "k": k}
                if allowed_ids is not None:
                    if not allowed_ids:
                        return []
                    q += " WHERE user_id = ANY(:ids)"
                    params["ids"] = allowed_ids
                q += " ORDER BY vec <=> :v LIMIT :k"
                with engine.connect() as c:
                    return [(r[0], float(r[1])) for r in c.execute(text(q), params)]
            except Exception as e:
                log.warning("pgvector search failed: %s", e)
        ids = list(self._mem.keys()) if allowed_ids is None else [i for i in allowed_ids if i in self._mem]
        if not ids:
            return []
        M = np.stack([self._mem[i] for i in ids])
        sims = M @ np.asarray(vec, dtype=np.float32)
        order = np.argsort(-sims)[:k]
        return [(ids[i], float(sims[i])) for i in order]

    def size(self) -> int:
        if self.pg:
            try:
                with engine.connect() as c:
                    return int(c.execute(text("SELECT count(*) FROM candidate_vectors")).scalar())
            except Exception:
                pass
        return len(self._mem)


_index: VectorIndex | None = None


def index() -> VectorIndex:
    global _index
    if _index is None:
        _index = VectorIndex()
    return _index
