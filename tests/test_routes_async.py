from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.tmdb import MediaType, TMDBSearchResult


@pytest.fixture
def client(auth_headers):
    return TestClient(app, headers=auth_headers)


@pytest.fixture
def unauthenticated_client():
    return TestClient(app)


mock_results = [
    TMDBSearchResult(
        id=1,
        title="Test Movie",
        overview="Test Overview",
        poster_url=None,
        backdrop_url=None,
        media_type=MediaType.MOVIE,
        release_year="2023",
        vote_average=8.0,
    )
]


def test_auth_required_for_everything(unauthenticated_client):
    for path in ("/", "/api/health", "/static/style.css"):
        response = unauthenticated_client.get(path)
        assert response.status_code == 401


@patch(
    "app.api.routes_api.search_tmdb", side_effect=AsyncMock(return_value=mock_results)
)
def test_api_search_async_fix(mock_search, client):
    """
    Test that api_search awaits the async search_tmdb function.
    If it fails to await, it returns a coroutine, which causes FastAPI to error
    (likely 500 or validation error) because it doesn't match List[TMDBSearchResult].
    """
    response = client.get("/api/search?q=test&media_type=movie")

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["title"] == "Test Movie"


@patch(
    "app.api.routes_ui.search_tmdb", side_effect=AsyncMock(return_value=mock_results)
)
def test_ui_search_async_success(mock_search, client):
    """
    Test that the UI search route works correctly (it was already correct).
    """
    response = client.post("/search", data={"query": "test", "media_type": "movie"})

    assert response.status_code == 200
    assert "Test Movie" in response.text


def test_health_check_is_authenticated(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "mirrarr"}
