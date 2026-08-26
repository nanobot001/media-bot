import re
from typing import Dict, Any, Optional


def format_size_bytes(size_bytes: Optional[int]) -> str:
    """Formats bytes into human-readable string (GB / MB)."""
    if not size_bytes or size_bytes <= 0:
        return "0 MB"
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def parse_release_details(title: str) -> Dict[str, Any]:
    """
    Parses a torrent release title to extract structured metadata:
    - resolution: '2160p', '1080p', '720p', '480p', or 'Unknown'
    - source_type: 'Remux', 'Web-DL', 'WEBRip', 'BluRay', 'HDTV', 'DVDRip', etc.
    - quality_label: e.g. '2160p Remux', '2160p Web-DL', '1080p BluRay'
    - hdr: 'DV / HDR10+', 'Dolby Vision', 'HDR10+', 'HDR', etc.
    - codec: 'HEVC (x265)', 'x264', 'AV1', etc.
    - audio: 'Dolby Atmos', 'TrueHD 7.1', 'DTS-HD MA', 'DDP 5.1', 'DD 5.1', 'AAC 2.0', etc.
    - channels: '7.1', '5.1', '2.0', etc.
    - release_group: e.g. 'FLUX', 'FraMeSToR', 'NTb', etc.
    """
    clean_title = title.strip()
    norm = clean_title.replace(".", " ").replace("_", " ").replace("-", " ")

    # 1. Resolution
    resolution = "Unknown"
    if re.search(r'\b(2160p|4k|uhd)\b', norm, re.IGNORECASE):
        resolution = "2160p"
    elif re.search(r'\b(1080p|1080i|fhd)\b', norm, re.IGNORECASE):
        resolution = "1080p"
    elif re.search(r'\b(720p|hd)\b', norm, re.IGNORECASE):
        resolution = "720p"
    elif re.search(r'\b(480p|576p|sd)\b', norm, re.IGNORECASE):
        resolution = "480p"

    # 2. Source Type
    source_type = "Unknown"
    is_remux = bool(re.search(r'\bremux\b', norm, re.IGNORECASE))
    if is_remux:
        source_type = "Remux"
    elif re.search(r'\b(web[\s._-]?dl|webrip|web)\b', clean_title, re.IGNORECASE):
        if re.search(r'\bwebrip\b', clean_title, re.IGNORECASE):
            source_type = "WEBRip"
        else:
            source_type = "Web-DL"
    elif re.search(r'\b(bluray|bdrip|brrip|blu[\s._-]?ray)\b', clean_title, re.IGNORECASE):
        source_type = "BluRay"
    elif re.search(r'\b(hdtv|pdtv|dsr)\b', clean_title, re.IGNORECASE):
        source_type = "HDTV"
    elif re.search(r'\b(dvdrip|dvd[\s._-]?r|dvd)\b', clean_title, re.IGNORECASE):
        source_type = "DVDRip"
    elif re.search(r'\b(cam|hdcam|telesync|ts)\b', clean_title, re.IGNORECASE):
        source_type = "CAM/TS"

    # 3. Quality Label
    if resolution != "Unknown" and source_type != "Unknown":
        quality_label = f"{resolution} {source_type}"
    elif resolution != "Unknown":
        quality_label = resolution
    elif source_type != "Unknown":
        quality_label = source_type
    else:
        quality_label = "HD"

    # 4. HDR / Color Space
    has_dv = bool(re.search(r'\b(dv|dovi|dolby[\s._-]?vision)\b', clean_title, re.IGNORECASE))
    has_hdr10plus = bool(re.search(r'\b(hdr10\+|hdr10plus)\b', clean_title, re.IGNORECASE))
    has_hdr = bool(re.search(r'\b(hdr|hdr10)\b', clean_title, re.IGNORECASE))

    hdr: Optional[str] = None
    if has_dv and has_hdr10plus:
        hdr = "DV / HDR10+"
    elif has_dv and has_hdr:
        hdr = "DV / HDR"
    elif has_dv:
        hdr = "Dolby Vision"
    elif has_hdr10plus:
        hdr = "HDR10+"
    elif has_hdr:
        hdr = "HDR"

    # 5. Video Codec
    codec: Optional[str] = None
    if re.search(r'\b(hevc|x265|h[\s._-]?265)\b', clean_title, re.IGNORECASE):
        codec = "HEVC (x265)"
    elif re.search(r'\b(av1)\b', clean_title, re.IGNORECASE):
        codec = "AV1"
    elif re.search(r'\b(x264|h[\s._-]?264|avc)\b', clean_title, re.IGNORECASE):
        codec = "x264"
    elif re.search(r'\b(xvid|divx)\b', clean_title, re.IGNORECASE):
        codec = "XviD"
    elif re.search(r'\b(mpeg[\s._-]?2)\b', clean_title, re.IGNORECASE):
        codec = "MPEG2"

    # 6. Audio Codecs and Channels
    audio: Optional[str] = None
    channels: Optional[str] = None

    if re.search(r'(?:^|[^\d])7[\s._-]1(?:[^\d]|$)', clean_title):
        channels = "7.1"
    elif re.search(r'(?:^|[^\d])5[\s._-]1(?:[^\d]|$)', clean_title):
        channels = "5.1"
    elif re.search(r'(?:^|[^\d])2[\s._-]0(?:[^\d]|$)', clean_title):
        channels = "2.0"

    has_atmos = bool(re.search(r'\batmos\b', norm, re.IGNORECASE))
    has_truehd = bool(re.search(r'\btruehd\b', norm, re.IGNORECASE))
    has_dtshd = bool(re.search(r'\bdts[\s._-]?hd[\s._-]?(ma)?\b', norm, re.IGNORECASE))
    has_dts = bool(re.search(r'\bdts\b', norm, re.IGNORECASE))
    has_ddp = bool(re.search(r'\b(ddp|dd\+|eac3|e[\s._-]?ac3|ddplus)', norm, re.IGNORECASE) or re.search(r'ddp\d', clean_title, re.IGNORECASE))
    has_dd = bool(re.search(r'\b(dd|ac3|ac[\s._-]?3)', norm, re.IGNORECASE) or re.search(r'ac3\d', clean_title, re.IGNORECASE))
    has_flac = bool(re.search(r'\bflac\b', norm, re.IGNORECASE))
    has_aac = bool(re.search(r'\baac', norm, re.IGNORECASE))
    has_mp3 = bool(re.search(r'\bmp3\b', norm, re.IGNORECASE))

    if has_atmos:
        audio = "Dolby Atmos"
    elif has_truehd:
        audio = f"TrueHD {channels}" if channels else "TrueHD"
    elif has_dtshd:
        audio = f"DTS-HD MA {channels}" if channels else "DTS-HD MA"
    elif has_dts:
        audio = f"DTS {channels}" if channels else "DTS 5.1"
    elif has_ddp:
        audio = f"DDP {channels}" if channels else "DDP 5.1"
    elif has_dd:
        audio = f"DD {channels}" if channels else "DD 5.1"
    elif has_flac:
        audio = f"FLAC {channels}" if channels else "FLAC"
    elif has_aac:
        audio = f"AAC {channels}" if channels else "AAC 2.0"
    elif has_mp3:
        audio = f"MP3 {channels}" if channels else "MP3"
    elif channels:
        audio = f"Audio {channels}"

    # 7. Release Group
    release_group: Optional[str] = None
    group_match = re.search(r'-([a-zA-Z0-9]+)(?:\[.*?\])?$', clean_title)
    if group_match:
        release_group = group_match.group(1)
    else:
        # Check bracketed group e.g. [FLUX]
        bracket_match = re.search(r'\[([a-zA-Z0-9_-]+)\]$', clean_title)
        if bracket_match:
            release_group = bracket_match.group(1)

    # 8. TV Season and Episode Extraction
    tv_info = extract_tv_spec(clean_title)

    return {
        "resolution": resolution,
        "source_type": source_type,
        "quality_label": quality_label,
        "hdr": hdr,
        "codec": codec,
        "audio": audio,
        "channels": channels,
        "release_group": release_group,
        "tv_label": tv_info.get("tv_label"),
        "season": tv_info.get("season"),
        "episode": tv_info.get("episode"),
        "is_season_pack": tv_info.get("is_season_pack"),
        "is_complete_series": tv_info.get("is_complete_series"),
        "is_tv": tv_info.get("is_tv"),
    }


