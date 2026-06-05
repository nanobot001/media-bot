import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from moviebot.core.conversational_rag import (
    RAGQueryCache,
    _build_local_fallback_answer,
    _find_inventory_matches,
    _inventory_title_queries,
    _is_rate_limit_error,
    get_global_rag_cache,
    minimize_movie_metadata,
    query_library_conversational,
)
from moviebot.core.gemini_client import generate_gemini_content


def test_minimize_movie_metadata_full():
    movie = {
        "id": "plex_1",
        "title": "The Matrix",
        "year": 1999,
        "genres": ["Action", "Sci-Fi"],
        "tagline": "Welcome to the Real World",
        "synopsis": "A computer hacker learns from mysterious rebels about the true nature of his reality. He decides to fight them. This is a third sentence that should be removed.",
        "tone_tags": '["Intense", "Dark", "Philosophical", "Action-Packed"]',
        "theme_tags": "Cyberpunk, Simulation, Rebellion, Artificial Intelligence",
        "award_tags": ["Oscar Win: Best Visual Effects", "Oscar Win: Best Editing", "Oscar Win: Best Sound", "Oscar Win: Best Sound Effects Editing"],
        "studios": "Warner Bros., Village Roadshow Pictures, Groucho II Film Partnership",
        "directors": ["Lana Wachowski", "Lilly Wachowski"],
    }
    
    minimized = minimize_movie_metadata(movie)
    
    assert minimized["id"] == "plex_1"
    assert minimized["title"] == "The Matrix"
    assert minimized["year"] == 1999
    assert minimized["genres"] == "Action, Sci-Fi"
    assert minimized["tagline"] == "Welcome to the Real World"
    # First 2 sentences
    assert "A computer hacker learns from mysterious rebels about the true nature of his reality. He decides to fight them." in minimized["synopsis"]
    assert "third sentence" not in minimized["synopsis"]
    assert len(minimized["synopsis"]) <= 150
    
    assert minimized["tones"] == ["Intense", "Dark", "Philosophical"]
    assert minimized["themes"] == ["Cyberpunk", "Simulation", "Rebellion"]
    assert minimized["awards"] == ["Oscar Win: Best Visual Effects", "Oscar Win: Best Editing", "Oscar Win: Best Sound"]
    assert minimized["studios"] == ["Warner Bros.", "Village Roadshow Pictures", "Groucho II Film Partnership"]
    assert minimized["directors"] == ["Lana Wachowski", "Lilly Wachowski"]


def test_minimize_movie_metadata_empty_or_missing():
    movie = {
        "id": "plex_2",
        "title": "Minimal Movie",
    }
    
    minimized = minimize_movie_metadata(movie)
    
    assert minimized["id"] == "plex_2"
    assert minimized["title"] == "Minimal Movie"
    assert "year" in minimized and minimized["year"] is None
    assert "genres" not in minimized
    assert "tagline" not in minimized
    assert "synopsis" not in minimized
    assert "tones" not in minimized
    assert "themes" not in minimized
    assert "awards" not in minimized


def test_minimize_movie_metadata_long_sentence():
    movie = {
        "id": "plex_3",
        "title": "Very Long Sentence Movie",
        "synopsis": "This is a single sentence which is extremely long and will go on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on and on to exceed 150 characters easily.",
    }
    
    minimized = minimize_movie_metadata(movie)
    assert len(minimized["synopsis"]) <= 150
    assert minimized["synopsis"].endswith("...")


@pytest.mark.asyncio
async def test_rag_query_cache():
    cache = RAGQueryCache(default_ttl_seconds=300.0)
    
    # Test set and get
    await cache.set("  WHAT is the Matrix?  ", "It is a simulated reality.", ttl=0.1)
    
    # Case insensitivity and whitespace normalization
    val = await cache.get("what is the matrix?")
    assert val == "It is a simulated reality."
    
    # Expiration
    await asyncio.sleep(0.15)
    val_expired = await cache.get("what is the matrix?")
    assert val_expired is None
    
    # Set again
    await cache.set("test_key", "test_value", ttl=100.0)
    val_cached = await cache.get("test_key")
    assert val_cached == "test_value"
    
    # Clear
    await cache.clear()
    assert await cache.get("test_key") is None


@pytest.mark.asyncio
async def test_rag_query_cache_prune():
    cache = RAGQueryCache(default_ttl_seconds=300.0)
    await cache.set("key1", "val1", ttl=0.01)
    await cache.set("key2", "val2", ttl=10.0)
    
    await asyncio.sleep(0.02)
    await cache.prune()
    
    # key1 should be deleted by prune, key2 remains
    assert cache._cache.get("key1") is None
    assert cache._cache.get("key2") is not None


