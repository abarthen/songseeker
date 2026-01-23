#!/usr/bin/env python3
"""
Check Mappings for SongSeeker

Unified tool to verify that mapping files are valid:
- Check that all ratingKeys in mappings still exist in Plex
- Check that all mapping tracks exist in a specific playlist
- Automatically recover tracks that were previously missing but now exist

Usage:
    # Check ALL mappings in game-registry.json against Plex
    poetry run check-mappings

    # Check a specific mapping against Plex
    poetry run check-mappings -m plex-mapping-de.json

    # Check a mapping against a specific playlist
    poetry run check-mappings -m plex-mapping-de.json -p "My Playlist"

    # Mark missing tracks in mapping(s)
    poetry run check-mappings --fix
    poetry run check-mappings -m plex-mapping-de.json --fix

Note: --fix marks tracks with "missing": true instead of deleting them,
preserving metadata for re-matching. Tracks that were previously missing
but now exist are automatically recovered (missing flag removed).
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .plex_api import (
    find_playlist,
    get_playlist_tracks,
    load_plex_config,
    plex_request,
    resolve_path,
    resolve_plex_credentials,
    test_plex_connection,
)


def check_mapping_against_plex(
    server_url: str,
    token: str,
    mapping_path: Path,
    debug: bool = False,
    fix: bool = False,
    workers: int = 10,
) -> tuple[int, int]:
    """Check that all rating keys in a mapping file still exist in Plex.

    Uses parallel requests for speed.
    Returns (total_checked, missing_count).
    """
    if not mapping_path.exists():
        print(f"Error: Mapping file not found: {mapping_path}")
        return 0, 0

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    # Get all entries with rating keys
    entries_with_keys = [
        (card_id, entry)
        for card_id, entry in mapping.items()
        if entry is not None and entry.get("ratingKey")
    ]

    total = len(entries_with_keys)
    print(f"Checking {total} tracks in {mapping_path.name}...")

    def check_track(card_id: str, entry: dict) -> tuple[str, str, str, str, bool]:
        """Check if a single track exists. Returns (card_id, rating_key, artist, title, exists)."""
        rating_key = entry.get("ratingKey")
        artist = entry.get("artist", "Unknown")
        title = entry.get("title", "Unknown")

        try:
            url = f"{server_url}/library/metadata/{rating_key}"
            response = plex_request(url, token)
            metadata = response.get("MediaContainer", {}).get("Metadata", [])
            exists = bool(metadata)
        except Exception:
            exists = False

        return card_id, rating_key, artist, title, exists

    missing = []
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(check_track, card_id, entry): (card_id, entry)
            for card_id, entry in entries_with_keys
        }

        for future in as_completed(futures):
            card_id, rating_key, artist, title, exists = future.result()
            completed += 1

            if debug:
                status = "OK" if exists else "MISSING"
                print(f"  [{completed}/{total}] {rating_key}: {artist} - {title}... {status}")

            if not exists:
                missing.append((card_id, rating_key, artist, title))

    # Check for tracks that were previously missing but now exist
    recovered = []
    for card_id, entry in entries_with_keys:
        if entry.get("missing") and (card_id, entry.get("ratingKey"), entry.get("artist"), entry.get("title")) not in [(m[0], m[1], m[2], m[3]) for m in missing]:
            recovered.append(card_id)

    # Track if we need to save
    needs_save = False

    if missing:
        print(f"  MISSING: {len(missing)} tracks")
        for card_id, rating_key, artist, title in missing:
            print(f"    Card #{card_id}: {artist} - {title} (ratingKey: {rating_key})")

        if fix:
            for card_id, _, _, _ in missing:
                mapping[card_id]["missing"] = True
            needs_save = True
            print(f"  Fixed: marked {len(missing)} tracks as missing")
    else:
        print("  All tracks exist in Plex!")

    # Remove missing flag from recovered tracks
    if recovered:
        print(f"  RECOVERED: {len(recovered)} tracks (previously missing, now exist)")
        for card_id in recovered:
            if "missing" in mapping[card_id]:
                del mapping[card_id]["missing"]
        needs_save = True

    # Save once if any changes were made
    if needs_save:
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)

    return total, len(missing)


def check_mapping_against_playlist(
    server_url: str, token: str, mapping_path: Path, playlist_name: str, debug: bool = False
) -> tuple[int, int]:
    """Check that all tracks in a mapping exist in a playlist.

    Returns (total_checked, missing_count).
    """
    if not mapping_path.exists():
        print(f"Error: Mapping file not found: {mapping_path}")
        return 0, 0

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    mapping_keys = {
        track["ratingKey"]: (card_id, track)
        for card_id, track in mapping.items()
        if track and track.get("ratingKey")
    }
    print(f"Loaded {len(mapping_keys)} tracks from {mapping_path.name}")

    # Get playlist tracks
    playlist_key, playlist_title, _ = find_playlist(server_url, token, playlist_name, debug)
    playlist_keys = set(get_playlist_tracks(server_url, token, playlist_key, debug))
    print(f"Playlist '{playlist_title}' has {len(playlist_keys)} tracks")

    # Find missing
    missing_keys = set(mapping_keys.keys()) - playlist_keys

    if missing_keys:
        print(f"\nMissing from playlist: {len(missing_keys)} tracks")
        for key in missing_keys:
            card_id, track = mapping_keys[key]
            print(
                f"  Card #{card_id}: {track['artist']} - {track['title']} ({track.get('year', '?')})"
            )
    else:
        print("\nAll mapping tracks exist in playlist!")

    return len(mapping_keys), len(missing_keys)


def load_game_registry(config: dict) -> dict[str, str]:
    """Load game registry from config."""
    registry_path = config.get("game_registry_path")
    if not registry_path:
        print("Error: game-registry-filename not set in plex-config.json")
        sys.exit(1)

    if not registry_path.exists():
        print(f"Error: Game registry not found: {registry_path}")
        sys.exit(1)

    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check mapping files against Plex or a playlist"
    )

    parser.add_argument(
        "--mapping",
        "-m",
        help="Mapping filename (e.g., plex-mapping-de.json). If not specified, checks all mappings in game-registry.json",
    )
    parser.add_argument(
        "--playlist",
        "-p",
        help="Playlist name or ratingKey to check against (requires --mapping)",
    )
    parser.add_argument(
        "--fix",
        "-f",
        action="store_true",
        help="Mark missing tracks with 'missing' property. Only works for Plex checks, not playlist checks.",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=10,
        help="Number of parallel workers (default: 10)",
    )
    parser.add_argument(
        "--server", "-s", help="Plex server URL (default: from plex-config.json)"
    )
    parser.add_argument(
        "--token", "-t", help="Plex authentication token (default: from plex-config.json)"
    )
    parser.add_argument(
        "--config", help="Path to plex-config.json (default: ../plex-config.json)"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Show detailed progress for each track"
    )

    args = parser.parse_args()

    # Validate: --playlist requires --mapping
    if args.playlist and not args.mapping:
        parser.error("--playlist requires --mapping")

    # Validate: --fix doesn't work with --playlist
    if args.fix and args.playlist:
        parser.error("--fix only works for Plex checks, not playlist checks")

    return args


def main():
    args = parse_args()

    # Resolve Plex credentials and file paths from config
    resolve_plex_credentials(args)
    server_url = args.server.rstrip("/")

    # Load config for game registry
    config_path = (
        Path(args.config)
        if args.config
        else Path(__file__).parent.parent.parent / "plex-config.json"
    )
    config = load_plex_config(config_path)

    # Test connection
    test_plex_connection(server_url, args.token)
    print()

    if args.playlist:
        # Check single mapping against playlist
        mapping_path = resolve_path(args, args.mapping)
        check_mapping_against_playlist(
            server_url, args.token, mapping_path, args.playlist, args.debug
        )

    elif args.mapping:
        # Check single mapping against Plex
        mapping_path = resolve_path(args, args.mapping)
        total, missing = check_mapping_against_plex(
            server_url, args.token, mapping_path, args.debug, args.fix, args.workers
        )

        print(f"\n{'=' * 50}")
        print(f"Check complete: {total} tracks checked, {missing} missing")
        if args.fix and missing > 0:
            print("\nHint: Run 'poetry run update-manifest' to update the manifest.")

    else:
        # Check all mappings in game-registry.json against Plex
        game_registry = load_game_registry(config)
        files_path = config.get("files_path")

        if not files_path:
            print("Error: files-path not set in plex-config.json")
            sys.exit(1)

        print(f"Checking {len(game_registry)} mappings from game-registry.json...\n")

        total_checked = 0
        total_missing = 0
        mappings_with_issues = []

        for mapping_id in game_registry.keys():
            mapping_path = files_path / f"plex-mapping-{mapping_id}.json"

            if not mapping_path.exists():
                print(f"Skipping {mapping_id}: file not found")
                continue

            checked, missing = check_mapping_against_plex(
                server_url, args.token, mapping_path, args.debug, args.fix, args.workers
            )
            total_checked += checked
            total_missing += missing

            if missing > 0:
                mappings_with_issues.append((mapping_id, missing))

            print()  # Blank line between mappings

        # Summary
        print("=" * 50)
        print(f"Check complete: {len(game_registry)} mappings, {total_checked} tracks total")
        if mappings_with_issues:
            print(f"\nMappings with missing tracks:")
            for mapping_id, missing in mappings_with_issues:
                print(f"  {mapping_id}: {missing} missing")
            print(f"\nTotal missing: {total_missing}")
            if args.fix:
                print("\nHint: Run 'poetry run update-manifest' to update the manifest.")
        else:
            print("\nAll tracks exist in Plex!")


if __name__ == "__main__":
    main()