def is_browser_stream_compatible(title: str) -> bool:
    """Return True only when a release explicitly advertises a safe HTML5 format.

    The discovery UI must not imply browser playback merely because a torrent is
    instant-cached. Native browser playback needs both a supported container and
    supported audio/video tracks; H.264 video in an MKV with DDP/DTS audio can
    otherwise produce the misleading video-without-sound symptom.
    """
    parsed = parse_release_details(title or "")
    normalized = (title or "").lower()
    codec = (parsed.get("codec") or "").lower()
    audio = (parsed.get("audio") or "").lower()

    if any(marker in normalized for marker in ("x265", "h265", "hevc", "av1", "10bit")):
        return False

    # Keep this conservative: MP4/M4V + H.264/AVC + AAC/MP3 is the reliable
    # cross-browser movie path. MKV, WebM, DDP/E-AC3, DTS, TrueHD, Atmos, and
    # releases with an unknown audio track remain external-player candidates.
    has_browser_container = bool(re.search(r"\.(mp4|m4v)(?:$|[?#])", normalized))
    has_browser_audio = bool(re.search(r"\b(aac|mp3)\b", audio))
    return (
        codec in {"x264", "h264", "avc"}
        and has_browser_container
        and has_browser_audio
    )


def extract_tv_spec(title: str) -> Dict[str, Any]:
    """
    Extracts TV season, episode, and pack metadata from a torrent title:
    - is_tv: bool
    - season: Optional[int]
    - episode: Optional[int]
    - is_season_pack: bool
    - is_complete_series: bool
    - tv_label: e.g. 'S10E09', 'Season 1 Pack', 'Complete Series'
    """
    clean = title.strip()

    # 1. Complete Series
    if re.search(r'\b(complete[\s._-]?series|all[\s._-]?seasons|s01[\s._-]?s\d+)\b', clean, re.IGNORECASE):
        return {
            "is_tv": True,
            "season": None,
            "episode": None,
            "is_season_pack": True,
            "is_complete_series": True,
            "tv_label": "Complete Series"
        }

    # 2. Season xx Episode yy (e.g. S10E09, S01E01)
    m_ep = re.search(r'\b[sS](\d{1,2})[eE](\d{1,3})\b', clean)
    if m_ep:
        s_num = int(m_ep.group(1))
        ep_num = int(m_ep.group(2))
        return {
            "is_tv": True,
            "season": s_num,
            "episode": ep_num,
            "is_season_pack": False,
            "is_complete_series": False,
            "tv_label": f"S{s_num:02d}E{ep_num:02d}"
        }

    # 3. Season Pack (e.g. S01, S10, Season 1, Season.01)
    m_season = re.search(r'\b(?:[sS](\d{1,2})|season[\s._-]?(\d{1,2}))\b', clean, re.IGNORECASE)
    if m_season:
        s_num = int(m_season.group(1) or m_season.group(2))
        return {
            "is_tv": True,
            "season": s_num,
            "episode": None,
            "is_season_pack": True,
            "is_complete_series": False,
            "tv_label": f"Season {s_num} Pack"
        }

    return {
        "is_tv": False,
        "season": None,
        "episode": None,
        "is_season_pack": False,
        "is_complete_series": False,
        "tv_label": None
    }