def test_global_rag_cache():
    c1 = get_global_rag_cache()
    c2 = get_global_rag_cache()
    assert c1 is c2
    assert isinstance(c1, RAGQueryCache)


def test_rate_limit_detection_and_local_fallback_answer():
    assert _is_rate_limit_error(RuntimeError("429 Too Many Requests")) is True
    assert _is_rate_limit_error(RuntimeError("RESOURCE_EXHAUSTED")) is True
    assert _is_rate_limit_error(RuntimeError("ordinary failure")) is False

    answer = _build_local_fallback_answer(
        [
            {
                "title": "The Matrix",
                "year": 1999,
                "genres": '["Action", "Sci-Fi"]',
                "directors": '["Lana Wachowski", "Lilly Wachowski"]',
            }
        ],
        "Try again later.",
    )

    assert "temporarily rate-limited" in answer
    assert "**The Matrix** (1999)" in answer
    assert "429" not in answer


def test_inventory_title_queries_extracts_owned_title():
    assert _inventory_title_queries("Do I already have Terminator 2 Judgment Day?")[-1] == "Terminator 2 Judgment Day"
    assert _inventory_title_queries("Is Terminator 2 Judgment Day in my library?")[-1] == "Terminator 2 Judgment Day"


@pytest.mark.asyncio
@patch("moviebot.core.conversational_rag.LibraryItemRepository.search_by_normalized_title")
@patch("moviebot.core.conversational_rag.get_embedding_result")
@patch("moviebot.core.conversational_rag.generate_gemini_content")
async def test_inventory_question_returns_exact_match_before_rag(mock_generate, mock_embed, mock_search):
    mock_search.return_value = [
        {
            "id": "plex_t2",
            "title": "Terminator 2: Judgment Day",
            "year": 1991,
            "resolution": "1080",
            "size_bytes": 2416799735,
        }
    ]

    res = await query_library_conversational("Do I already have Terminator 2 Judgment Day?")

    assert "already in your local library" in res["answer"]
    assert "Terminator 2: Judgment Day" in res["answer"]
    assert res["cited_movie_ids"] == ["plex_t2"]
    assert res["external_recommendations"] == []
    mock_embed.assert_not_called()
    mock_generate.assert_not_called()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
@patch("moviebot.config.settings.gemini_api_key", "fake-key")
async def test_generate_gemini_content_success(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Hello, world!"}]
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    res = await generate_gemini_content("Test prompt")
    assert res == "Hello, world!"
    mock_post.assert_called_once()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
@patch("moviebot.config.settings.gemini_api_key", "fake-key")
async def test_generate_gemini_content_retry_success(mock_post):
    # First response fails with 500, second succeeds
    fail_response = MagicMock()
    fail_response.status_code = 500
    fail_response.raise_for_status.side_effect = httpx.HTTPStatusError("500 Internal Server Error", request=MagicMock(), response=fail_response)

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Success after retry!"}]
                }
            }
        ]
    }

    mock_post.side_effect = [fail_response, success_response]

    # Patch asyncio.sleep to avoid waiting in tests
    with patch("asyncio.sleep", return_value=None) as mock_sleep:
        res = await generate_gemini_content("Test retry prompt")
        assert res == "Success after retry!"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
