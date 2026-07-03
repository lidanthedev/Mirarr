import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.download_manager import manager
from app.providers.base import ProviderInterface
from app.providers import ProviderRegistry


# Define a mock provider
class MockProvider(ProviderInterface):
    @property
    def name(self) -> str:
        return "TestProvider"

    async def get_movie(self, movie):
        return []

    async def get_series_episode(self, series, season, episode):
        return []

    def get_yt_opts(self):
        return {"test": "opts"}


@pytest.fixture
def mock_provider():
    """Register MockProvider for the test and unregister it after."""
    provider = MockProvider()
    ProviderRegistry.register(provider)
    yield provider
    # Cleanup: remove from registry (assuming we can access the dict directly for tests)
    if provider.name in ProviderRegistry._providers:
        del ProviderRegistry._providers[provider.name]

    # Reset download manager state
    from app.services.download_manager import manager

    if hasattr(manager, "download_status"):
        manager.download_status.clear()
    if hasattr(manager, "_worker_tasks"):
        # Cancel any pending tasks to avoid warnings
        for task in manager._worker_tasks:
            task.cancel()
        manager._worker_tasks.clear()


@pytest.fixture
def client(mock_provider, auth_headers):
    """Create a TestClient with the mock provider registered."""
    return TestClient(app, headers=auth_headers)


def test_download_queue_post(client):
    """Test that the download queue endpoint works with POST and stores metadata."""

    # Metadata params
    params = {
        "url": "https://example.com/video.mp4",
        "quality": "1080p",
        "source": "TestProvider",
        "media_type": "movie",
        "tmdb_id": 12345,
        "season": 1,
        "episode": 1,
        "filename": "Test Movie (2023).mp4",
    }

    # Make POST request with JSON body
    response = client.post("/download/queue", json=params)

    assert response.status_code == 200, (
        f"Expected 200 OK, got {response.status_code}: {response.text}"
    )

    # Verify download was added to manager
    downloads = manager.get_all_downloads()
    assert len(downloads) > 0, "Download queue should not be empty"

    # Find our download
    # Since tests run in parallel or sequence, we should filter by ID or URL
    # We use list comprehension to safely get the last matching download
    matching_downloads = [d for d in downloads if d["url"] == params["url"]]
    assert len(matching_downloads) > 0, "Should find the download we just queued"
    latest = matching_downloads[-1]

    # Verify metadata
    metadata = latest.get("metadata")
    assert metadata is not None
    # Note: Query params are parsed as strings by FastAPI unless typed, but here they are passed as kwargs to client.post
    # FastAPI does type coercion based on type hints in route function!
    # So tmdb_id should be int, season int, etc.
    assert metadata["tmdb_id"] == params["tmdb_id"]
    assert metadata["media_type"] == params["media_type"]
    assert metadata["season"] == params["season"]
    assert metadata["episode"] == params["episode"]

    print("Test passed: Download queued via POST with correct metadata.")


def test_download_queue_url_validation(client):
    """Test that the download queue endpoint validates URLs correctly."""

    valid_urls = [
        "https://example.com/video.mp4",
        "http://example.com/video.mp4",
        "https://www.google.com/search?q=test",
        "http://localhost:8080/file.mkv",
        "https://subdomain.example.co.uk/path/to/resource",
    ]

    invalid_url = "not-a-valid-url"

    # Test valid URLs
    for url in valid_urls:
        params = {
            "url": url,
            "quality": "1080p",
            "source": "TestProvider",
            "media_type": "movie",
            "tmdb_id": 12345,
            "season": 1,
            "episode": 1,
            "filename": "Test Movie.mp4",
        }
        response = client.post("/download/queue", json=params)
        assert response.status_code == 200, (
            f"Expected valid URL '{url}' to be accepted, got {response.status_code}"
        )

    # Test invalid URL
    params = {
        "url": invalid_url,
        "quality": "1080p",
        "source": "TestProvider",
        "media_type": "movie",
        "tmdb_id": 12345,
        "season": 1,
        "episode": 1,
        "filename": "Test Movie.mp4",
    }
    response = client.post("/download/queue", json=params)
    assert response.status_code == 422, (
        f"Expected invalid URL '{invalid_url}' to be rejected with 422, got {response.status_code}"
    )

    print(
        "Test passed: URL validation correctly accepted 5 valid URLs and rejected 1 invalid URL."
    )
