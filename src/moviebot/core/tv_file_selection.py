import re
from typing import List, Dict, Any, Tuple, Set, Optional


# Regex exclusions for junk files
EXCLUSION_PATTERN = re.compile(
    r'(sample|trailer|extra|bonus|featurette|behind[\s._-]?the[\s._-]?scenes|deleted[\s._-]?scene|interview|nfo|preview)',
    re.IGNORECASE
)

# Valid video file extensions
VALID_EXTENSIONS = ('.mkv', '.mp4', '.avi', '.m4v', '.ts', '.wmv')


def extract_season_episode(filename: str, path: str = "") -> Optional[Tuple[int, int]]:
    """
    Extracts (season_number, episode_number) from a filename or its containing directory path.
    Supports standard patterns:
      - S01E02, s1e2, S01E02-E03, S01E01-08
      - 1x02, 01x02
      - Season 1 Episode 2, Season.1.Episode.02
      - Episode 02, E02 (with season inferred from path)
    """
    target = f"{path}/{filename}" if path else filename

    # 1. Standard S01E02 or S01E01-02
    m = re.search(r'[sS](\d{1,2})[\s._-]*[eE](\d{1,3})', target)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 2. 1x02 format
    m = re.search(r'(?:^|[\s._\(\[-])(\d{1,2})[xX](\d{1,3})(?:[\s._\)\]-]|$)', target)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 3. "Season 1 Episode 2"
    m = re.search(r'[sS]eason[\s._-]*(\d{1,2})[\s._-]*[eE]pisode[\s._-]*(\d{1,3})', target, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 4. Check if season is in directory path, e.g. "Season 01/Episode 02.mkv" or "S01/02.mkv"
    season_in_path = None
    m_season = re.search(r'(?:[sS]eason[\s._-]*(\d{1,2})|[sS](\d{1,2}))', path)
    if m_season:
        season_in_path = int(m_season.group(1) or m_season.group(2))

    # Look for episode in filename if season was in path
    if season_in_path is not None:
        m_ep = re.search(r'(?:[eE]pisode[\s._-]*|[eE]|^|\b)(\d{1,3})(?:[\s._\)-]|$)', filename)
        if m_ep:
            try:
                ep_num = int(m_ep.group(1))
                if 1 <= ep_num <= 999:
                    return season_in_path, ep_num
            except ValueError:
                pass

    # 5. Standalone "Episode 02" or "E02" -> default season 1 if not otherwise specified
    m_standalone = re.search(r'(?:[eE]pisode[\s._-]*|[eE])(\d{1,3})', filename, re.IGNORECASE)
    if m_standalone:
        return 1, int(m_standalone.group(1))

    return None


def parse_tv_torrent_files(
    files: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Parses a multi-file torrent manifest from AllDebrid, isolates valid video files,
    strips junk (samples/nfo/trailers/extras), and extracts structured season & episode numbers.

    Accepts:
        files: A list of dicts with file metadata ('name'/'n', 'size'/'s', 'id', 'link'/'l', 'path').

    Returns:
        List of structured episode dicts sorted by (season, episode):
        [
            {
                "id": int,
                "season": int,
                "episode": int,
                "name": str,
                "size": int,
                "link": str,
                "path": str,
            },
            ...
        ]
    """
    if not files:
        return []

    cleaned_files = []
    for idx, f in enumerate(files, start=1):
        name = f.get("name") or f.get("n") or ""
        size = f.get("size") or f.get("s") or f.get("size_bytes") or 0
        file_id = f.get("id", idx)
        link = f.get("link") or f.get("l") or ""
        path = f.get("path") or ""

        if not name:
            continue

        cleaned_files.append({
            "id": file_id,
            "name": name,
            "size": int(size),
            "link": link,
            "path": path,
        })

    # 1. Exclusion filter (samples, trailers, featurettes, extras, nfo, txt)
    valid_files = [f for f in cleaned_files if not EXCLUSION_PATTERN.search(f["name"]) and not EXCLUSION_PATTERN.search(f["path"])]

    # 2. Extension filter
    valid_files = [f for f in valid_files if f["name"].lower().endswith(VALID_EXTENSIONS)]

    # 3. Parse Season and Episode for each file
    parsed_episodes = []
    for f in valid_files:
        se_tuple = extract_season_episode(f["name"], f["path"])
        if se_tuple:
            season, episode = se_tuple
            parsed_episodes.append({
                "id": f["id"],
                "season": season,
                "episode": episode,
                "name": f["name"],
                "size": f["size"],
                "link": f["link"],
                "path": f["path"],
            })

    # Sort primarily by season, then episode
    parsed_episodes.sort(key=lambda x: (x["season"], x["episode"], x["name"]))
    return parsed_episodes


def filter_unowned_episodes(
    episodes: List[Dict[str, Any]],
    owned_set: Set[Tuple[int, int]]
) -> List[Dict[str, Any]]:
    """
    Filters out episode items that already exist in the user's Plex library.
    
    Args:
        episodes: List of parsed episode dicts (containing 'season' and 'episode' keys).
        owned_set: Set of (season_number, episode_number) tuples owned in Plex.

    Returns:
        List of episode dicts for missing/unowned episodes.
    """
    if not owned_set:
        return episodes

    return [
        ep for ep in episodes
        if (ep.get("season"), ep.get("episode")) not in owned_set
    ]
