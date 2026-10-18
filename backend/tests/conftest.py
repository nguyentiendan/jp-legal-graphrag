import pytest


@pytest.fixture(scope="session")
def sparse_encoder():
    from jplegal.retrieval.sparse import get_encoder

    return get_encoder()
