"""Feature vectors for films (SPEC §4.3).

Each film becomes a sparse trait vector (genres, director, top cast, keywords, decade,
language, runtime bucket). We fit one shared vocabulary over the **combined watched +
candidate** set so every vector lives in the same space, apply TF-IDF weighting so
ubiquitous traits (common genres/keywords) don't dominate, scale by trait type, and
L2-normalize so cosine similarity is just a dot product.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.preprocessing import normalize

from backend.models import Film

# Relative emphasis per trait type. A shared director/genre says more about taste than a
# shared runtime bucket. (TF-IDF already up-weights rarer traits; this tunes by kind.)
TYPE_WEIGHTS: dict[str, float] = {
    "genre": 1.0,
    "director": 1.0,
    "cast": 0.7,
    "kw": 0.8,
    "decade": 0.5,
    "lang": 0.4,
    "runtime": 0.3,
}


def runtime_bucket(runtime: int | None) -> str:
    if runtime is None:
        return "unknown"
    if runtime < 90:
        return "short"
    if runtime < 120:
        return "mid"
    if runtime < 150:
        return "long"
    return "epic"


def film_traits(film: Film) -> dict[str, float]:
    """The raw (binary) trait dict for one film, keys prefixed by trait type."""
    traits: dict[str, float] = {}
    for g in film.genres:
        traits[f"genre:{g}"] = 1.0
    if film.director:
        traits[f"director:{film.director}"] = 1.0
    for c in film.top_cast:
        traits[f"cast:{c}"] = 1.0
    for k in film.keywords:
        traits[f"kw:{k}"] = 1.0
    if film.release_decade:
        traits[f"decade:{film.release_decade}"] = 1.0
    if film.original_language:
        traits[f"lang:{film.original_language}"] = 1.0
    traits[f"runtime:{runtime_bucket(film.runtime)}"] = 1.0
    return traits


def build_feature_matrix(films: list[Film]) -> tuple[sp.csr_matrix, list[str]]:
    """Return an (n_films × n_features) L2-normalized sparse matrix + feature names.

    Rows align to ``films``. Fit this once over watched+candidates together.
    """
    dv = DictVectorizer(dtype=np.float64, sparse=True)
    raw = dv.fit_transform(film_traits(f) for f in films)
    names = list(dv.get_feature_names_out())

    # Down-weight ubiquitous traits across the corpus.
    weighted = TfidfTransformer().fit_transform(raw)

    # Scale columns by trait type, then L2-normalize rows.
    type_scale = np.array([TYPE_WEIGHTS.get(name.split(":", 1)[0], 1.0) for name in names])
    weighted = weighted @ sp.diags(type_scale)
    weighted = normalize(weighted, norm="l2", axis=1)
    return weighted.tocsr(), names
