from script import parse_tracks, parse_profile
from datetime import date


def test_parse_tracks_handles_empty_genre():
    """SoundCloud sometimes returns genre as an empty string — should become None."""
    fake_response = {
        "collection": [
            {
                "id": 123,
                "title": "Test Track",
                "genre": "",
                "created_at": "2025/08/24 15:43:03 +0000",
                "playback_count": 10,
                "favoritings_count": 2,
                "reposts_count": 0,
                "comment_count": 0,
                "download_count": 0,
            }
        ]
    }

    tracks_rows, _ = parse_tracks(fake_response)

    assert tracks_rows[0]["genre"] is None


def test_parse_tracks_keeps_genre_when_present():
    """When genre is a real value, it should pass through unchanged."""
    fake_response = {
        "collection": [
            {
                "id": 456,
                "title": "Another Track",
                "genre": "Electronic",
                "created_at": "2026/08/21 21:08:53 +0000",
                "playback_count": 5,
                "favoritings_count": 1,
                "reposts_count": 0,
                "comment_count": 0,
                "download_count": 0,
            }
        ]
    }

    tracks_rows, _ = parse_tracks(fake_response)

    assert tracks_rows[0]["genre"] == "Electronic"


def test_parse_tracks_produces_matching_snapshot_row():
    """Each track should produce exactly one snapshot row with today's counters."""
    fake_response = {
        "collection": [
            {
                "id": 123,
                "title": "Test Track",
                "genre": "Techno",
                "created_at": "2026/08/21 15:43:03 +0000",
                "playback_count": 100,
                "favoritings_count": 20,
                "reposts_count": 3,
                "comment_count": 1,
                "download_count": 0,
            }
        ]
    }

    _, snapshot_rows = parse_tracks(fake_response)

    assert len(snapshot_rows) == 1
    assert snapshot_rows[0]["track_id"] == 123
    assert snapshot_rows[0]["playback_count"] == 100
    assert snapshot_rows[0]["snapshot_date"] == date.today()


def test_parse_profile_extracts_expected_fields():
    """parse_profile should extract only the fields we care about, plus today's date."""
    fake_response = {
        "followers_count": 27,
        "followings_count": 121,
        "public_favorites_count": 778,
        "reposts_count": 65,
        "username": "irrelevant field, should be ignored",
    }

    account_row = parse_profile(fake_response)

    assert account_row == {
        "snapshot_date": date.today(),
        "followers_count": 27,
        "followings_count": 121,
        "public_favorites_count": 778,
        "reposts_count": 65,
    }