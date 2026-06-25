"""Recommender math: taste direction, prior, vote floor, scoring, MMR, why, fallback."""

import numpy as np
import scipy.sparse as sp

from backend.models import Film
from backend.recommender import (
    _apply_vote_floor,
    _explanations,
    content_scores,
    mainstream_prior,
    mmr_select,
    recommend,
    score_candidates,
    taste_centroids,
    taste_vector,
)


def test_taste_vector_points_toward_liked_traits() -> None:
    # Two orthogonal traits; film 0 rated above mean, film 1 below.
    matrix = sp.csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
    taste = taste_vector(matrix, [5.0, 1.0], [False, False], user_mean=3.0, liked_bump=0.0)
    assert taste[0] > 0  # toward the high-rated film's trait
    assert taste[1] < 0  # away from the low-rated film's trait


def test_score_favors_higher_content() -> None:
    content_raw = np.array([1.0, 0.0])  # candidate 0 matches taste, candidate 1 doesn't
    scores = score_candidates(
        content_raw, [0, 0], np.zeros(2), w_content=1.0, w_graph=0.0, w_prior=0.0
    )
    assert scores[0] > scores[1]


def test_taste_centroids_find_two_facets() -> None:
    matrix = sp.csr_matrix(
        np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    )
    pos_c, neg_c = taste_centroids(
        matrix, [5.0, 5.0, 5.0, 5.0], [False] * 4, user_mean=3.0, n_clusters=2
    )
    assert pos_c.shape[0] == 2  # two distinct taste facets
    assert neg_c is None  # nothing rated below the mean


def test_multicentroid_scores_minority_facet_higher_than_single() -> None:
    # User loves facet A (3 films) + facet B (1 film). A pure-B candidate is "minority taste":
    # a single averaged vector buries it; max-over-centroids surfaces it.
    watched = sp.csr_matrix(np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]))
    ratings, liked = [5.0, 5.0, 5.0, 5.0], [False] * 4
    cand = sp.csr_matrix(np.array([[0.0, 1.0]]))  # pure facet B

    single = taste_vector(watched, ratings, liked, user_mean=3.0, liked_bump=0.0)
    single_score = float((cand @ single)[0])

    pos_c, neg_c = taste_centroids(watched, ratings, liked, user_mean=3.0, n_clusters=2)
    multi_score = float(content_scores(cand, pos_c, neg_c)[0])

    assert multi_score > single_score


def test_mainstream_prior_favors_quality_popular_recent() -> None:
    films = [
        Film(tmdb_id=1, title="blockbuster", vote_average=8.0, vote_count=10_000, year=2021),
        Film(tmdb_id=2, title="obscure", vote_average=6.0, vote_count=40, year=1968),
    ]
    prior = mainstream_prior(films)
    assert prior[0] > prior[1]


def test_quality_term_honours_imdb_and_metacritic() -> None:
    # Identical TMDB stats; the film with higher IMDb + Metacritic must score a higher prior.
    high = Film(
        tmdb_id=1,
        title="H",
        vote_average=7.0,
        vote_count=5000,
        year=2015,
        imdb_rating=8.6,
        metascore=90,
    )
    low = Film(
        tmdb_id=2,
        title="L",
        vote_average=7.0,
        vote_count=5000,
        year=2015,
        imdb_rating=5.0,
        metascore=40,
    )
    prior = mainstream_prior([high, low])
    assert prior[0] > prior[1]


def test_vote_floor_filters_obscure_candidates() -> None:
    films = [
        Film(tmdb_id=1, title="A", vote_count=1000),
        Film(tmdb_id=2, title="B", vote_count=2000),
        Film(tmdb_id=3, title="C", vote_count=10),
        Film(tmdb_id=4, title="D", vote_count=5),
    ]
    kept, prov = _apply_vote_floor(films, [9, 8, 7, 6], min_vote_count=500, top_n=1)
    assert {f.tmdb_id for f in kept} == {1, 2}  # the two below-floor films are dropped
    assert set(prov) == {9, 8}  # provenance stays aligned to survivors


def test_mmr_drops_near_duplicate() -> None:
    pool = sp.csr_matrix(np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]))
    selected = mmr_select(pool, np.array([0.9, 0.85, 0.5]), k=2, lambda_=0.5)
    assert selected[0] == 0
    assert selected[1] == 2  # the duplicate (idx 1) is skipped for diversity


def test_explanations_only_cite_eligible_highly_rated_films() -> None:
    # Film 0 is the MOST similar, but is not eligible (rated below average); only film 1 is.
    watched = sp.csr_matrix(np.array([[1.0, 0.0], [0.9, 0.1]]))
    films = [Film(tmdb_id=10, title="LowRated"), Film(tmdb_id=11, title="HighRated")]
    because, neighbours = _explanations(np.array([1.0, 0.0]), watched, films, eligible=[1], k=2)
    assert len(because) == 1
    assert because[0].title == "HighRated"  # the more-similar low-rated film is excluded


def test_recommend_sparse_profile_is_non_empty_and_ordered() -> None:
    # Only 2 rated films → triggers the sparse-profile fallback; must still rank sanely.
    watched = [
        Film(tmdb_id=1, title="A", genres=["Action"], rating=5.0),
        Film(tmdb_id=2, title="B", genres=["Action"], rating=4.0),
    ]
    candidates = [
        Film(tmdb_id=3, title="C", genres=["Action"], vote_average=7.5, vote_count=8000, year=2018),
        Film(tmdb_id=4, title="D", genres=["Comedy"], vote_average=7.5, vote_count=8000, year=2018),
    ]
    recs = recommend(watched, candidates, [1, 0], user_mean=3.0, top_n=2)
    assert len(recs) == 2  # fallback never returns empty
    assert recs[0].tmdb_id == 3  # Action candidate beats the Comedy one
    assert recs[0].because  # carries an explanation
