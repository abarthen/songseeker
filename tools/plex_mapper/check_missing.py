#!/usr/bin/env python3
"""
Quick script to find songs from a mapping that are missing in a playlist.
"""

import argparse
import json
from pathlib import Path

from .plex_api import (
    find_playlist,
    get_playlist_tracks,
    resolve_path,
    resolve_plex_credentials,
)


def main():
    parser = argparse.ArgumentParser(description="Find mapping songs missing from a playlist")
    parser.add_argument("--mapping", "-m", required=True, help="Mapping filename (e.g., plex-mapping-de.json)")
    parser.add_argument("--playlist", "-p", required=True, help="Playlist name or ratingKey")
    parser.add_argument("--server", "-s", help="Plex server URL")
    parser.add_argument("--token", "-t", help="Plex token")
    parser.add_argument("--config", help="Path to plex-config.json")
    args = parser.parse_args()

    # Load Plex config and resolve paths
    resolve_plex_credentials(args)
    server_url = args.server.rstrip("/")

    # Load mapping
    mapping_path = resolve_path(args, args.mapping)
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    mapping_keys = {track["ratingKey"] for track in mapping.values() if track}
    print(f"Loaded {len(mapping_keys)} tracks from mapping")

    # Get playlist tracks
    playlist_key, playlist_name, _ = find_playlist(server_url, args.token, args.playlist)
    playlist_keys = set(get_playlist_tracks(server_url, args.token, playlist_key))
    print(f"Playlist '{playlist_name}' has {len(playlist_keys)} tracks")

    # Find missing
    missing_keys = mapping_keys - playlist_keys
    print(f"\nMissing from playlist: {len(missing_keys)} tracks\n")

    if missing_keys:
        for card_id, track in mapping.items():
            if track and track["ratingKey"] in missing_keys:
                print(f"  {track['ratingKey']}: {track['artist']} - {track['title']} ({track.get('year', '?')})")


if __name__ == "__main__":
    main()
