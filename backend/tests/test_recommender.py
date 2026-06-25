"""Recommender math: taste direction, scoring, MMR diversity, why, sparse fallback."""

import numpy as np
import scipy.sparse as sp

from backend.models import Film
from backend.recommender import (
    _explanations,
    mmr_select,
    recommend,
    score_candidates,
    taste_vector,
)


def test_taste_vector_points_toward_liked_traits() -> None:
    # Two orthogonal traits; film 0 rated above mean, film 1 below.
    matrix = sp.csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
    taste = taste_vector(matrix, [5.0, 1.0], [False, False], user_mean=3.0, liked_bump=0.0)
    assert taste[0] > 0  # toward the high-rated film's trait
    assert taste[1] < 0  # away from the low-rated film's trait


def test_score_favors_taste_aligned_candidate() -> None:
    taste = np.array([1.0, 0.0])
    cand = sp.csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))  # aligned, anti-aligned
    scores = score_candidates(
        cand, taste, [0, 0], [None, None], w_content=1.0, w_graph=0.0, w_pop=0.0
    )
    assert scores[0] > scores[1]


def test_mmr_drops_near_duplicate() -> None:
    # c0 and c1 identical; c2 distinct. MMR should prefer the distinct one second.
    pool = sp.csr_matrix(np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]))
    selected = mmr_select(pool, np.array([0.9, 0.85, 0.5]), k=2, lambda_=0.5)
    assert selected[0] == 0
    assert selected[1] == 2  # the duplicate (idx 1) is skipped for diversity


def test_explanations_pick_nearest_watched_neighbour() -> None:
    watched = sp.csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
    films = [Film(tmdb_id=10, title="X"), Film(tmdb_id=11, title="Y")]
    because, neighbours = _explanations(np.array([1.0, 0.0]), watched, films, k=1)
    assert because[0].title == "X"
    assert because[0].id == "tmdb:10"
    assert neighbours[0].tmdb_id == 10


def test_recommend_sparse_profile_is_non_empty_and_ordered() -> None:
    # Only 2 rated films → triggers the sparse-profile fallback; must still rank sanely.
    watched = [
        Film(tmdb_id=1, title="A", genres=["Action"], rating=5.0),
        Film(tmdb_id=2, title="B", genres=["Action"], rating=4.0),
    ]
    candidates = [
        Film(tmdb_id=3, title="C", genres=["Action"], popularity=10.0),
        Film(tmdb_id=4, title="D", genres=["Comedy"], popularity=5.0),
    ]
    recs = recommend(watched, candidates, [1, 0], user_mean=3.0, top_n=2)
    assert len(recs) == 2  # fallback never returns empty
    assert recs[0].tmdb_id == 3  # Action candidate beats the Comedy one
    assert recs[0].because  # carries an explanation
