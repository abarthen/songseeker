#!/usr/bin/env python3
"""
Create Plex Playlist from JSON Mapping File

Creates a Plex audio playlist from a SongSeeker mapping file.
This is the inverse of `custom-game --playlist` which exports a playlist to JSON.

Usage:
    poetry run create-playlist -i plex-mapping-de-custom.json -n "My Playlist"
"""

import argparse
import sys

import json5

from .plex_api import create_playlist, resolve_plex_credentials


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a Plex playlist from a JSON mapping file"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Input JSON mapping filename (resolved from files-path)"
    )
    parser.add_argument(
        "--name", "-n", required=True,
        help="Playlist name to create"
    )
    parser.add_argument(
        "--server", "-s",
        help="Plex server URL (default: from plex-config.json)"
    )
    parser.add_argument(
        "--token", "-t",
        help="Plex authentication token (default: from plex-config.json)"
    )
    parser.add_argument(
        "--config",
        help="Path to plex-config.json (default: ../plex-config.json)"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true",
        help="Enable debug output"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve Plex credentials from config file if not provided
    resolve_plex_credentials(args)

    # Normalize server URL
    server_url = args.server.rstrip("/")

    # Resolve input file path
    input_path = args.files_path / args.input
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    # Load the mapping file
    print(f"Loading mapping file: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        mapping = json5.load(f)

    # Extract rating keys from the track entries
    # Mapping structure: {cardId: {ratingKey: "...", title: "...", ...}}
    rating_keys = []
    for entry in mapping.values():
        if isinstance(entry, dict) and "ratingKey" in entry:
            rating_keys.append(entry["ratingKey"])

    if not rating_keys:
        print("Error: No tracks found in mapping file")
        sys.exit(1)

    print(f"Found {len(rating_keys)} tracks")

    # Create the playlist
    print(f"\nCreating playlist: {args.name}")
    playlist_key = create_playlist(
        server_url=server_url,
        token=args.token,
        title=args.name,
        rating_keys=rating_keys,
        debug=args.debug
    )

    if playlist_key:
        print(f"\nPlaylist created successfully!")
        print(f"  Name: {args.name}")
        print(f"  Tracks: {len(rating_keys)}")
        print(f"  Rating Key: {playlist_key}")
    else:
        print("\nFailed to create playlist")
        sys.exit(1)


if __name__ == "__main__":
    main()