def normalize_title(title: str) -> str:
    """Normalizes title string for robust token and similarity comparison."""
    if not title:
        return ""
    # Strip common video file extensions
    t = re.sub(r'\.(mkv|mp4|avi|ts|iso)$', '', title, flags=re.IGNORECASE)
    # Replace dots, underscores, dashes, brackets with spaces
    t = re.sub(r'[\._\-\[\]\(\)\{\}\+]', ' ', t)
    # Remove non-alphanumeric except spaces
    t = re.sub(r'[^\w\s]', '', t, flags=re.UNICODE)
    # Lowercase and collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip().lower()
    return t


def extract_year_from_title(title: str) -> Optional[int]:
    """Extracts 4-digit release year from a release title (1920-2035)."""
    if not title:
        return None
    matches = re.findall(r'\b(19\d{2}|20\d{2})\b', title)
    if matches:
        for m in matches:
            val = int(m)
            if 1920 <= val <= 2035:
                return val
    return None


def compute_title_similarity(target: str, candidate_release: str) -> float:
    """
    Computes a robust similarity ratio (0.0 to 1.0) between target title and candidate release title.
    Disregards scene specs (1080p, WEB-DL, x264, etc.) in candidate.
    """
    norm_target = normalize_title(target)
    if not norm_target:
        return 1.0

    norm_cand = normalize_title(candidate_release)
    # Strip scene specs and TV season tags from candidate
    norm_cand = re.sub(
        r'\b(s\d{1,2}e\d{1,3}|s\d{1,2}|season\s*\d{1,2}|complete\s*series|2160p|1080p|1080i|720p|480p|4k|uhd|fhd|hd|remux|webdl|webrip|web|bluray|bdrip|brrip|hdtv|dvdrip|hevc|x265|h265|x264|h264|av1|xvid|atmos|truehd|dtshd|dts|ddp|ac3|flac|aac|hdr|hdr10|dv|dolby|vision|10bit|multi)\b',
        ' ',
        norm_cand
    )
    norm_cand = re.sub(r'\s+', ' ', norm_cand).strip()

    target_tokens = [tok for tok in norm_target.split() if tok not in ('the', 'a', 'an', 'and', 'of', 'in', 'on', 'at', 'to', 'for')]
    if not target_tokens:
        target_tokens = norm_target.split()

    cand_tokens = norm_cand.split()
    if not cand_tokens:
        return 0.0

    # Exact token containment check
    matched_tokens = 0.0
    for tok in target_tokens:
        # Check whole word boundary match in candidate tokens
        if tok in cand_tokens:
            matched_tokens += 1.0
        elif any(c_tok.startswith(tok) or tok.startswith(c_tok) for c_tok in cand_tokens if len(tok) >= 4 and len(c_tok) >= 4):
            matched_tokens += 0.75

    token_coverage = matched_tokens / len(target_tokens) if target_tokens else 0.0

    # Prefix match bonus: Does candidate start with the target title?
    prefix_bonus = 0.2 if norm_cand.startswith(norm_target) else 0.0

    # Severe penalty if candidate contains completely different primary words before target
    if target_tokens and cand_tokens and target_tokens[0] != cand_tokens[0]:
        if not any(target_tokens[0] == c for c in cand_tokens[:2]):
            token_coverage *= 0.3

    ratio = min(1.0, token_coverage + prefix_bonus)
    return ratio


