"""
Shared Plex API utilities for SongSeeker tools.

This module provides common functions for interacting with Plex servers,
used by both plex-mapper and custom-game tools.
"""

import json
import re
import sys
from pathlib import Path

import json5
import requests


def normalize_for_comparison(text: str) -> str:
    """Normalize text for fuzzy comparison by removing spaces, punctuation, and lowercasing."""
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Normalize & to and (before removing spaces)
    text = text.replace(" & ", " and ").replace("&", " and ")
    # Remove common punctuation and spaces
    text = re.sub(r"[\s\-_'.,:;!?]+", "", text)
    # Remove accents (basic normalization)
    text = text.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    text = text.replace("é", "e").replace("è", "e").replace("ê", "e")
    text = text.replace("á", "a").replace("à", "a").replace("â", "a")
    text = text.replace("ó", "o").replace("ò", "o").replace("ô", "o")
    text = text.replace("ú", "u").replace("ù", "u").replace("û", "u")
    text = text.replace("ñ", "n").replace("ß", "ss")
    # Ligatures
    text = text.replace("æ", "ae").replace("œ", "oe")
    return text


def resolve_plex_credentials(args, config_attr: str = "config") -> None:
    """Load Plex credentials and file paths from config file.

    Modifies args in-place to set:
    - server: Plex server URL
    - token: Plex authentication token
    - files_path: Base directory for all mapping files
    - csv_files_path: Directory for CSV files (defaults to files_path)
    - remapper_path: Full path to remapper JSON
    - manifest_path: Full path to manifest JSON

    Args:
        args: Parsed arguments object with server, token, and config attributes
        config_attr: Name of the config path attribute on args (default: "config")
    """
    config_value = getattr(args, config_attr, None)
    config_path = Path(config_value) if config_value else Path(__file__).parent.parent.parent / "plex-config.json"
    config = load_plex_config(config_path)

    # Set server/token from config if not provided
    if not getattr(args, "server", None):
        args.server = config.get("serverUrl")
    if not getattr(args, "token", None):
        args.token = config.get("token")

    # Set file paths from config
    args.files_path = config.get("files_path")
    args.csv_files_path = config.get("csv_files_path")
    args.remapper_path = config.get("remapper_path")
    args.manifest_path = config.get("manifest_path")

    # Validate we have required values
    if not args.server or not args.token:
        print("Error: Plex server and token are required.")
        print("Either provide --server and --token, or create plex-config.json")
        sys.exit(1)

    if not args.files_path:
        print("Error: files-path is required in plex-config.json")
        sys.exit(1)


def resolve_path(args, filename: str) -> Path:
    """Resolve a filename to full path using files_path from config.

    Args:
        args: Parsed arguments with files_path attribute
        filename: Filename (not path) to resolve

    Returns:
        Full Path object
    """
    return args.files_path / filename


def test_plex_connection(server_url: str, token: str, test_search: bool = False) -> dict:
    """Test connection to Plex server and optionally test search API.

    Args:
        server_url: Plex server URL
        token: Plex authentication token
        test_search: If True, also test the search API

    Returns:
        Server info dict with 'friendlyName' and 'version'

    Raises:
        SystemExit: If connection fails
    """
    print(f"Testing Plex connection: {server_url}")
    try:
        server_info = plex_request(f"{server_url}/", token)
        container = server_info.get("MediaContainer", {})
        print(f"Plex connection successful!")
        print(f"  Server: {container.get('friendlyName', 'Unknown')}")
        print(f"  Version: {container.get('version', 'Unknown')}")
    except Exception as e:
        print(f"Error: Cannot connect to Plex server: {e}")
        sys.exit(1)

    if test_search:
        print("\nTesting Plex search API...")
        try:
            test_result = plex_request(f"{server_url}/search?query=test&type=10", token)
            size = test_result.get("MediaContainer", {}).get("size", 0)
            print(f"Search API working! (Found {size} results for 'test')")
        except Exception as e:
            print(f"Warning: Search API test failed: {e}")

    return container


def find_playlist(server_url: str, token: str, playlist_name_or_key: str, debug: bool = False) -> tuple[str, str, int] | None:
    """Find a playlist by name or ratingKey.

    Args:
        server_url: Plex server URL
        token: Plex authentication token
        playlist_name_or_key: Playlist name (case-insensitive) or ratingKey
        debug: Enable debug output

    Returns:
        Tuple of (ratingKey, title, trackCount) if found, None otherwise.
        Prints available playlists and exits if not found.
    """
    playlists = list_plex_playlists(server_url, token, debug)

    for pl in playlists:
        if pl['ratingKey'] == playlist_name_or_key or pl['title'].lower() == playlist_name_or_key.lower():
            print(f"Found playlist: {pl['title']} ({pl['leafCount']} tracks)")
            return pl['ratingKey'], pl['title'], pl['leafCount']

    print(f"Error: Playlist '{playlist_name_or_key}' not found")
    print("\nAvailable playlists:")
    for pl in playlists:
        print(f"  {pl['ratingKey']}: {pl['title']}")
    sys.exit(1)

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
            data = json5.load(f)

        # Check for duplicate ratingKeys
        seen_keys: dict[str, int] = {}  # ratingKey -> first occurrence index
        duplicates: list[tuple[str, int, int]] = []  # (ratingKey, first_index, duplicate_index)
        for idx, entry in enumerate(data):
            rating_key = entry.get("ratingKey")
            if rating_key:
                key_str = str(rating_key)
                if key_str in seen_keys:
                    duplicates.append((key_str, seen_keys[key_str], idx))
                else:
                    seen_keys[key_str] = idx

        if duplicates:
            print(f"Error: Duplicate ratingKeys found in {remapper_path.name}:")
            for key, first_idx, dup_idx in duplicates:
                print(f"  ratingKey {key}: entries at index {first_idx} and {dup_idx}")
            sys.exit(1)

        # Validate that all ratingKeys are strings (not numbers)
        non_string_keys: list[tuple[int, str, object]] = []
        for idx, entry in enumerate(data):
            rating_key = entry.get("ratingKey")
            if rating_key is not None and not isinstance(rating_key, str):
                non_string_keys.append((idx, "ratingKey", rating_key))
            replace_key = entry.get("replaceData", {}).get("ratingKey")
            if replace_key is not None and not isinstance(replace_key, str):
                non_string_keys.append((idx, "replaceData.ratingKey", replace_key))

        if non_string_keys:
            print(f"Error: Non-string ratingKeys found in {remapper_path.name}:")
            for idx, field, value in non_string_keys:
                print(f"  Entry {idx}: {field} = {value} ({type(value).__name__}, should be string)")
            sys.exit(1)

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
        print(f"Error: Could not load track remapper from {remapper_path}: {e}")
        print("  The remapper file will be ignored. Fix the syntax error and try again.")
        _track_remapper_loaded = True
        return _track_remapper


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

    Used to support old printed cards that have a different ratingKey.
    The alternative key is added to alternativeKeys so the website can look up
    tracks by either the current or old ratingKey.
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


