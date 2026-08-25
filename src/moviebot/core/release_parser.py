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

    return {
        "resolution": resolution,
        "source_type": source_type,
        "quality_label": quality_label,
        "hdr": hdr,
        "codec": codec,
        "audio": audio,
        "channels": channels,
        "release_group": release_group
    }
