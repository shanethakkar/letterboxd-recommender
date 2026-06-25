"""Feature matrix: multi-hot correctness, L2 norm, TF-IDF down-weighting."""

import numpy as np

from backend.features import build_feature_matrix
from backend.models import Film


def _film(tmdb_id: int, **kw) -> Film:
    return Film(tmdb_id=tmdb_id, title=f"F{tmdb_id}", **kw)


def test_rows_are_l2_normalized() -> None:
    films = [
        _film(1, genres=["Drama"], keywords=["a"], runtime=100),
        _film(2, genres=["Action", "Thriller"], director="Nolan", runtime=130),
    ]
    matrix, _ = build_feature_matrix(films)
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    assert np.allclose(norms, 1.0)


def test_multi_hot_sets_expected_columns() -> None:
    films = [_film(1, genres=["Action", "Thriller"], director="Nolan")]
    matrix, names = build_feature_matrix(films)
    row = matrix[0].toarray().ravel()
    for col in ("genre:Action", "genre:Thriller", "director:Nolan"):
        assert row[names.index(col)] > 0
    # A genre the film doesn't have is absent from the vocabulary entirely.
    assert "genre:Comedy" not in names


def test_tfidf_downweights_ubiquitous_trait() -> None:
    # "Drama" appears in every film (ubiquitous → low weight); "rare" appears once.
    films = [
        _film(1, genres=["Drama"], keywords=["rare"]),
        _film(2, genres=["Drama"], keywords=["common"]),
        _film(3, genres=["Drama"], keywords=["common"]),
        _film(4, genres=["Drama"], keywords=["common"]),
    ]
    matrix, names = build_feature_matrix(films)
    row0 = matrix[0].toarray().ravel()
    assert row0[names.index("kw:rare")] > row0[names.index("genre:Drama")]
