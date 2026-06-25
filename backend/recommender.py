"""Content-based hybrid recommender (SPEC §4.4).

Pipeline: build a **taste vector** as a rating-weighted mean of watched-film vectors
(films below the user's average pull negative; liked films get a bump) → drop obscure
candidates (vote-count floor) → score the rest by cosine to the taste vector, blended
with the TMDB rec-graph signal and a **mainstream prior** (quality + popularity + recency)
→ **MMR** re-rank for diversity → attach a "why" drawn only from the user's highly-rated
films. Sparse profiles lean harder on the prior so the map never renders empty.

All score components are min-max normalized to [0,1], so the blend weights mean what they
say. The math functions take plain matrices (sparse or dense) → unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from sklearn.cluster import KMeans

from backend.features import build_feature_matrix
from backend.models import Because, Film, Recommendation

MIN_RATED_FOR_TASTE = 8  # below this, lean on the prior (sparse-profile fallback)
DEFAULT_LIKED_BUMP = 0.5
DEFAULT_MIN_VOTE_COUNT = 500  # candidate floor: drop films few people have rated


@dataclass(frozen=True)
class ScoreWeights:
    """Blend weights for the three normalized score components."""

    content: float  # cosine to the taste vector (relevance)
    graph: float  # TMDB recommendation-graph provenance
    prior: float  # mainstream prior (quality + popularity + recency)


# Lean mainstream but keep taste in the driver's seat; sparse profiles lean further on prior.
DEFAULT_WEIGHTS = ScoreWeights(content=0.55, graph=0.15, prior=0.45)
SPARSE_WEIGHTS = ScoreWeights(content=0.35, graph=0.15, prior=0.60)


def _l2(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def _minmax(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)


def _rating_weights(
    ratings: list[float | None], liked: list[bool], user_mean: float, liked_bump: float
) -> np.ndarray:
    """Per-film taste weight = (rating − user_mean), plus `liked_bump` if liked."""
    weights = np.zeros(len(ratings), dtype=float)
    for i, (r, lk) in enumerate(zip(ratings, liked, strict=True)):
        w = (r - user_mean) if r is not None else 0.0
        if lk:
            w += liked_bump
        weights[i] = w
    return weights


def taste_vector(
    matrix: sp.spmatrix,
    ratings: list[float | None],
    liked: list[bool],
    user_mean: float,
    liked_bump: float = DEFAULT_LIKED_BUMP,
) -> np.ndarray:
    """Single rating-weighted, L2-normalized mean of watched vectors.

    Below-average films get a negative weight and pull the vector away from their traits.
    """
    weights = _rating_weights(ratings, liked, user_mean, liked_bump)
    return _l2(np.asarray(matrix.T @ weights).ravel())  # (n,)·(n×d) → (d,)


def _cluster_centroids(matrix: sp.spmatrix, weights: np.ndarray, n_clusters: int) -> np.ndarray:
    """KMeans the rows into ≤ n_clusters facets; each centroid = weighted, L2-normed mean."""
    k = max(1, min(n_clusters, matrix.shape[0]))
    if k == 1:
        return _l2(np.asarray(matrix.T @ weights).ravel())[np.newaxis, :]
    labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(matrix)
    centroids = []
    for c in range(k):
        members = np.flatnonzero(labels == c)
        if members.size == 0:
            continue
        vec = np.asarray(matrix[members].T @ weights[members]).ravel()
        centroids.append(_l2(vec))
    return np.vstack(centroids)


def taste_centroids(
    matrix: sp.spmatrix,
    ratings: list[float | None],
    liked: list[bool],
    user_mean: float,
    *,
    n_clusters: int,
    liked_bump: float = DEFAULT_LIKED_BUMP,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Cluster the user's loved films into taste facets (fixes single-centroid mush).

    Returns (positive_centroids [k×d], negative_centroid [d] or None). Loved (positively
    weighted) films are clustered into ≤ n_clusters facets; a candidate then matches the
    *best* facet rather than being averaged into one vector. The negative centroid
    summarises disliked films and is subtracted at scoring time.
    """
    weights = _rating_weights(ratings, liked, user_mean, liked_bump)
    pos_idx = np.flatnonzero(weights > 0)
    neg_idx = np.flatnonzero(weights < 0)

    if pos_idx.size == 0:  # no positive signal → one centroid from everything
        pos_centroids = _l2(np.asarray(matrix.T @ weights).ravel())[np.newaxis, :]
    else:
        pos_centroids = _cluster_centroids(matrix[pos_idx], weights[pos_idx], n_clusters)

    neg_centroid = None
    if neg_idx.size:
        neg_centroid = _l2(np.asarray(matrix[neg_idx].T @ (-weights[neg_idx])).ravel())
    return pos_centroids, neg_centroid


