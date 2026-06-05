import logging
import json
import re
from typing import List, Dict, Any, Optional

from moviebot.db.repositories import UserProfileRepository, UserMemoryRepository, UserInteractionMemoryRepository
from moviebot.core.gemini_client import generate_gemini_content

logger = logging.getLogger(__name__)

class UserMemoryManager:
    @staticmethod
    async def extract_and_save_memories(
        discord_user_id: str,
        query_text: str,
        known_users: Optional[Dict[str, str]] = None  # Mapping of name/nickname -> discord_user_id
    ) -> List[Dict[str, Any]]:
        """
        Uses Gemini to naturally extract movie preferences (likes, dislikes, general preferences)
        from a user's chat message and saves them as atomic facts.
        
        Supports cross-user memory extraction (e.g., Tony saying "Justin hates horror").
        """
        known_users = known_users or {}
        
        # Build list of names/nicknames for Gemini context
        user_context_str = ", ".join(f"'{name}' (ID: {uid})" for name, uid in known_users.items())
        
        system_instruction = (
            "You are an expert user memory extraction engine for a movie recommendation assistant.\n"
            "Analyze the user's message to detect any declared movie preferences, interests, dislikes, or facts "
            "about themselves or other users in the chat.\n"
            "Extract facts cleanly and atomicity. Do NOT assume or invent preferences.\n"
            f"Active users in this context: {user_context_str or 'None'}\n\n"
            "Format the output as a JSON object containing a list of memories. "
            "For each memory, specify:\n"
            "- target_user_name: The name/nickname of the person this preference belongs to. "
            "Use 'self' if they are expressing their own preference, or one of the active user names/nicknames if they refer to someone else.\n"
            "- category: 'like', 'dislike', or 'general_preference'\n"
            "- fact: The preference fact stated in a third-person, concise sentence (e.g., 'Loves Canadian indie movies', 'Dislikes jump scares').\n"
            "If no movie-related preferences or personal tastes are declared, return an empty list."
        )

        json_schema = {
            "type": "OBJECT",
            "properties": {
                "memories": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "target_user_name": {
                                "type": "STRING", 
                                "description": "Name/nickname of the user this preference belongs to, or 'self' if the sender themselves."
                            },
                            "category": {
                                "type": "STRING", 
                                "enum": ["like", "dislike", "general_preference"]
                            },
                            "fact": {
                                "type": "STRING", 
                                "description": "The exact atomic preference fact in third-person, e.g. 'Loves horror movies'."
                            }
                        },
                        "required": ["target_user_name", "category", "fact"]
                    }
                }
            },
            "required": ["memories"]
        }

        try:
            response_text = await generate_gemini_content(
                prompt=query_text,
                system_instruction=system_instruction,
                json_schema=json_schema,
                temperature=0.0
            )
            
            data = json.loads(response_text)
            extracted = data.get("memories", [])
            saved_memories = []

            for item in extracted:
                target_name = item["target_user_name"].strip().lower()
                category = item["category"]
                fact = item["fact"]

                # Resolve target user id
                resolved_user_id = discord_user_id
                target_user_id = None

                if target_name != "self":
                    # Check if target name matches any known user
                    matched_id = None
                    for name, uid in known_users.items():
                        if name.lower() == target_name:
                            matched_id = uid
                            break
                    if matched_id:
                        # Cross-user memory: Stored on matched_id's profile, noting discord_user_id (the sender) as target_user_id
                        resolved_user_id = matched_id
                        target_user_id = discord_user_id
                        # Update fact to indicate author source
                        fact = f"According to context: {fact}"

                # Ensure target user profile exists
                UserProfileRepository.upsert(discord_user_id=resolved_user_id)
                
                # Check for duplicates before adding
                existing = UserMemoryRepository.get_all_for_user(resolved_user_id)
                is_duplicate = False
                for m in existing:
                    if m["fact"].lower() == fact.lower() and m["category"] == category:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    mem_id = UserMemoryRepository.add(
                        discord_user_id=resolved_user_id,
                        category=category,
                        fact=fact,
                        source="chat_extraction",
                        target_user_id=target_user_id
                    )
                    saved_memories.append({
                        "id": mem_id,
                        "discord_user_id": resolved_user_id,
                        "category": category,
                        "fact": fact,
                        "target_user_id": target_user_id
                    })
                    
                    # Enforce cap limits
                    UserMemoryRepository.prune_oldest(resolved_user_id, max_limit=100)

            return saved_memories

        except Exception as e:
            logger.error(f"Error extracting and saving memories: {e}")
            return []

    @staticmethod
    def get_relevant_memories(
        discord_user_id: str,
        query_text: str,
        known_users: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Retrieves user profiles and relevant atomic memories for the conversational RAG context.
        Returns a formatted prompt block containing profile info, custom taste notes, and atomic memories.
        Supports cross-user visibility checks to fetch other mentioned users' preferences.
        """
        known_users = known_users or {}
        
        # 1. Fetch current user's profile and memories
        profile = UserProfileRepository.get(discord_user_id)
        memories = UserMemoryRepository.get_all_social(discord_user_id)

        lines = ["User Preferences & Tastes (Requester):"]
        if profile:
            if profile.get("plex_username"):
                lines.append(f"Mapped Plex Username: {profile['plex_username']}")
            if profile.get("custom_taste_notes"):
                lines.append(f"Manual Taste Preference Overrides: {profile['custom_taste_notes']}")

        # Helper to score and format memories for a specific user
        def format_user_memories(user_memories: List[Dict[str, Any]]) -> List[str]:
            scored_memories = []
            query_words = set(re.findall(r'\w+', query_text.lower()))

            for m in user_memories:
                fact_text = m["fact"]
                score = 0
                fact_words = set(re.findall(r'\w+', fact_text.lower()))
                overlap = query_words.intersection(fact_words)
                score += len(overlap) * 2
                
                if m["category"] in query_text.lower():
                    score += 3
                    
                scored_memories.append((score, m))

            scored_memories.sort(key=lambda x: x[0], reverse=True)
            top_memories = [item[1] for item in scored_memories[:15]]

            mem_lines = []
            for m in top_memories:
                category_label = m["category"].upper().replace("_", " ")
                if m.get("target_user_id"):
                    mem_lines.append(f"- [{category_label}] {m['fact']} (asserted by other user)")
                else:
                    mem_lines.append(f"- [{category_label}] {m['fact']}")
            return mem_lines

        req_mem_lines = format_user_memories(memories)
        if req_mem_lines:
            lines.extend(req_mem_lines)
        else:
            lines.append("- No atomic memories recorded yet.")

        # 2. Check if other known users are mentioned in the query
        for name, uid in known_users.items():
            if uid == discord_user_id:
                continue  # Already processed requester
            
            # Simple case-insensitive name match
            if re.search(r'\b' + re.escape(name) + r'\b', query_text, re.IGNORECASE):
                other_profile = UserProfileRepository.get(uid)
                is_public = True
                if other_profile and other_profile.get("metadata_json"):
                    try:
                        meta = json.loads(other_profile["metadata_json"])
                        is_public = meta.get("public_visibility", True)
                    except Exception:
                        pass
                
                if is_public:
                    other_memories = UserMemoryRepository.get_all_social(uid)
                    lines.append(f"\nUser Preferences & Tastes ({name}):")
                    if other_profile:
                        if other_profile.get("plex_username"):
                            lines.append(f"Mapped Plex Username: {other_profile['plex_username']}")
                        if other_profile.get("custom_taste_notes"):
                            lines.append(f"Manual Taste Preference Overrides: {other_profile['custom_taste_notes']}")
                    
                    other_mem_lines = format_user_memories(other_memories)
                    if other_mem_lines:
                        lines.extend(other_mem_lines)
                    else:
                        lines.append("- No atomic memories recorded yet.")
                else:
                    lines.append(f"\n[Preferences of user '{name}' are private and cannot be read by other users.]")

        return "\n".join(lines)
