import pytest
import sqlite3
from moviebot.db.connection import get_db_connection, init_db
from moviebot.db.repositories import UserProfileRepository, UserMemoryRepository, UserInteractionMemoryRepository
from moviebot.config import settings

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch, tmp_path):
    # Set up temporary test database path
    db_file = tmp_path / "test_moviebot.db"
    monkeypatch.setattr(settings, "database_path", str(db_file))
    init_db()
    yield

def test_user_profile_crud():
    discord_id = "discord_123"
    plex_user = "plex_tony"
    
    # 1. Get non-existent profile
    profile = UserProfileRepository.get(discord_id)
    assert profile is None
    
    # 2. Insert profile
    UserProfileRepository.upsert(
        discord_user_id=discord_id,
        plex_username=plex_user,
        custom_taste_notes="Loves sci-fi",
        metadata_json='{"public_visibility": true}'
    )
    
    # 3. Retrieve profile
    profile = UserProfileRepository.get(discord_id)
    assert profile is not None
    assert profile["discord_user_id"] == discord_id
    assert profile["plex_username"] == plex_user
    assert profile["custom_taste_notes"] == "Loves sci-fi"
    assert "public_visibility" in profile["metadata_json"]
    
    # Get by Plex username
    profile_by_plex = UserProfileRepository.get_by_plex_username(plex_user)
    assert profile_by_plex is not None
    assert profile_by_plex["discord_user_id"] == discord_id
    
    # 4. Update profile (partial update)
    UserProfileRepository.upsert(
        discord_user_id=discord_id,
        custom_taste_notes="Loves sci-fi and action"
    )
    profile = UserProfileRepository.get(discord_id)
    assert profile["custom_taste_notes"] == "Loves sci-fi and action"
    assert profile["plex_username"] == plex_user # Preserved COALESCE
    
    # 5. Delete profile
    UserProfileRepository.delete(discord_id)
    assert UserProfileRepository.get(discord_id) is None

def test_user_memory_crud():
    discord_id = "discord_456"
    UserProfileRepository.upsert(discord_user_id=discord_id, plex_username="plex_justin")
    
    # 1. Add memories
    mem_id1 = UserMemoryRepository.add(discord_id, "like", "Loves Canadian indie movies", "chat_extraction")
    mem_id2 = UserMemoryRepository.add(discord_id, "dislike", "Dislikes jump scares", "chat_extraction", "discord_123")
    
    assert mem_id1 > 0
    assert mem_id2 > 0
    
    # 2. Get memories
    memories = UserMemoryRepository.get_all_for_user(discord_id)
    assert len(memories) == 2
    assert memories[0]["fact"] == "Dislikes jump scares"
    assert memories[0]["target_user_id"] == "discord_123"
    
    # Get social memories
    social = UserMemoryRepository.get_all_social("discord_123")
    assert len(social) == 1
    assert social[0]["target_user_id"] == "discord_123"
    
    # 3. Update memory
    UserMemoryRepository.update(mem_id1, "Loves Canadian indie movies and documentaries", "like")
    memories = UserMemoryRepository.get_all_for_user(discord_id)
    updated_mem = [m for m in memories if m["id"] == mem_id1][0]
    assert updated_mem["fact"] == "Loves Canadian indie movies and documentaries"
    
    # 4. Pruning test
    for i in range(10):
        UserMemoryRepository.add(discord_id, "like", f"Fact {i}", "chat_extraction")
    
    # Prune to max 5
    UserMemoryRepository.prune_oldest(discord_id, max_limit=5)
    memories = UserMemoryRepository.get_all_for_user(discord_id)
    assert len(memories) == 5

def test_user_interaction_memory_crud():
    discord_id = "discord_789"
    UserProfileRepository.upsert(discord_user_id=discord_id, plex_username="plex_someone")
    
    # 1. Log interactions
    UserInteractionMemoryRepository.log(discord_id, "Hello", "Hi there!", "chan_1")
    UserInteractionMemoryRepository.log(discord_id, "Recommend a movie", "Check out Inception.", "chan_1")
    
    # 2. Get recent (reversing order)
    recent = UserInteractionMemoryRepository.get_recent(discord_id, limit=10)
    assert len(recent) == 2
    assert recent[0]["query_text"] == "Hello"
    assert recent[1]["query_text"] == "Recommend a movie"
    
    # 3. Pruning
    for i in range(5):
        UserInteractionMemoryRepository.log(discord_id, f"Query {i}", f"Response {i}", "chan_1")
    
    UserInteractionMemoryRepository.prune_oldest(discord_id, max_limit=3)
    recent = UserInteractionMemoryRepository.get_recent(discord_id, limit=10)
    assert len(recent) == 3
    assert recent[0]["query_text"] == "Query 2"
    assert recent[2]["query_text"] == "Query 4"
    
    # 4. Delete all
    UserInteractionMemoryRepository.delete_all_for_user(discord_id)
    assert len(UserInteractionMemoryRepository.get_recent(discord_id, limit=10)) == 0


@pytest.mark.asyncio
async def test_user_memory_manager_extraction_and_retrieval(monkeypatch):
    import json
    from moviebot.core.user_memory_manager import UserMemoryManager

    # Mock generate_gemini_content
    async def mock_generate_content(*args, **kwargs):
        return json.dumps({
            "memories": [
                {
                    "target_user_name": "self",
                    "category": "like",
                    "fact": "Loves psychological thrillers"
                },
                {
                    "target_user_name": "Justin",
                    "category": "dislike",
                    "fact": "Dislikes slow-paced romance movies"
                }
            ]
        })

    monkeypatch.setattr("moviebot.core.user_memory_manager.generate_gemini_content", mock_generate_content)

    discord_tony = "discord_tony_123"
    discord_justin = "discord_justin_456"

    known_users = {
        "Tony": discord_tony,
        "Justin": discord_justin
    }

    # Extract memories from Tony's message
    saved = await UserMemoryManager.extract_and_save_memories(
        discord_user_id=discord_tony,
        query_text="I love psychological thrillers but Justin hates slow romance",
        known_users=known_users
    )

    assert len(saved) == 2
    
    assert saved[0]["discord_user_id"] == discord_tony
    assert saved[0]["category"] == "like"
    assert saved[0]["fact"] == "Loves psychological thrillers"
    assert saved[0]["target_user_id"] is None

    assert saved[1]["discord_user_id"] == discord_justin
    assert saved[1]["category"] == "dislike"
    assert saved[1]["fact"] == "According to context: Dislikes slow-paced romance movies"
    assert saved[1]["target_user_id"] == discord_tony

    UserProfileRepository.upsert(discord_tony, plex_username="tony_plex", custom_taste_notes="Always recommend 4K")
    
    prompt_block = UserMemoryManager.get_relevant_memories(discord_tony, "Can you suggest some thriller films?")
    assert "tony_plex" in prompt_block
    assert "Always recommend 4K" in prompt_block
    assert "Loves psychological thrillers" in prompt_block

    justin_block = UserMemoryManager.get_relevant_memories(discord_justin, "Any romance films?")
    assert "Dislikes slow-paced romance movies" in justin_block
    assert "asserted by other user" in justin_block