@patch("moviebot.config.settings.gemini_api_key", "fake-key")
@patch("moviebot.db.repositories.ErrorLogRepository.insert")
async def test_generate_gemini_content_failure_logging(mock_db_insert, mock_post):
    # Always fail
    fail_response = MagicMock()
    fail_response.status_code = 500
    fail_response.raise_for_status.side_effect = httpx.HTTPStatusError("500 Internal Server Error", request=MagicMock(), response=fail_response)
    mock_post.return_value = fail_response

    with patch("asyncio.sleep", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            await generate_gemini_content("Test failing prompt")
        
        assert "Gemini API content generation failed after 4 attempts" in str(exc_info.value)
        assert mock_post.call_count == 4
        # Assert database insert was called to log the failure
        mock_db_insert.assert_called_once()
        args, kwargs = mock_db_insert.call_args
        assert kwargs["command_name"] == "gemini_client"
        assert "Gemini API content generation failed after 4 attempts" in kwargs["error_message"]
        assert kwargs["stack_trace"] is not None


@pytest.mark.asyncio
@patch("moviebot.core.conversational_rag.get_embedding_result")
@patch("moviebot.core.conversational_rag.get_db_connection")
@patch("moviebot.core.conversational_rag.generate_gemini_content")
async def test_query_library_conversational_success(mock_generate, mock_db, mock_embed):
    # Setup embedding mock
    mock_emb_res = MagicMock()
    mock_emb_res.vector = [0.1] * 768
    mock_emb_res.model = "mock-hash-v1"
    mock_emb_res.dim = 768
    mock_embed.return_value = mock_emb_res

    # Setup DB mock
    import sqlite3
    import struct
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE library_items (
            id TEXT PRIMARY KEY,
            title TEXT,
            year INTEGER,
            genres TEXT,
            tagline TEXT,
            synopsis TEXT,
            tone_tags TEXT,
            theme_tags TEXT,
            award_tags TEXT,
            studios TEXT,
            directors TEXT,
            synopsis_vector BLOB,
            synopsis_vector_model TEXT,
            synopsis_vector_dim INTEGER
        )
    """)
    mock_vector = [0.1] * 768
    vec_bytes = struct.pack("f" * 768, *mock_vector)
    conn.execute("""
        INSERT INTO library_items (
            id, title, year, genres, tagline, synopsis,
            tone_tags, theme_tags, award_tags, studios, directors,
            synopsis_vector, synopsis_vector_model, synopsis_vector_dim
        ) VALUES (
            'plex_1', 'The Matrix', 1999, '["Action"]', 'Welcome', 'Neo discovers reality',
            '["Dark"]', '["Cyberpunk"]', '[]', 'WB', '["Wachowskis"]',
            ?, 'mock-hash-v1', 768
        )
    """, (vec_bytes,))
    conn.commit()

    # Wrap the connection in a mock context manager
    mock_context = MagicMock()
    mock_context.__enter__.return_value = conn
    mock_context.__exit__.return_value = False
    mock_db.return_value = mock_context

    # Setup Gemini content generation mock
    mock_generate.return_value = "I recommend **The Matrix** (1999) because it's action-packed."

    # Clear global cache first
    cache = get_global_rag_cache()
    await cache.clear()

    res = await query_library_conversational("recommend action movie")
    
    assert "answer" in res
    assert "The Matrix" in res["answer"]
    assert res["cited_movie_ids"] == ["plex_1"]
    
    # Test that caching works
    # If we call again, mock_generate should not be called again
    mock_generate.reset_mock()
    res_cached = await query_library_conversational("recommend action movie")
    assert res_cached == res
    mock_generate.assert_not_called()


@pytest.mark.asyncio
@patch("moviebot.core.conversational_rag.get_embedding_result")
@patch("moviebot.core.conversational_rag.get_db_connection")
@patch("moviebot.core.conversational_rag.generate_gemini_content")
async def test_query_library_conversational_rate_limit_returns_local_fallback(mock_generate, mock_db, mock_embed):
    mock_emb_res = MagicMock()
    mock_emb_res.vector = [0.1] * 768
    mock_emb_res.model = "mock-hash-v1"
    mock_emb_res.dim = 768
    mock_embed.return_value = mock_emb_res

    import sqlite3
    import struct
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE library_items (
            id TEXT PRIMARY KEY,
            title TEXT,
            year INTEGER,
            genres TEXT,
            tagline TEXT,
            synopsis TEXT,
            tone_tags TEXT,
            theme_tags TEXT,
            award_tags TEXT,
            studios TEXT,
            directors TEXT,
            synopsis_vector BLOB,
            synopsis_vector_model TEXT,
            synopsis_vector_dim INTEGER
        )
    """)
    vec_bytes = struct.pack("f" * 768, *([0.1] * 768))
    conn.execute("""
        INSERT INTO library_items (
            id, title, year, genres, tagline, synopsis,
            tone_tags, theme_tags, award_tags, studios, directors,
            synopsis_vector, synopsis_vector_model, synopsis_vector_dim
        ) VALUES (
            'plex_1', 'The Matrix', 1999, '["Action", "Sci-Fi"]', 'Welcome', 'Neo discovers reality',
            '["Dark"]', '["Cyberpunk"]', '[]', 'WB', '["Wachowskis"]',
            ?, 'mock-hash-v1', 768
        )
    """, (vec_bytes,))
    conn.commit()

    mock_context = MagicMock()
    mock_context.__enter__.return_value = conn
    mock_context.__exit__.return_value = False
    mock_db.return_value = mock_context
    mock_generate.side_effect = RuntimeError("429 Too Many Requests")

    cache = get_global_rag_cache()
    await cache.clear()

    res = await query_library_conversational("recommend action movie")

    assert "ok" not in res
    assert res["rate_limited"] is True
    assert "temporarily rate-limited" in res["answer"]
    assert "The Matrix" in res["answer"]
    assert res["cited_movie_ids"] == ["plex_1"]
    assert res["external_recommendations"] == []


