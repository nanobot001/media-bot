import pytest
pytest.importorskip("mcp")

from unittest.mock import AsyncMock, patch
from moviebot.cli.mcp_server import mcp


@pytest.mark.asyncio
async def test_mcp_tools_registration():
    """Verify that all 8 media-bot tools are registered with their expected schema names."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "search_library",
        "dedupe_check",
        "search_sources",
        "enqueue_download",
        "get_download_jobs",
        "get_error_logs",
        "query_watch_history",
        "resolve_pending_jobs",
        "check_movie_state",
        "get_system_health",
        "get_tool_manifest",
        "get_recent_events",
        "tail_logs",
        "query_library",
        "recommend_movies",
        "audit_collections"
    }

    assert expected_tools == tool_names, f"Expected tools {expected_tools}, but got {tool_names}"


@pytest.mark.asyncio
async def test_mcp_search_library_invocation():
    """Verify that search_library tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "data": {"movies": []}}
    with patch("moviebot.cli.mcp_server.search_library_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("search_library", {"title": "Inception", "year": 2010})
        
        mock_tool.assert_called_once_with(title="Inception", year=2010)
        assert len(content_list) == 1
        # FastMCP serializes dictionary returns as JSON in the text content
        assert "data" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_dedupe_check_invocation():
    """Verify that dedupe_check tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "match": False}
    with patch("moviebot.cli.mcp_server.dedupe_check_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("dedupe_check", {"title": "Avatar", "year": 2009})
        
        mock_tool.assert_called_once_with(title="Avatar", year=2009, imdb_id=None)
        assert len(content_list) == 1
        assert "match" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_search_sources_invocation():
    """Verify that search_sources tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "results": []}
    with patch("moviebot.cli.mcp_server.search_sources_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("search_sources", {"query": "Interstellar", "imdb_id": "tt0816692"})
        
        mock_tool.assert_called_once_with(query="Interstellar", imdb_id="tt0816692")
        assert len(content_list) == 1
        assert "results" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_enqueue_download_invocation():
    """Verify that enqueue_download tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "job_id": "123"}
    with patch("moviebot.cli.mcp_server.enqueue_download_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("enqueue_download", {
            "reference_id": "ref123",
            "dry_run": True,
            "selected_file_id": "file99"
        })
        
        mock_tool.assert_called_once_with(reference_id="ref123", dry_run=True, selected_file_id="file99")
        assert len(content_list) == 1
        assert "job_id" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_get_download_jobs_invocation():
    """Verify that get_download_jobs tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "jobs": []}
    with patch("moviebot.cli.mcp_server.get_download_jobs_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("get_download_jobs", {"active_only": False, "limit": 10})
        
        mock_tool.assert_called_once_with(active_only=False, limit=10)
        assert len(content_list) == 1
        assert "jobs" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_get_error_logs_invocation():
    """Verify that get_error_logs tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "errors": []}
    with patch("moviebot.cli.mcp_server.get_error_logs_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("get_error_logs", {"limit": 5})
        
        mock_tool.assert_called_once_with(limit=5)
        assert len(content_list) == 1
        assert "errors" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_query_watch_history_invocation():
    """Verify that query_watch_history tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "history": []}
    with patch("moviebot.cli.mcp_server.query_watch_history_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("query_watch_history", {"user": "anthony", "title": "The Matrix", "limit": 20})
        
        mock_tool.assert_called_once_with(user="anthony", title="The Matrix", limit=20)
        assert len(content_list) == 1
        assert "history" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_resolve_pending_jobs_invocation():
    """Verify that resolve_pending_jobs tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "resolved": []}
    with patch("moviebot.cli.mcp_server.resolve_pending_jobs_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("resolve_pending_jobs", {"dry_run": True})
        
        mock_tool.assert_called_once_with(dry_run=True)
        assert len(content_list) == 1
        assert "resolved" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_query_library_invocation():
    """Verify that query_library tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "movies": []}
    with patch("moviebot.cli.mcp_server.query_library_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("query_library", {
            "query": "predator",
            "semantic_query": "sci-fi action",
            "genre": "Action",
            "director": "McTiernan",
            "resolution": "1080p",
            "watch_status": "unwatched",
            "max_runtime": 120,
            "min_rating": 7.5,
            "limit": 5
        })
        
        mock_tool.assert_called_once_with(
            query="predator",
            semantic_query="sci-fi action",
            genre="Action",
            director="McTiernan",
            resolution="1080p",
            watch_status="unwatched",
            max_runtime=120,
            min_rating=7.5,
            limit=5
        )
        assert len(content_list) == 1
        assert "movies" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_recommend_movies_invocation():
    """Verify that recommend_movies tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "recommendations": []}
    with patch("moviebot.cli.mcp_server.recommend_movies_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("recommend_movies", {
            "user": "anthony",
            "limit": 5
        })
        
        mock_tool.assert_called_once_with(user="anthony", limit=5)
        assert len(content_list) == 1
        assert "recommendations" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_audit_collections_invocation():
    """Verify that audit_collections tool delegates correctly and handles arguments."""
    mock_res = {"ok": True, "reports": []}
    with patch("moviebot.cli.mcp_server.audit_collections_tool", new_callable=AsyncMock) as mock_tool:
        mock_tool.return_value = mock_res
        
        content_list, extra = await mcp.call_tool("audit_collections", {})
        
        mock_tool.assert_called_once_with()
        assert len(content_list) == 1
        assert "reports" in content_list[0].text

