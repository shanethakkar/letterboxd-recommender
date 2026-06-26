"""Projection, clustering, and similarity edges (no network)."""

import numpy as np

from backend.features import build_feature_matrix
from backend.models import Film
from backend.projection import (
    cluster_2d,
    cluster_labels,
    project_2d,
    similarity_edges,
)


def _films() -> list[Film]:
    # Two clear groups: Action/Nolan vs Comedy/Wright.
    return [
        Film(
            tmdb_id=i,
            title=str(i),
            genres=["Action"] if i < 10 else ["Comedy"],
            director="Nolan" if i < 10 else "Wright",
        )
        for i in range(20)
    ]


def test_project_2d_returns_2d_coords() -> None:
    matrix, _ = build_feature_matrix(_films())
    coords = project_2d(matrix)
    assert coords.shape == (20, 2)


def test_cluster_2d_returns_one_label_per_node() -> None:
    coords = np.random.RandomState(0).rand(40, 2)
    labels = cluster_2d(coords)
    assert labels.shape == (40,)


def test_cluster_labels_use_dominant_genre() -> None:
    films = _films()
    labels = np.array([0] * 10 + [1] * 10)
    out = cluster_labels(films, labels)
    assert out[0] == "action"
    assert out[1] == "comedy"


def test_similarity_edges_are_undirected_and_tagged() -> None:
    films = _films()
    matrix, _ = build_feature_matrix(films)
    edges = similarity_edges(matrix, films, k=3, threshold=0.0)

    pairs = {(e.source, e.target) for e in edges}
    for e in edges:
        assert (e.target, e.source) not in pairs  # deduped undirected
        assert e.shared in {"director", "genre", "keyword", "cast"}
        assert 0.0 <= e.weight <= 1.0
    # Two Action/Nolan films should connect via their shared director.
    assert any(e.shared == "director" for e in edges)
