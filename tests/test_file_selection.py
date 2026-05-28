import json
import pytest
from pathlib import Path
from moviebot.core.file_selection import select_primary_video_file


@pytest.fixture
def fixtures_data():
    fixture_path = Path(__file__).parent / "fixtures" / "alldebrid_files_sample.json"
    with open(fixture_path, "r") as f:
        return json.load(f)


def test_select_single_movie(fixtures_data):
    files = fixtures_data["single_movie"]
    is_resolved, chosen = select_primary_video_file(files)
    assert is_resolved is True
    assert len(chosen) == 1
    assert chosen[0]["name"] == "The.Matrix.Resurrections.2021.1080p.mkv"


def test_select_movie_excluding_samples(fixtures_data):
    files = fixtures_data["movie_with_sample_and_trailer"]
    is_resolved, chosen = select_primary_video_file(files)
    assert is_resolved is True
    assert len(chosen) == 1
    assert chosen[0]["name"] == "The.Matrix.Resurrections.2021.1080p.mkv"


def test_select_ambiguous_files_returns_multiple(fixtures_data):
    files = fixtures_data["ambiguous_sizes"]
    is_resolved, chosen = select_primary_video_file(files)
    # Both Part1 and Part2 are around 6GB (within 10% of each other), sample.mkv is filtered
    assert is_resolved is False
    assert len(chosen) == 2
    names = [f["name"] for f in chosen]
    assert "The.Matrix.Resurrections.2021.Part1.mkv" in names
    assert "The.Matrix.Resurrections.2021.Part2.mkv" in names


def test_no_valid_video_files_raises():
    files = [
        {"name": "readme.txt", "size": 100},
        {"name": "sample.mkv", "size": 20000}
    ]
    with pytest.raises(ValueError, match="No valid movie files found"):
        select_primary_video_file(files)