def content_scores(
    cand_matrix: sp.spmatrix,
    pos_centroids: np.ndarray,
    neg_centroid: np.ndarray | None,
    *,
    neg_penalty: float = 0.3,
) -> np.ndarray:
    """Per-candidate taste similarity = best match across facets, minus a dislike penalty."""
    sims = np.asarray(cand_matrix @ pos_centroids.T)  # (m × k)
    best = sims.max(axis=1)
    if neg_centroid is not None:
        neg = np.asarray(cand_matrix @ neg_centroid).ravel()
        best = best - neg_penalty * np.maximum(neg, 0.0)
    return best


def mainstream_prior(
    films: list[Film],
    *,
    bayes_strength: float = 1000.0,
    w_quality: float = 0.4,
    w_popularity: float = 0.35,
    w_recency: float = 0.25,
) -> np.ndarray:
    """A [0,1] prior favouring well-rated, widely-seen, more recent films.

    - quality = per-film mean of the available review scores on a 0–10 scale: a TMDB
      Bayesian rating (vote_average shrunk toward the pool mean by vote_count — no
      9.0-from-12-votes flukes), plus IMDb rating and Metacritic/10 when OMDb-enriched.
      Films without OMDb data just use the TMDB score (graceful).
    - popularity = log1p(vote_count) — "how widely seen", steadier than TMDB `popularity`.
    - recency = normalized release year (missing year → treated as least-recent).
    Each sub-score is min-max normalized across the pool, then blended.
    """
    va = np.array([f.vote_average or 0.0 for f in films], dtype=float)
    vc = np.array([f.vote_count or 0.0 for f in films], dtype=float)
    yr = np.array([f.year or 0 for f in films], dtype=float)

    voted = vc > 0
    pool_mean = float(va[voted].mean()) if voted.any() else 6.5
    tmdb_bayes = (vc / (vc + bayes_strength)) * va + (
        bayes_strength / (vc + bayes_strength)
    ) * pool_mean

    quality = np.empty(len(films), dtype=float)
    for i, f in enumerate(films):
        signals = [float(tmdb_bayes[i])]
        if f.imdb_rating is not None:
            signals.append(f.imdb_rating)
        if f.metascore is not None:
            signals.append(f.metascore / 10.0)
        quality[i] = sum(signals) / len(signals)

    popularity = np.log1p(vc)
    if (yr > 0).any():
        yr = np.where(yr > 0, yr, yr[yr > 0].min())

    return (
        w_quality * _minmax(quality) + w_popularity * _minmax(popularity) + w_recency * _minmax(yr)
    )


def score_candidates(
    content_raw: np.ndarray,
    provenance: list[int],
    prior: np.ndarray,
    *,
    w_content: float,
    w_graph: float,
    w_prior: float,
) -> np.ndarray:
    """Blend taste-match, the rec-graph signal, and the mainstream prior.

    All three components are min-max normalized to [0,1] so the weights are comparable.
    `content_raw` is the per-candidate taste similarity (single-centroid cosine, or the
    max-over-facets score from `content_scores`).
    """
    content = _minmax(content_raw)
    graph = _minmax(np.log1p(np.asarray(provenance, dtype=float)))
    return w_content * content + w_graph * graph + w_prior * prior


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


def _apply_vote_floor(
    films: list[Film],
    provenance: list[int],
    min_vote_count: int,
    top_n: int,
) -> tuple[list[Film], list[int]]:
    """Drop candidates below the vote-count floor; relax only to avoid fewer than `top_n`."""
    order = sorted(range(len(films)), key=lambda i: films[i].vote_count or 0, reverse=True)
    survivors = [i for i in order if (films[i].vote_count or 0) >= min_vote_count]
    if len(survivors) < top_n:
        survivors = order[:top_n]
    return [films[i] for i in survivors], [provenance[i] for i in survivors]


