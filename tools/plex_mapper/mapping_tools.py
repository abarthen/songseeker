#!/usr/bin/env python3
"""
Mapping Tools for SongSeeker

Operations that work directly on plex-mapping-*.json files without needing
the original CSV or playlist source.

Commands:
    --enrich    Re-fetch metadata for all tracks (adds guid, mbid, alternativeKeys, etc.)

Usage:
    poetry run mapping-tools --enrich --mapping plex-mapping-de.json
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import json5

from .plex_api import (
    fetch_plex_track,
    load_plex_config,
    load_track_remapper,
    resolve_path,
    resolve_plex_credentials,
    test_plex_connection,
)


def enrich_mapping(
    server_url: str, token: str, mapping_path: Path, debug: bool = False, workers: int = 10
) -> None:
    """Re-fetch metadata for all tracks in a mapping file using their existing ratingKey.

    This updates tracks with:
    - guid and mbid (stable identifiers)
    - alternativeKeys (from remapper, for old cards)
    - Any metadata changes (year, artist, title from remapper)

    Uses parallel requests for speed (configurable via workers parameter).
    """
    if not mapping_path.exists():
        print(f"Error: Mapping file not found: {mapping_path}")
        sys.exit(1)

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json5.load(f)

    # Report unmatched entries (null values)
    unmatched = [card_id for card_id, entry in mapping.items() if entry is None]
    if unmatched:
        print(f"UNMATCHED: {len(unmatched)} cards have no mapping: {', '.join(f'#{c}' for c in unmatched)}\n")

    # Get all entries with rating keys
    entries_with_keys = [
        (card_id, entry)
        for card_id, entry in mapping.items()
        if entry is not None and entry.get("ratingKey")
    ]

    total = len(entries_with_keys)
    print(f"Enriching {total} tracks in {mapping_path.name} ({workers} parallel workers)...\n")

    enriched = 0
    missing = 0
    unchanged = 0
    recovered = 0

    def fetch_track(card_id: str, entry: dict) -> tuple[str, dict | None, dict, list[str]]:
        """Fetch a single track and return (card_id, new_track, old_entry, changes)."""
        rating_key = entry.get("ratingKey")
        new_track = fetch_plex_track(server_url, token, rating_key, debug=False)

        changes = []
        if new_track:
            if new_track.get("guid") and not entry.get("guid"):
                changes.append("guid")
            if new_track.get("mbid") and not entry.get("mbid"):
                changes.append("mbid")
            if new_track.get("alternativeKeys") and not entry.get("alternativeKeys"):
                changes.append(f"alternativeKeys: {new_track['alternativeKeys']}")
            if new_track.get("year") != entry.get("year"):
                changes.append(f"year:{entry.get('year')}->{new_track.get('year')}")
            if new_track.get("artist") != entry.get("artist"):
                changes.append("artist")
            if new_track.get("title") != entry.get("title"):
                changes.append("title")
            if new_track.get("partKey") != entry.get("partKey"):
                changes.append("partKey")

        return card_id, new_track, entry, changes

    # Process tracks in parallel
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_track, card_id, entry): (card_id, entry)
            for card_id, entry in entries_with_keys
        }

        for future in as_completed(futures):
            card_id, new_track, old_entry, changes = future.result()
            completed += 1
            old_artist = old_entry.get("artist", "Unknown")
            old_title = old_entry.get("title", "Unknown")
            rating_key = old_entry.get("ratingKey")

            if new_track:
                # Remove missing flag if track was previously marked as missing
                was_missing = old_entry.get("missing", False)
                mapping[card_id] = new_track
                if was_missing:
                    recovered += 1
                    changes.append("recovered (was missing)")
                if changes:
                    enriched += 1
                    if debug:
                        print(
                            f"[{completed}/{total}] {old_artist} - {old_title}: UPDATED ({', '.join(changes)})"
                        )
                    else:
                        print(
                            f"[{completed}/{total}] UPDATED: {old_artist} - {old_title} ({', '.join(changes)})"
                        )
                else:
                    unchanged += 1
                    if debug:
                        print(f"[{completed}/{total}] {old_artist} - {old_title}: unchanged")
            else:
                missing += 1
                print(
                    f"[{completed}/{total}] MISSING: {old_artist} - {old_title} (ratingKey: {rating_key})"
                )

    # Write updated mapping
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Enrich complete: {total} tracks processed")
    print(f"  Updated:   {enriched}")
    print(f"  Unchanged: {unchanged}")
    print(f"  Missing:   {missing}")
    if recovered > 0:
        print(f"  Recovered: {recovered} (previously missing, now found)")
    print(f"\nMapping saved to: {mapping_path}")
    print("=" * 50)
    if enriched > 0:
        print("\nHint: Run 'poetry run update-manifest' to update the manifest.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tools for working with plex-mapping-*.json files"
    )

    # Optional: mapping filename (if omitted, processes all from game-registry.json)
    parser.add_argument(
        "--mapping", "-m",
        help="Mapping filename (e.g., plex-mapping-de.json). If omitted, processes all in game-registry.json",
    )

    # Operations
    parser.add_argument(
        "--enrich",
        "-e",
        action="store_true",
        required=True,
        help="Re-fetch metadata for all tracks (adds guid, mbid, alternativeKeys)",
    )

    # Plex connection (optional overrides)
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
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=10,
        help="Number of parallel workers for --enrich (default: 10)",
    )

    return parser.parse_args()


def load_game_registry(config: dict) -> dict[str, dict]:
    """Load game registry from config.

    Supports both formats:
    - New: {"de": {"name": "Hitster Deutschland", "playlist": "Hitster DE"}}
    - Legacy: {"de": "Hitster Deutschland"}

    Returns dict of mapping_id -> {"name": str, ...}.
    """
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


def main():
    args = parse_args()

    # Resolve Plex credentials and file paths from config
    resolve_plex_credentials(args)
    server_url = args.server.rstrip("/")

    # Test connection
    test_plex_connection(server_url, args.token)
    print()

    # Load remapper from config path
    load_track_remapper(args.remapper_path)

    if args.mapping:
        # Single mapping
        mapping_path = resolve_path(args, args.mapping)
        enrich_mapping(server_url, args.token, mapping_path, args.debug, args.workers)
    else:
        # All mappings from game-registry.json
        config_path = (
            Path(args.config)
            if getattr(args, "config", None)
            else Path(__file__).parent.parent.parent / "plex-config.json"
        )
        config = load_plex_config(config_path)
        game_registry = load_game_registry(config)
        files_path = config.get("files_path")

        if not files_path:
            print("Error: files-path not set in plex-config.json")
            sys.exit(1)

        print(f"Enriching {len(game_registry)} mappings from game-registry.json...\n")

        for mapping_id in game_registry.keys():
            mapping_path = files_path / f"plex-mapping-{mapping_id}.json"

            if not mapping_path.exists():
                print(f"Skipping {mapping_id}: file not found")
                continue

            enrich_mapping(server_url, args.token, mapping_path, args.debug, args.workers)
            print()


if __name__ == "__main__":
    main()
