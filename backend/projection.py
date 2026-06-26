"""2D projection, clustering, and similarity edges (SPEC §4.5).

UMAP projects the feature matrix to 2D **server-side only** (architecture guardrail — never
in the browser; the frontend animates precomputed coords). We cluster the 2D layout so clusters
match what the eye sees, auto-label each by its dominant genre, and draw kNN-cosine edges tagged
with the strongest shared trait.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import scipy.sparse as sp
import umap
from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors

from backend.models import Edge, Film


def project_2d(matrix: sp.spmatrix, *, seed: int = 42) -> np.ndarray:
    """Project rows to 2D with cosine-metric UMAP. Returns an (n, 2) array."""
    n = matrix.shape[0]
    if n <= 2:  # UMAP needs a few points; degenerate layout otherwise
        return np.zeros((n, 2), dtype=float)
    reducer = umap.UMAP(
        n_components=2,
        metric="cosine",
        n_neighbors=min(15, n - 1),
        min_dist=0.1,
        init="random",  # robust + deterministic across sizes
        random_state=seed,
    )
    return np.asarray(reducer.fit_transform(matrix), dtype=float)


def cluster_2d(coords: np.ndarray, *, target_per_cluster: int = 40) -> np.ndarray:
    """Partition the 2D layout into legible regions with KMeans.

    KMeans (not HDBSCAN) because a taste map wants *every* poster to belong to a labelled
    region — density clustering lumped concentrated tastes into one mega-blob + noise.
    """
    n = coords.shape[0]
    if n < 8:
        return np.zeros(n, dtype=int)  # too small to partition meaningfully
    k = max(4, min(8, round(n / target_per_cluster)))
    return KMeans(n_clusters=min(k, n), n_init=10, random_state=42).fit_predict(coords).astype(int)


def cluster_labels(films: list[Film], labels: np.ndarray) -> dict[int, str]:
    """Label each cluster by its most *distinctive* genres (lift vs. the global mix).

    Using raw frequency makes every cluster "drama" (it's ubiquitous); lift surfaces what
    actually sets a region apart (e.g. "crime · thriller").
    """
    total = len(films)
    global_counts = Counter(g for f in films for g in f.genres)
    out: dict[int, str] = {}
    for cid in {int(c) for c in labels}:
        if cid == -1:
            continue
        members = [f for f, lab in zip(films, labels, strict=False) if lab == cid]
        local = Counter(g for f in members for g in f.genres)
        if not local:
            out[cid] = f"cluster {cid}"
            continue

        n_members = len(members)

        def _lift(g: str, local: Counter = local, n: int = n_members) -> float:
            return (local[g] / n) / (global_counts[g] / total)

        ranked = sorted((g for g in local if local[g] >= 2), key=_lift, reverse=True)
        ranked = ranked or [local.most_common(1)[0][0]]
        out[cid] = " · ".join(g.lower() for g in ranked[:2])
    return out


def _shared_trait(a: Film, b: Film) -> str:
    """The strongest trait two films share (SPEC §5 edge `shared`)."""
    if a.director and a.director == b.director:
        return "director"
    if set(a.top_cast) & set(b.top_cast):
        return "cast"
    if set(a.keywords) & set(b.keywords):
        return "keyword"
    return "genre"  # default; shared genres or just feature-space proximity


def similarity_edges(
    matrix: sp.spmatrix, films: list[Film], *, k: int = 6, threshold: float = 0.08
) -> list[Edge]:
    """kNN-cosine edges, deduped undirected, tagged with shared trait.

    Each node always keeps its single nearest neighbour (so the constellation is connected —
    no orphan dots), plus any other neighbours scoring above `threshold`. These sparse TF-IDF
    vectors are near-orthogonal, so a high absolute threshold leaves almost nothing connected;
    the nearest-neighbour floor guarantees a legible web regardless.
    """
    n = matrix.shape[0]
    if n < 2:
        return []
    kk = min(k + 1, n)  # +1: the nearest neighbour is the node itself
    nn = NearestNeighbors(n_neighbors=kk, metric="cosine").fit(matrix)
    distances, indices = nn.kneighbors(matrix)

    seen: set[tuple[int, int]] = set()
    edges: list[Edge] = []
    for i in range(n):
        kept_nearest = False
        for pos in range(kk):
            j = int(indices[i][pos])
            if j == i:  # skip self (not always at pos 0 when vectors tie)
                continue
            sim = 1.0 - float(distances[i][pos])
            is_nearest = not kept_nearest  # the closest non-self neighbour
            kept_nearest = True
            if sim < threshold and not is_nearest:
                continue
            a, b = sorted((i, j))
            if (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append(
                Edge(
                    source=f"tmdb:{films[a].tmdb_id}",
                    target=f"tmdb:{films[b].tmdb_id}",
                    weight=round(sim, 3),
                    shared=_shared_trait(films[a], films[b]),
                )
            )
    return edges