def _explanations(
    cand_row: np.ndarray,
    watched_matrix: sp.spmatrix,
    watched_films: list[Film],
    eligible: list[int],
    k: int = 3,
) -> tuple[list[Because], list[Film]]:
    """Top-k nearest *highly-rated* watched neighbours of a candidate → explanation edges.

    Only films in `eligible` (rated at/above the user's average, or liked) may explain a
    rec, so "because you rated X" always points at a film the user actually liked.
    """
    sims = np.asarray(watched_matrix @ cand_row).ravel()
    ranked = sorted((i for i in eligible if sims[i] > 0), key=lambda i: sims[i], reverse=True)
    because: list[Because] = []
    neighbours: list[Film] = []
    for i in ranked[:k]:
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
    min_vote_count: int = DEFAULT_MIN_VOTE_COUNT,
    mmr_pool: int = 150,
    mmr_lambda: float = 0.7,
    liked_bump: float = DEFAULT_LIKED_BUMP,
    n_clusters: int = 1,
    weights: ScoreWeights | None = None,
) -> list[Recommendation]:
    """Full recommendation pass. `provenance` aligns to `candidate_films`.

    `n_clusters=1` uses a single taste vector (today's default); `>1` clusters the user's
    loved films into facets and scores each candidate by its best-matching facet
    (max-over-centroids). Knobs (`min_vote_count`, `weights`, `mmr_lambda`, …) are parameters
    so a later UI can expose them per request (mood / popularity / recency / genre-year filters).
    """
    if not candidate_films:
        return []

    # 1. Drop obscure candidates before anything else (biggest lever against niche recs).
    candidate_films, provenance = _apply_vote_floor(
        candidate_films, provenance, min_vote_count, top_n
    )

    # 2. One shared vocabulary over watched + surviving candidates (SPEC §4.3).
    matrix, _names = build_feature_matrix(watched_films + candidate_films)
    nw = len(watched_films)
    watched_matrix, cand_matrix = matrix[:nw], matrix[nw:]

    ratings = [f.rating for f in watched_films]
    liked = [f.liked for f in watched_films]
    n_rated = sum(1 for r in ratings if r is not None)
    w = weights or (SPARSE_WEIGHTS if n_rated < MIN_RATED_FOR_TASTE else DEFAULT_WEIGHTS)

    # 3. Score = taste-match + rec-graph + mainstream prior.
    if n_clusters <= 1:
        taste = taste_vector(watched_matrix, ratings, liked, user_mean, liked_bump)
        content_raw = np.asarray(cand_matrix @ taste).ravel()
    else:
        pos_c, neg_c = taste_centroids(
            watched_matrix,
            ratings,
            liked,
            user_mean,
            n_clusters=n_clusters,
            liked_bump=liked_bump,
        )
        content_raw = content_scores(cand_matrix, pos_c, neg_c)

    prior = mainstream_prior(candidate_films)
    scores = score_candidates(
        content_raw,
        provenance,
        prior,
        w_content=w.content,
        w_graph=w.graph,
        w_prior=w.prior,
    )

    # 4. Pre-limit to the strongest `mmr_pool`, then MMR-rerank to `top_n`.
    pool = np.argsort(-scores)[:mmr_pool]
    sel_local = mmr_select(cand_matrix[pool], scores[pool], top_n, mmr_lambda)
    selected = [int(pool[i]) for i in sel_local]

    # Explanations come only from films the user rated highly (≥ their average) or liked.
    eligible = [
        i
        for i, f in enumerate(watched_films)
        if (f.rating is not None and f.rating >= user_mean) or f.liked
    ]
    if not eligible:
        eligible = list(range(len(watched_films)))

    recs: list[Recommendation] = []
    for idx in selected:
        cand = candidate_films[idx]
        cand_row = np.asarray(cand_matrix[idx].toarray()).ravel()
        because, neighbours = _explanations(cand_row, watched_matrix, watched_films, eligible)
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
