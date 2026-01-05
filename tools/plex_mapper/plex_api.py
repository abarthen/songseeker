"""
Shared Plex API utilities for SongSeeker tools.

This module provides common functions for interacting with Plex servers,
used by both plex-mapper and custom-game tools.
"""

import json
import re
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
            ratingkey_count = sum(1 for e in _track_remapper.values() if "ratingKey" in e)
            parts = []
            if year_count:
                parts.append(f"{year_count} year")
            if artist_count:
                parts.append(f"{artist_count} artist")
            if title_count:
                parts.append(f"{title_count} title")
            if ratingkey_count:
                parts.append(f"{ratingkey_count} ratingKey")
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


def get_alternative_ratingkey(rating_key: str) -> str | None:
    """Get alternative ratingKey from remapper's replaceData if one exists.

    Used when a track was replaced in Plex (new ratingKey) but old cards still exist.
    The alternative key points to the current track in Plex.
    """
    if not _track_remapper_loaded:
        load_track_remapper()
    entry = _track_remapper.get(str(rating_key))
    if entry:
        return entry.get("ratingKey")
    return None


# Patterns to strip from titles (version/format info that doesn't affect song identity)
_TITLE_STRIP_PATTERNS = [
    r"\s*\(Extended Version\)",
    r"\s*\(\d{4}\s*-?\s*Remaster(?:ed)?\)",
    r"\s*\(Remaster(?:ed)?\)",
    r"\s*\(\d+(?:st|nd|rd|th) Anniversary Edition\)",
    r"\s*\(Mono\)",
    r"\s*\(Stereo\)",
    r"\s*\(Reworked\)",
    r"\s*\(Single Version\)",
    r"\s*\(Soundtrack Version\)",
    r"\s*\([^)]*Mix\)",
]

# Patterns that indicate problematic versions (should warn, not strip)
_TITLE_WARNING_PATTERNS = [
    (r"\(Instrumental\)", "Instrumental version"),
    (r"\(Live[^)]*\)", "Live version"),
]


def check_title_warnings(title: str) -> list[str]:
    """Check if title contains problematic version indicators. Returns list of warnings."""
    warnings = []
    for pattern, warning_msg in _TITLE_WARNING_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            warnings.append(warning_msg)
    return warnings


def normalize_title(title: str) -> str:
    """Remove version/format suffixes from title that don't affect song identity."""
    if not title:
        return title
    result = title
    for pattern in _TITLE_STRIP_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    return result.strip()


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


def extract_guids(track: dict) -> tuple[str | None, str | None]:
    """Extract Plex GUID and MusicBrainz ID from track metadata.

    Returns (plex_guid, musicbrainz_id) tuple.
    """
    # Plex GUID is a top-level attribute (e.g., "plex://track/...")
    plex_guid = track.get("guid")

    # MusicBrainz ID is in the Guid array (e.g., {"id": "mbid://..."})
    mbid = None
    for guid_entry in track.get("Guid", []):
        guid_id = guid_entry.get("id", "")
        if guid_id.startswith("mbid://"):
            mbid = guid_id[7:]  # Strip "mbid://" prefix
            break

    return plex_guid, mbid


def fetch_plex_track(server_url: str, token: str, rating_key: str, debug: bool = False) -> dict | None:
    """Fetch track metadata directly by ratingKey.

    If the remapper has an alternative ratingKey (replaceData.ratingKey), fetches from that
    instead but keeps the original ratingKey in the result, adding the alternative to
    alternativeKeys array. This allows old printed cards to work after tracks are replaced.

    Returns dict with track info including 'warnings' list if problematic version detected.
    """
    # Check if there's an alternative ratingKey in the remapper
    alternative_key = get_alternative_ratingkey(rating_key)
    fetch_key = alternative_key if alternative_key else rating_key

    try:
        url = f"{server_url}/library/metadata/{fetch_key}"
        if debug:
            if alternative_key:
                print(f"  DEBUG: Fetching: {url} (alternative for {rating_key})")
            else:
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
        # Apply remapper overrides using the ORIGINAL rating_key (not the fetch key)
        remapped_year = get_remapped_year(rating_key, plex_year)
        remapped_artist = get_remapped_artist(rating_key, plex_artist)
        remapped_title = get_remapped_title(rating_key, plex_title)

        # Check for problematic versions before normalizing
        warnings = check_title_warnings(remapped_title)

        # Normalize title (remove version suffixes)
        normalized_title = normalize_title(remapped_title)

        # Extract stable identifiers
        plex_guid, mbid = extract_guids(track)

        # Keep the ORIGINAL ratingKey (for printed cards), not the fetch key
        result = {
            "ratingKey": rating_key,
            "title": normalized_title,
            "artist": remapped_artist,
            "album": track.get("parentTitle"),
            "year": remapped_year,
            "duration": track.get("duration"),
            "partKey": parts.get("key"),
        }

        # Add alternativeKeys if we used a different key to fetch
        if alternative_key:
            result["alternativeKeys"] = [alternative_key]

        # Add stable identifiers if available
        if plex_guid:
            result["guid"] = plex_guid
        if mbid:
            result["mbid"] = mbid

        if warnings:
            result["warnings"] = warnings

        if debug:
            year_info = f"{result['year']}"
            if remapped_year != plex_year:
                year_info += f" (remapped from {plex_year})"
            artist_info = result['artist']
            if remapped_artist != plex_artist:
                artist_info += f" (remapped from {plex_artist})"
            title_info = result['title']
            if normalized_title != remapped_title:
                title_info += f" (normalized from {remapped_title})"
            elif remapped_title != plex_title:
                title_info += f" (remapped from {plex_title})"
            print(f"  DEBUG: Found: {artist_info} - {title_info} ({year_info})")
            if plex_guid:
                print(f"  DEBUG: GUID: {plex_guid}")
            if mbid:
                print(f"  DEBUG: MBID: {mbid}")
            if alternative_key:
                print(f"  DEBUG: Alternative key: {alternative_key}")

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
