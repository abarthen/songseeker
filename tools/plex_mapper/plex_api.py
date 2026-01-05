"""
Shared Plex API utilities for SongSeeker tools.

This module provides common functions for interacting with Plex servers,
used by both plex-mapper and custom-game tools.
"""

import json
from pathlib import Path

import requests

# Global cache for track remapper (year, artist, title overrides)
_track_remapper: dict[str, dict] = {}
_track_remapper_loaded = False


def load_track_remapper(remapper_path: Path = None) -> dict[str, dict]:
    """Load track remapper from JSON file. Returns dict of ratingKey -> replaceData."""
    global _track_remapper, _track_remapper_loaded

    if _track_remapper_loaded and remapper_path is None:
        return _track_remapper

    if remapper_path is None:
        # Default path: tools/plex-date-remapper.json
        remapper_path = Path(__file__).parent.parent / "plex-date-remapper.json"

    if not remapper_path.exists():
        _track_remapper_loaded = True
        return _track_remapper

    try:
        with open(remapper_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for entry in data:
            rating_key = entry.get("ratingKey")
            replace_data = entry.get("replaceData", {})
            if rating_key and replace_data:
                _track_remapper[str(rating_key)] = replace_data

        if _track_remapper:
            artist_count = sum(1 for e in _track_remapper.values() if "artist" in e)
            year_count = sum(1 for e in _track_remapper.values() if "year" in e)
            title_count = sum(1 for e in _track_remapper.values() if "title" in e)
            parts = []
            if year_count:
                parts.append(f"{year_count} year")
            if artist_count:
                parts.append(f"{artist_count} artist")
            if title_count:
                parts.append(f"{title_count} title")
            print(f"Loaded {len(_track_remapper)} track remappings ({', '.join(parts)})")

        _track_remapper_loaded = True
        return _track_remapper

    except Exception as e:
        print(f"Warning: Could not load track remapper: {e}")
        _track_remapper_loaded = True
        return _track_remapper


# Alias for backwards compatibility
def load_date_remapper(remapper_path: Path = None) -> dict[str, dict]:
    """Alias for load_track_remapper (backwards compatibility)."""
    return load_track_remapper(remapper_path)


def get_remapped_year(rating_key: str, original_year: int) -> int:
    """Get remapped year for a rating key, or return original year if not remapped."""
    if not _track_remapper_loaded:
        load_track_remapper()
    entry = _track_remapper.get(str(rating_key))
    return entry.get("year", original_year) if entry else original_year


def get_remapped_artist(rating_key: str, original_artist: str) -> str:
    """Get remapped artist for a rating key, or return original artist if not remapped."""
    if not _track_remapper_loaded:
        load_track_remapper()
    entry = _track_remapper.get(str(rating_key))
    return entry.get("artist", original_artist) if entry else original_artist


def get_remapped_title(rating_key: str, original_title: str) -> str:
    """Get remapped title for a rating key, or return original title if not remapped."""
    if not _track_remapper_loaded:
        load_track_remapper()
    entry = _track_remapper.get(str(rating_key))
    return entry.get("title", original_title) if entry else original_title


def load_plex_config(config_path: Path) -> tuple[str, str]:
    """Load Plex server URL and token from config file."""
    if not config_path.exists():
        return None, None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("serverUrl"), config.get("token")
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read config file: {e}")
        return None, None


def plex_request(url: str, token: str) -> dict:
    """Make a request to the Plex API."""
    headers = {"Accept": "application/json"}
    params = {"X-Plex-Token": token}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_plex_track(server_url: str, token: str, rating_key: str, debug: bool = False) -> dict | None:
    """Fetch track metadata directly by ratingKey."""
    try:
        url = f"{server_url}/library/metadata/{rating_key}"
        if debug:
            print(f"  DEBUG: Fetching: {url}")

        response = plex_request(url, token)
        metadata = response.get("MediaContainer", {}).get("Metadata", [])

        if not metadata:
            return None

        track = metadata[0]
        media = track.get("Media", [{}])[0]
        parts = media.get("Part", [{}])[0]

        plex_year = track.get("parentYear") or track.get("year")
        plex_artist = track.get("grandparentTitle") or track.get("originalTitle")
        plex_title = track.get("title")
        remapped_year = get_remapped_year(rating_key, plex_year)
        remapped_artist = get_remapped_artist(rating_key, plex_artist)
        remapped_title = get_remapped_title(rating_key, plex_title)

        result = {
            "ratingKey": track.get("ratingKey"),
            "title": remapped_title,
            "artist": remapped_artist,
            "album": track.get("parentTitle"),
            "year": remapped_year,
            "duration": track.get("duration"),
            "partKey": parts.get("key"),
        }

        if debug:
            year_info = f"{result['year']}"
            if remapped_year != plex_year:
                year_info += f" (remapped from {plex_year})"
            artist_info = result['artist']
            if remapped_artist != plex_artist:
                artist_info += f" (remapped from {plex_artist})"
            title_info = result['title']
            if remapped_title != plex_title:
                title_info += f" (remapped from {plex_title})"
            print(f"  DEBUG: Found: {artist_info} - {title_info} ({year_info})")

        return result

    except Exception as e:
        if debug:
            print(f"  DEBUG: Error fetching track: {e}")
        return None


def list_plex_playlists(server_url: str, token: str, debug: bool = False) -> list[dict]:
    """List all audio playlists from Plex server."""
    try:
        url = f"{server_url}/playlists"
        if debug:
            print(f"  DEBUG: Fetching playlists: {url}")

        response = plex_request(url, token)
        playlists = response.get("MediaContainer", {}).get("Metadata", [])

        # Filter to audio playlists only
        audio_playlists = []
        for playlist in playlists:
            if playlist.get("playlistType") == "audio":
                audio_playlists.append({
                    "ratingKey": playlist.get("ratingKey"),
                    "title": playlist.get("title"),
                    "leafCount": playlist.get("leafCount", 0),
                })

        return audio_playlists

    except Exception as e:
        if debug:
            print(f"  DEBUG: Error fetching playlists: {e}")
        return []


def get_playlist_tracks(server_url: str, token: str, playlist_key: str, debug: bool = False) -> list[str]:
    """Get all track rating keys from a Plex playlist."""
    try:
        url = f"{server_url}/playlists/{playlist_key}/items"
        if debug:
            print(f"  DEBUG: Fetching playlist items: {url}")

        response = plex_request(url, token)
        items = response.get("MediaContainer", {}).get("Metadata", [])

        rating_keys = []
        for item in items:
            key = item.get("ratingKey")
            if key:
                rating_keys.append(key)

        return rating_keys

    except Exception as e:
        if debug:
            print(f"  DEBUG: Error fetching playlist tracks: {e}")
        return []