def load_plex_config(config_path: Path) -> dict:
    """Load full config from plex-config.json.

    Returns dict with keys: serverUrl, token, files_path, csv_files_path, remapper_path,
    manifest_path, game_registry_path
    """
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        result = {
            "serverUrl": config.get("serverUrl"),
            "token": config.get("token"),
        }

        # Resolve file paths
        files_path = config.get("files-path")
        if files_path:
            files_path = Path(files_path)
            result["files_path"] = files_path

            remapper_filename = config.get("remapper-filename")
            if remapper_filename:
                result["remapper_path"] = files_path / remapper_filename

            manifest_filename = config.get("manifest-filename")
            if manifest_filename:
                result["manifest_path"] = files_path / manifest_filename

            game_registry_filename = config.get("game-registry-filename")
            if game_registry_filename:
                result["game_registry_path"] = files_path / game_registry_filename

        # CSV files can be in a separate directory
        csv_files_path = config.get("csv-files-path")
        if csv_files_path:
            result["csv_files_path"] = Path(csv_files_path)
        elif files_path:
            # Fall back to files_path if csv-files-path not specified
            result["csv_files_path"] = files_path

        return result
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read config file: {e}")
        return {}


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

    If the remapper has an alternative ratingKey (replaceData.ratingKey), it will be added
    to alternativeKeys array so old cards with that key still work on the website.

    Returns dict with track info including 'warnings' list if problematic version detected.
    """
    # Check if there's an alternative ratingKey in the remapper (for old cards)
    alternative_key = get_alternative_ratingkey(rating_key)

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

        result = {
            "ratingKey": rating_key,
            "title": normalized_title,
            "artist": remapped_artist,
            "album": track.get("parentTitle"),
            "year": remapped_year,
            "duration": track.get("duration"),
            "partKey": parts.get("key"),
        }

        # Add alternativeKeys from remapper (for old cards that have different ratingKey)
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


def get_machine_identifier(server_url: str, token: str, debug: bool = False) -> str | None:
    """Get the machine identifier from the Plex server.

    Required for creating playlists via the API.
    """
    try:
        response = plex_request(f"{server_url}/", token)
        machine_id = response.get("MediaContainer", {}).get("machineIdentifier")
        if debug:
            print(f"  DEBUG: Machine identifier: {machine_id}")
        return machine_id
    except Exception as e:
        if debug:
            print(f"  DEBUG: Error getting machine identifier: {e}")
        return None


def create_playlist(
    server_url: str,
    token: str,
    title: str,
    rating_keys: list[str],
    machine_id: str = None,
    debug: bool = False
) -> str | None:
    """Create a new Plex audio playlist with the given tracks.

    Args:
        server_url: Plex server URL
        token: Plex authentication token
        title: Playlist title
        rating_keys: List of track rating keys to add
        machine_id: Server machine identifier (fetched automatically if not provided)
        debug: Enable debug output

    Returns:
        The new playlist's ratingKey on success, None on failure.
    """
    if not rating_keys:
        print("Error: No rating keys provided")
        return None

    # Get machine identifier if not provided
    if not machine_id:
        machine_id = get_machine_identifier(server_url, token, debug)
        if not machine_id:
            print("Error: Could not get server machine identifier")
            return None

    try:
        # Build the URI for the tracks
        keys_str = ",".join(str(k) for k in rating_keys)
        uri = f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{keys_str}"

        # Create the playlist
        url = f"{server_url}/playlists"
        headers = {"Accept": "application/json"}
        params = {
            "X-Plex-Token": token,
            "type": "audio",
            "title": title,
            "smart": "0",
            "uri": uri,
        }

        if debug:
            print(f"  DEBUG: Creating playlist: POST {url}")
            print(f"  DEBUG: Title: {title}")
            print(f"  DEBUG: Tracks: {len(rating_keys)}")

        response = requests.post(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        result = response.json()
        playlist = result.get("MediaContainer", {}).get("Metadata", [{}])[0]
        playlist_key = playlist.get("ratingKey")

        if debug:
            print(f"  DEBUG: Created playlist with ratingKey: {playlist_key}")

        return playlist_key

    except Exception as e:
        if debug:
            print(f"  DEBUG: Error creating playlist: {e}")
        print(f"Error: Failed to create playlist: {e}")
        return None
