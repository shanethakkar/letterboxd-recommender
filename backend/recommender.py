"""Content-based hybrid recommender (SPEC §4.4).

Pipeline: build a **taste vector** as a rating-weighted mean of watched-film vectors
(films below the user's average pull negative; liked films get a bump) → score candidates
by cosine to the taste vector, blended with a small popularity prior and the TMDB
rec-graph provenance signal → **MMR** re-rank for diversity → attach a "why" (each rec's
nearest watched neighbours + the strongest shared traits). Sparse profiles fall back
toward popularity so the map never renders empty.

The math functions take plain matrices (sparse or dense), so they're unit-tested with
small synthetic arrays, independent of feature extraction.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from backend.features import build_feature_matrix
from backend.models import Because, Film, Recommendation

MIN_RATED_FOR_TASTE = 8  # below this, lean on popularity (sparse-profile fallback)
DEFAULT_LIKED_BUMP = 0.5


def _l2(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def _minmax(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)


def taste_vector(
    matrix: sp.spmatrix,
    ratings: list[float | None],
    liked: list[bool],
    user_mean: float,
    liked_bump: float = DEFAULT_LIKED_BUMP,
) -> np.ndarray:
    """Rating-weighted, L2-normalized mean of watched vectors.

    weight = (rating − user_mean), plus `liked_bump` if liked. Below-average films get a
    negative weight and pull the taste vector away from their traits.
    """
    weights = np.zeros(matrix.shape[0], dtype=float)
    for i, (r, lk) in enumerate(zip(ratings, liked, strict=True)):
        w = (r - user_mean) if r is not None else 0.0
        if lk:
            w += liked_bump
        weights[i] = w
    taste = np.asarray(matrix.T @ weights).ravel()  # (n,)·(n×d) → (d,)
    return _l2(taste)


def score_candidates(
    cand_matrix: sp.spmatrix,
    taste: np.ndarray,
    provenance: list[int],
    popularity: list[float | None],
    *,
    w_content: float,
    w_graph: float,
    w_pop: float,
) -> np.ndarray:
    """Blend cosine-to-taste with the rec-graph signal and a popularity prior."""
    content = np.asarray(cand_matrix @ taste).ravel()  # cosine (rows are L2-normalized)
    graph = _minmax(np.log1p(np.asarray(provenance, dtype=float)))
    pop = _minmax(np.log1p(np.asarray([p or 0.0 for p in popularity], dtype=float)))
    return w_content * content + w_graph * graph + w_pop * pop


def mmr_select(
    pool_matrix: sp.spmatrix,
    base_scores: np.ndarray,
    k: int,
    lambda_: float = 0.7,
) -> list[int]:
    """Maximal Marginal Relevance: pick k indices balancing score vs. novelty."""
    scores = _minmax(base_scores)
    sim = pool_matrix @ pool_matrix.T
    sim = sim.toarray() if sp.issparse(sim) else np.asarray(sim)

    selected: list[int] = []
    remaining = set(range(len(scores)))
    while remaining and len(selected) < k:
        if not selected:
            best = max(remaining, key=lambda i: scores[i])
        else:
            best = max(
                remaining,
                key=lambda i: (
                    lambda_ * scores[i] - (1 - lambda_) * max(sim[i, j] for j in selected)
                ),
            )
        selected.append(best)
        remaining.discard(best)
    return selected


def _explanations(
    cand_row: np.ndarray,
    watched_matrix: sp.spmatrix,
    watched_films: list[Film],
    k: int = 3,
) -> tuple[list[Because], list[Film]]:
    """Top-k nearest watched neighbours of a candidate → explanation edges."""
    sims = np.asarray(watched_matrix @ cand_row).ravel()
    top = np.argsort(-sims)[:k]
    because: list[Because] = []
    neighbours: list[Film] = []
    for i in top:
        if sims[i] <= 0:
            continue
        f = watched_films[i]
        because.append(
            Because(id=f"tmdb:{f.tmdb_id}", title=f.title, contribution=round(float(sims[i]), 3))
        )
        neighbours.append(f)
    return because, neighbours


def _shared_traits(cand: Film, neighbours: list[Film], limit: int = 4) -> list[str]:
    """Strongest traits the candidate shares with its explanation neighbours."""
    traits: list[str] = []
    n_dirs = {f.director for f in neighbours if f.director}
    n_genres = {g for f in neighbours for g in f.genres}
    n_keywords = {k for f in neighbours for k in f.keywords}
    n_cast = {c for f in neighbours for c in f.top_cast}

    if cand.director and cand.director in n_dirs:
        traits.append(f"dir. {cand.director}")
    traits.extend(g for g in cand.genres if g in n_genres)
    traits.extend(k for k in cand.keywords if k in n_keywords)
    traits.extend(c for c in cand.top_cast if c in n_cast)
    # de-dupe preserving order, cap
    seen: set[str] = set()
    out = [t for t in traits if not (t in seen or seen.add(t))]
    return out[:limit]


def recommend(
    watched_films: list[Film],
    candidate_films: list[Film],
    provenance: list[int],
    *,
    user_mean: float,
    top_n: int = 20,
    mmr_pool: int = 150,
    mmr_lambda: float = 0.7,
    liked_bump: float = DEFAULT_LIKED_BUMP,
) -> list[Recommendation]:
    """Full Phase-1 recommendation pass. `provenance` aligns to `candidate_films`."""
    if not candidate_films:
        return []

    # One shared vocabulary over watched + candidates (SPEC §4.3).
    matrix, _names = build_feature_matrix(watched_films + candidate_films)
    nw = len(watched_films)
    watched_matrix, cand_matrix = matrix[:nw], matrix[nw:]

    ratings = [f.rating for f in watched_films]
    liked = [f.liked for f in watched_films]
    n_rated = sum(1 for r in ratings if r is not None)

    # Sparse-profile fallback: too little rating signal → lean on popularity/graph.
    if n_rated < MIN_RATED_FOR_TASTE:
        w_content, w_graph, w_pop = 0.5, 0.3, 0.5
    else:
        w_content, w_graph, w_pop = 1.0, 0.25, 0.1

    taste = taste_vector(watched_matrix, ratings, liked, user_mean, liked_bump)
    scores = score_candidates(
        cand_matrix,
        taste,
        provenance,
        [f.popularity for f in candidate_films],
        w_content=w_content,
        w_graph=w_graph,
        w_pop=w_pop,
    )

    # Pre-limit to the strongest `mmr_pool`, then MMR-rerank to `top_n`.
    pool = np.argsort(-scores)[:mmr_pool]
    sel_local = mmr_select(cand_matrix[pool], scores[pool], top_n, mmr_lambda)
    selected = [int(pool[i]) for i in sel_local]

    recs: list[Recommendation] = []
    for idx in selected:
        cand = candidate_films[idx]
        cand_row = np.asarray(cand_matrix[idx].toarray()).ravel()
        because, neighbours = _explanations(cand_row, watched_matrix, watched_films)
        recs.append(
            Recommendation(
                id=f"tmdb:{cand.tmdb_id}",
                tmdb_id=cand.tmdb_id,
                title=cand.title,
                year=cand.year,
                score=round(float(scores[idx]), 4),
                because=because,
                shared_traits=_shared_traits(cand, neighbours),
            )
        )
    return recs
