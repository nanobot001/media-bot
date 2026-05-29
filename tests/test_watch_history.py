import pytest
from unittest.mock import AsyncMock, patch
from moviebot.tools.query_watch_history_tool import query_watch_history_tool

# Dummy Tautulli user data
MOCK_USERS = [
    {"user_id": 799399, "username": "tonyhung", "friendly_name": "tonyhung"},
    {"user_id": 21887739, "username": "Dorothy363", "friendly_name": "Dorothy363"},
    {"user_id": 466948420, "username": "dorothyfung", "friendly_name": "dorothyfung"},
    {"user_id": 125411560, "username": "Justin", "friendly_name": "Justin"},
]

MOCK_HISTORY = {
    "data": [
        {
            "title": "Wake Up Dead Man",
            "year": 2025,
            "user": "tonyhung",
            "friendly_name": "tonyhung",
            "date": 1779989851,
            "duration": 6052,
            "percent_complete": 69,
            "player": "TV 2020",
            "media_type": "movie"
        }
    ]
}

@pytest.mark.asyncio
async def test_exact_case_insensitive_match():
    with patch("moviebot.adapters.tautulli_client.TautulliClient._query", new_callable=AsyncMock) as mock_query:
        # Mock _query responses: first for get_users, second for get_history
        mock_query.side_effect = [MOCK_USERS, MOCK_HISTORY]
        
        # Test lowercase match for mixed case username "Justin" -> "justin"
        res = await query_watch_history_tool(user="justin")
        assert res["ok"] is True
        assert res["data"]["resolved_user"] == "Justin"
        
        # Verify get_history called with correct user_id
        mock_query.assert_any_call("get_users")
        mock_query.assert_any_call("get_history", {"length": 50, "user_id": 125411560})

@pytest.mark.asyncio
async def test_prefix_match():
    with patch("moviebot.adapters.tautulli_client.TautulliClient._query", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = [MOCK_USERS, MOCK_HISTORY]
        
        # Test prefix match "dorothy3" -> "Dorothy363"
        res = await query_watch_history_tool(user="dorothy3")
        assert res["ok"] is True
        assert res["data"]["resolved_user"] == "Dorothy363"
        
        mock_query.assert_any_call("get_history", {"length": 50, "user_id": 21887739})

@pytest.mark.asyncio
async def test_substring_match():
    with patch("moviebot.adapters.tautulli_client.TautulliClient._query", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = [MOCK_USERS, MOCK_HISTORY]
        
        # Test substring match "fung" -> "dorothyfung"
        res = await query_watch_history_tool(user="fung")
        assert res["ok"] is True
        assert res["data"]["resolved_user"] == "dorothyfung"
        
        mock_query.assert_any_call("get_history", {"length": 50, "user_id": 466948420})

@pytest.mark.asyncio
async def test_fallback_no_match():
    with patch("moviebot.adapters.tautulli_client.TautulliClient._query", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = [MOCK_USERS, MOCK_HISTORY]
        
        # Test fallback when username isn't matched
        res = await query_watch_history_tool(user="unknown_user")
        assert res["ok"] is True
        assert res["data"]["resolved_user"] is None
        
        mock_query.assert_any_call("get_history", {"length": 50, "user": "unknown_user"})

@pytest.mark.asyncio
async def test_empty_users_list():
    with patch("moviebot.adapters.tautulli_client.TautulliClient._query", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = [[], MOCK_HISTORY]
        
        res = await query_watch_history_tool(user="tonyhung")
        assert res["ok"] is True
        assert res["data"]["resolved_user"] is None
        
        mock_query.assert_any_call("get_history", {"length": 50, "user": "tonyhung"})