def score_and_rank_releases(
    releases: list[Dict[str, Any]],
    preferred_quality: str = "1080p Web-DL",
    prefer_cached: bool = True,
    target_title: Optional[str] = None,
    target_year: Optional[int] = None,
    target_season: Optional[int] = None,
    target_episode: Optional[int] = None
) -> list[Dict[str, Any]]:
    """
    Ranks release candidates based on user quality presets, instant cache availability,
    resolution hierarchy, codec efficiency, audio channels, and TV season/episode precision.
    """
    scored = []
    pref_lower = (preferred_quality or "1080p").lower()

    for r in releases:
        title = r.get("title") or ""
        parsed = parse_release_details(title)
        score = 0
        mismatch = False

        # --- 0. Title & Year Precision Guard ---
        if target_title:
            sim = compute_title_similarity(target_title, title)
            if sim >= 0.85:
                score += 350
            elif sim >= 0.60:
                score += 150
            else:
                # Title similarity too low
                score -= 5000
                mismatch = True

        # For TV shows, don't penalize year differences if it's a TV release (seasons air across decades)
        is_tv_release = bool(parsed.get("is_tv"))
        if target_year and not is_tv_release:
            cand_year = extract_year_from_title(title)
            if cand_year:
                year_diff = abs(cand_year - target_year)
                if year_diff == 0:
                    score += 250
                elif year_diff == 1:
                    score += 100
                else:
                    score -= 3000
                    mismatch = True

        # --- TV Season & Episode Precision Gating ---
        if target_season is not None:
            c_season = parsed.get("season")
            if c_season == target_season:
                score += 400
                if target_episode is not None:
                    c_ep = parsed.get("episode")
                    if c_ep == target_episode:
                        score += 500
                    elif c_ep is not None:
                        score -= 2000
                        mismatch = True
            elif c_season is not None and not parsed.get("is_complete_series"):
                # Different season (e.g. asked for Season 1, candidate is Season 10)
                score -= 3000
                mismatch = True
        elif is_tv_release:
            # If no target season specified for TV, prefer Season 1 or Complete Series
            if parsed.get("is_complete_series"):
                score += 300
            elif parsed.get("season") == 1:
                score += 200

        # 1. Instant Cache Bonus (eliminates P2P download wait)
        is_cached = bool(r.get("cached"))
        if prefer_cached and is_cached:
            score += 1000

        # 2. Resolution Scoring
        res = parsed.get("resolution", "Unknown")
        if "2160p" in pref_lower or "4k" in pref_lower:
            if res == "2160p":
                score += 500
            elif res == "1080p":
                score += 300
            elif res == "720p":
                score += 100
        elif "720p" in pref_lower:
            if res == "720p":
                score += 500
            elif res == "1080p":
                score += 200
        else:
            # Default 1080p preference
            if res == "1080p":
                score += 500
            elif res == "2160p":
                score += 300
            elif res == "720p":
                score += 100

        # 3. Source Quality Match
        source = (parsed.get("source_type") or "Unknown").lower()
        if "remux" in pref_lower and "remux" in source:
            score += 150
        elif "web" in pref_lower and ("web" in source or "webrip" in source):
            score += 150
        elif "bluray" in pref_lower and ("bluray" in source or "brrip" in source):
            score += 150

        # 4. Codec & Audio Bonuses
        codec = (parsed.get("codec") or "").lower()
        if "hevc" in codec or "x265" in codec or "10bit" in title.lower():
            score += 60
        elif "x264" in codec:
            score += 30

        audio = (parsed.get("audio") or "").lower()
        if any(a in audio for a in ["atmos", "truehd", "7.1", "5.1", "dts"]):
            score += 40

        # 5. Seeders (small tie-breaker)
        seeders = int(r.get("seeders") or 0)
        score += min(seeders // 5, 50)

        r_copy = dict(r)
        r_copy["_score"] = score
        r_copy["_parsed"] = parsed
        r_copy["_mismatch"] = mismatch
        scored.append(r_copy)

    # Sort descending by total score
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored
