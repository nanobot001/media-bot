import json
from typing import List, Dict, Any, Optional
from moviebot.core.embeddings import decode_vector, cosine_similarity
from moviebot.adapters.tautulli_client import TautulliClient


def generate_taste_vector(watched_vectors: List[List[float]]) -> List[float]:
    """Compute the dimension-wise average of a list of float vectors. L2 normalizes the result."""
    if not watched_vectors:
        return [0.0] * 768

    dim = len(watched_vectors[0])
    avg_vector = [0.0] * dim

    for vec in watched_vectors:
        if len(vec) != dim:
            continue
        for i in range(dim):
            avg_vector[i] += vec[i]

    # Compute average
    n = len(watched_vectors)
    avg_vector = [x / n for x in avg_vector]

    # L2 normalize the average vector
    magnitude = sum(x * x for x in avg_vector) ** 0.5
    if magnitude > 0:
        avg_vector = [x / magnitude for x in avg_vector]

    return avg_vector


async def recommend_movies(db_conn, user: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Retrieve Tautulli watch histories, build a taste profile vector, and recommend unwatched movies
    by blending cosine vector similarity and genre/director affinity weights.
    """
    client = TautulliClient()
    watched_keys = set()
    user_resolved = None

    # Try retrieving watch history from Tautulli
    if client.api_key:
        params = {"length": 500}
        if user:
            try:
                users_list = await client._query("get_users")
                if isinstance(users_list, list):
                    user_lower = user.lower()
                    matched_user = None
                    for u in users_list:
                        uname = u.get("username")
                        fname = u.get("friendly_name")
                        if (uname and uname.lower() == user_lower) or (fname and fname.lower() == user_lower):
                            matched_user = u
                            break
                    if matched_user:
                        params["user_id"] = matched_user.get("user_id")
                        user_resolved = matched_user.get("friendly_name") or matched_user.get("username")
                    else:
                        params["user"] = user
                else:
                    params["user"] = user
            except Exception:
                params["user"] = user

        try:
            history_data = await client._query("get_history", params)
            entries = history_data.get("data", [])
            for item in entries:
                # Basic check for movies (Tautulli history entries for movies have grandparent_title as null/empty)
                if item.get("media_type") == "movie" or (item.get("rating_key") and not item.get("grandparent_title")):
                    rating_key = item.get("rating_key")
                    if rating_key:
                        watched_keys.add(str(rating_key))
        except Exception:
            pass

    # Load all library items from SQLite
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT rating_key, title, year, genres, directors, synopsis_vector, watch_status, watch_count
        FROM library_items
    """)
    rows = cursor.fetchall()

    watched_items = []
    unwatched_items = []

    # If watched_keys is empty (e.g. Tautulli unconfigured or offline), we use DB columns as fallback
    use_db_fallback = len(watched_keys) == 0

    for row in rows:
        rating_key, title, year, genres_json, directors_json, vector_blob, watch_status, watch_count = row

        # Safe JSON parse
        try:
            genres = json.loads(genres_json) if genres_json else []
        except Exception:
            genres = []

        try:
            directors = json.loads(directors_json) if directors_json else []
        except Exception:
            directors = []

        # Decode vector
        vector = None
        if vector_blob:
            try:
                vector = decode_vector(vector_blob)
            except Exception:
                pass

        item_info = {
            "rating_key": rating_key,
            "title": title,
            "year": year,
            "genres": genres,
            "directors": directors,
            "vector": vector
        }

        is_watched = False
        if not use_db_fallback:
            is_watched = str(rating_key) in watched_keys
        else:
            is_watched = (watch_status == "watched") or (watch_count and watch_count > 0)

        if is_watched:
            watched_items.append(item_info)
        else:
            unwatched_items.append(item_info)

    # Filter watched items with valid vectors
    valid_watched_vectors = [item["vector"] for item in watched_items if item["vector"]]

    # Build statistics
    genre_counts = {}
    director_counts = {}
    for item in watched_items:
        for g in item["genres"]:
            genre_counts[g] = genre_counts.get(g, 0) + 1
        for d in item["directors"]:
            director_counts[d] = director_counts.get(d, 0) + 1

    max_genre_count = max(genre_counts.values()) if genre_counts else 1
    max_director_count = max(director_counts.values()) if director_counts else 1

    # Generate taste vector
    taste_vector = generate_taste_vector(valid_watched_vectors)
    has_taste_vector = len(valid_watched_vectors) > 0

    # Score unwatched movies
    scored_recommendations = []

    for item in unwatched_items:
        # Ignore if item has no vector
        if not item["vector"]:
            continue

        # Cosine similarity
        cos_sim = 0.0
        if has_taste_vector:
            cos_sim = cosine_similarity(item["vector"], taste_vector)

        # Genre match score (average count fraction for the movie's genres)
        genre_match_score = 0.0
        if item["genres"] and genre_counts:
            genre_match_score = sum(genre_counts.get(g, 0) for g in item["genres"]) / (max_genre_count * len(item["genres"]))

        # Director match score (average count fraction for the movie's directors)
        director_match_score = 0.0
        if item["directors"] and director_counts:
            director_match_score = sum(director_counts.get(d, 0) for d in item["directors"]) / (max_director_count * len(item["directors"]))

        # Combined score formula:
        # Cosine similarity + 0.3 * genre + 0.5 * director
        combined_score = cos_sim + (0.3 * genre_match_score) + (0.5 * director_match_score)

        scored_recommendations.append({
            "rating_key": item["rating_key"],
            "title": item["title"],
            "year": item["year"],
            "genres": item["genres"],
            "directors": item["directors"],
            "cosine_similarity": cos_sim,
            "genre_score": genre_match_score,
            "director_score": director_match_score,
            "score": combined_score
        })

    # Sort recommendations by score descending
    scored_recommendations.sort(key=lambda x: x["score"], reverse=True)

    return scored_recommendations[:limit]
