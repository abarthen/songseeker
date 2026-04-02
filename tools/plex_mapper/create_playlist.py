#!/usr/bin/env python3
"""
Create Plex Playlist from JSON Mapping File

Creates a Plex audio playlist from a SongSeeker mapping file.
This is the inverse of `custom-game --playlist` which exports a playlist to JSON.

Usage:
    # Create a single playlist
    poetry run create-playlist -i plex-mapping-de-custom.json -n "My Playlist"

    # Create all playlists that have a "playlist" property in game-registry.json
    poetry run create-playlist --all
"""

import argparse
import sys
from pathlib import Path

import json5

from .plex_api import create_playlist, load_plex_config, resolve_plex_credentials


def load_game_registry(config: dict) -> dict[str, dict]:
    """Load game registry from config."""
    registry_path = config.get("game_registry_path")
    if not registry_path:
        print("Error: game-registry-filename not set in plex-config.json")
        sys.exit(1)

    if not registry_path.exists():
        print(f"Error: Game registry not found: {registry_path}")
        sys.exit(1)

    with open(registry_path, "r", encoding="utf-8") as f:
        raw = json5.load(f)

    registry = {}
    for key, value in raw.items():
        if isinstance(value, str):
            registry[key] = {"name": value}
        else:
            registry[key] = value
    return registry


def create_playlist_from_mapping(
    server_url: str, token: str, mapping_path: Path, playlist_name: str, debug: bool = False
) -> bool:
    """Load a mapping file and create a Plex playlist from it. Returns True on success."""
    if not mapping_path.exists():
        print(f"  Error: File not found: {mapping_path}")
        return False

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json5.load(f)

    rating_keys = []
    for entry in mapping.values():
        if isinstance(entry, dict) and "ratingKey" in entry:
            rating_keys.append(entry["ratingKey"])

    if not rating_keys:
        print(f"  Error: No tracks found in {mapping_path.name}")
        return False

    print(f"  {len(rating_keys)} tracks -> playlist \"{playlist_name}\"")

    playlist_key = create_playlist(
        server_url=server_url,
        token=token,
        title=playlist_name,
        rating_keys=rating_keys,
        debug=debug
    )

    if playlist_key:
        print(f"  Created (ratingKey: {playlist_key})")
        return True
    else:
        print(f"  Failed to create playlist")
        return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a Plex playlist from a JSON mapping file"
    )
    parser.add_argument(
        "--input", "-i",
        help="Input JSON mapping filename (resolved from files-path)"
    )
    parser.add_argument(
        "--name", "-n",
        help="Playlist name to create (required with --input)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Create playlists for all entries with 'playlist' in game-registry.json"
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

    args = parser.parse_args()

    if not args.all and not args.input:
        parser.error("Either --input or --all is required")
    if args.input and not args.name:
        parser.error("--name is required with --input")
    if args.all and args.input:
        parser.error("--all and --input are mutually exclusive")

    return args


def main():
    args = parse_args()

    # Resolve Plex credentials from config file if not provided
    resolve_plex_credentials(args)

    # Normalize server URL
    server_url = args.server.rstrip("/")

    if args.all:
        config_path = (
            Path(args.config)
            if args.config
            else Path(__file__).parent.parent.parent / "plex-config.json"
        )
        config = load_plex_config(config_path)
        game_registry = load_game_registry(config)
        files_path = config.get("files_path")

        if not files_path:
            print("Error: files-path not set in plex-config.json")
            sys.exit(1)

        entries_with_playlist = {
            k: v for k, v in game_registry.items() if v.get("playlist")
        }

        if not entries_with_playlist:
            print("No entries with 'playlist' property found in game-registry.json")
            sys.exit(1)

        print(f"Creating {len(entries_with_playlist)} playlists from game-registry.json\n")

        created = 0
        for mapping_id, info in entries_with_playlist.items():
            mapping_path = files_path / f"plex-mapping-{mapping_id}.json"
            playlist_name = info["playlist"]
            print(f"[{mapping_id}]")
            if create_playlist_from_mapping(server_url, args.token, mapping_path, playlist_name, args.debug):
                created += 1
            print()

        print(f"Done: {created}/{len(entries_with_playlist)} playlists created")

    else:
        # Single playlist
        input_path = args.files_path / args.input
        print(f"Loading mapping file: {input_path}")
        if create_playlist_from_mapping(server_url, args.token, input_path, args.name, args.debug):
            print(f"\nPlaylist created successfully!")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
