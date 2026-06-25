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


def mainstream_prior(
    films: list[Film],
    *,
    bayes_strength: float = 1000.0,
    w_quality: float = 0.4,
    w_popularity: float = 0.35,
    w_recency: float = 0.25,
) -> np.ndarray:
    """A [0,1] prior favouring well-rated, widely-seen, more recent films.

    - quality = Bayesian rating: `vote_average` shrunk toward the pool mean by `vote_count`
      (so a high score needs enough votes to count — no 9.0-from-12-votes flukes).
    - popularity = log1p(vote_count) — "how widely seen", steadier than TMDB `popularity`.
    - recency = normalized release year (missing year → treated as least-recent).
    Each sub-score is min-max normalized across the pool, then blended.
    """
    va = np.array([f.vote_average or 0.0 for f in films], dtype=float)
    vc = np.array([f.vote_count or 0.0 for f in films], dtype=float)
    yr = np.array([f.year or 0 for f in films], dtype=float)

    voted = vc > 0
    pool_mean = float(va[voted].mean()) if voted.any() else 6.5
    quality = (vc / (vc + bayes_strength)) * va + (
        bayes_strength / (vc + bayes_strength)
    ) * pool_mean
    popularity = np.log1p(vc)
    if (yr > 0).any():
        yr = np.where(yr > 0, yr, yr[yr > 0].min())

    return (
        w_quality * _minmax(quality) + w_popularity * _minmax(popularity) + w_recency * _minmax(yr)
    )


def score_candidates(
    cand_matrix: sp.spmatrix,
    taste: np.ndarray,
    provenance: list[int],
    prior: np.ndarray,
    *,
    w_content: float,
    w_graph: float,
    w_prior: float,
) -> np.ndarray:
    """Blend taste-match, the rec-graph signal, and the mainstream prior.

    All three components are min-max normalized to [0,1] so the weights are comparable.
    """
    content = _minmax(np.asarray(cand_matrix @ taste).ravel())
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
    weights: ScoreWeights | None = None,
) -> list[Recommendation]:
    """Full recommendation pass. `provenance` aligns to `candidate_films`.

    Knobs (`min_vote_count`, `weights`, `mmr_lambda`, …) are parameters so a later UI can
    expose them per request (mood / popularity / recency / genre-year filters).
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
    taste = taste_vector(watched_matrix, ratings, liked, user_mean, liked_bump)
    prior = mainstream_prior(candidate_films)
    scores = score_candidates(
        cand_matrix,
        taste,
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