@pytest.mark.asyncio
async def test_ask_library_tool_args_validation():
    from moviebot.tools.ask_library_tool import ask_library_tool
    res = await ask_library_tool(question="")
    assert res["ok"] is False
    assert res["error"]["code"] == "MISSING_QUESTION"


@pytest.mark.asyncio
@patch("moviebot.tools.ask_library_tool.query_library_conversational")
async def test_ask_library_tool_success_and_error(mock_query):
    from moviebot.tools.ask_library_tool import ask_library_tool
    
    # Success case
    mock_query.return_value = {
        "answer": "Here is the matrix.",
        "cited_movie_ids": ["plex_1"]
    }
    res = await ask_library_tool(question="Matrix?")
    assert res["ok"] is True
    assert res["data"]["answer"] == "Here is the matrix."
    assert res["data"]["cited_movie_ids"] == ["plex_1"]

    # Error case
    mock_query.return_value = {
        "ok": False,
        "error": {"message": "Simulated error"}
    }
    res = await ask_library_tool(question="Fail me")
    assert res["ok"] is False
    assert res["error"]["code"] == "RAG_QUERY_FAILED"


@pytest.mark.asyncio
@patch("moviebot.core.conversational_rag.get_embedding_result")
@patch("moviebot.core.conversational_rag.get_db_connection")
@patch("moviebot.core.conversational_rag.generate_gemini_content")
async def test_query_library_conversational_with_history(mock_generate, mock_db, mock_embed):
    # Setup embedding mock
    mock_emb_res = MagicMock()
    mock_emb_res.vector = [0.1] * 768
    mock_emb_res.model = "mock-hash-v1"
    mock_emb_res.dim = 768
    mock_embed.return_value = mock_emb_res

    # Setup DB mock
    import sqlite3
    import struct
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE library_items (
            id TEXT PRIMARY KEY,
            title TEXT,
            year INTEGER,
            genres TEXT,
            tagline TEXT,
            synopsis TEXT,
            tone_tags TEXT,
            theme_tags TEXT,
            award_tags TEXT,
            studios TEXT,
            directors TEXT,
            synopsis_vector BLOB,
            synopsis_vector_model TEXT,
            synopsis_vector_dim INTEGER
        )
    """)
    mock_vector = [0.1] * 768
    vec_bytes = struct.pack("f" * 768, *mock_vector)
    conn.execute("""
        INSERT INTO library_items (
            id, title, year, genres, tagline, synopsis,
            tone_tags, theme_tags, award_tags, studios, directors,
            synopsis_vector, synopsis_vector_model, synopsis_vector_dim
        ) VALUES (
            'plex_1', 'Interstellar', 2014, '["Sci-Fi"]', 'Mankind was born', 'A team of explorers travel through a wormhole',
            '["Emotional"]', '["Space"]', '[]', 'Paramount', '["Christopher Nolan"]',
            ?, 'mock-hash-v1', 768
        )
    """, (vec_bytes,))
    conn.commit()

    mock_context = MagicMock()
    mock_context.__enter__.return_value = conn
    mock_context.__exit__.return_value = False
    mock_db.return_value = mock_context

    # First call: query reformulation
    # Second call: answer generation
    mock_generate.side_effect = [
        "What is the runtime of Interstellar?",
        "The movie **Interstellar** (2014) is 169 minutes long."
    ]

    chat_history = [
        {"role": "user", "text": "Show me Nolan sci-fi movies"},
        {"role": "model", "text": "I recommend **Interstellar** (2014)."}
    ]

    res = await query_library_conversational("What is its runtime?", chat_history=chat_history)

    assert "answer" in res
    assert "Interstellar" in res["answer"]
    assert res["cited_movie_ids"] == ["plex_1"]
    
    # Assert query reformulation was called
    assert mock_generate.call_count == 2
    
    # Check that query reformulation prompt was passed
    args_first_call = mock_generate.call_args_list[0]
    assert "Standalone Question:" in args_first_call[1]["prompt"]
    assert "What is its runtime?" in args_first_call[1]["prompt"]
    
    # Check that final prompt was passed with history
    args_second_call = mock_generate.call_args_list[1]
    assert "Show me Nolan sci-fi movies" in args_second_call[1]["prompt"]
    assert "I recommend **Interstellar** (2014)." in args_second_call[1]["prompt"]
    assert "What is its runtime?" in args_second_call[1]["prompt"]
