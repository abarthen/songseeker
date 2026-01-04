"""
Shared Plex API utilities for SongSeeker tools.

This module provides common functions for interacting with Plex servers,
used by both plex-mapper and custom-game tools.
"""

import json
from pathlib import Path

import requests


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

        result = {
            "ratingKey": track.get("ratingKey"),
            "title": track.get("title"),
            "artist": track.get("grandparentTitle") or track.get("originalTitle"),
            "album": track.get("parentTitle"),
            "year": track.get("parentYear") or track.get("year"),
            "duration": track.get("duration"),
            "partKey": parts.get("key"),
        }

        if debug:
            print(f"  DEBUG: Found: {result['artist']} - {result['title']} ({result['year']})")

        return result

    except Exception as e:
        if debug:
            print(f"  DEBUG: Error fetching track: {e}")
        return None
