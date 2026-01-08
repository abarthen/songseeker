#!/usr/bin/env python3
"""
Mapping Tools for SongSeeker

Operations that work directly on plex-mapping-*.json files without needing
the original CSV or playlist source.

Commands:
    --check     Verify all ratingKeys still exist in Plex
    --fix       Used with --check to remove missing tracks
    --enrich    Re-fetch metadata for all tracks (adds guid, mbid, alternativeKeys, etc.)

Usage:
    poetry run mapping-tools --check --mapping plex-mapping-de.json
    poetry run mapping-tools --check --fix --mapping plex-mapping-de.json
    poetry run mapping-tools --enrich --mapping plex-mapping-de.json
"""

import argparse
import json
import sys
from pathlib import Path

from .plex_api import (
    fetch_plex_track,
    load_track_remapper,
    plex_request,
    resolve_path,
    resolve_plex_credentials,
    test_plex_connection,
)


def check_mapping(server_url: str, token: str, mapping_path: Path, debug: bool = False, fix: bool = False) -> None:
    """Check that all rating keys in a mapping file still exist in Plex."""
    if not mapping_path.exists():
        print(f"Error: Mapping file not found: {mapping_path}")
        sys.exit(1)

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    # Get all entries with rating keys
    entries_with_keys = [(card_id, entry) for card_id, entry in mapping.items()
                         if entry is not None and entry.get("ratingKey")]

    print(f"Checking {len(entries_with_keys)} tracks in {mapping_path.name}...\n")

    missing = []
    for i, (card_id, entry) in enumerate(entries_with_keys):
        rating_key = entry.get("ratingKey")
        artist = entry.get("artist", "Unknown")
        title = entry.get("title", "Unknown")

        if debug:
            print(f"[{i + 1}/{len(entries_with_keys)}] Checking {rating_key}: {artist} - {title}... ", end="", flush=True)

        try:
            url = f"{server_url}/library/metadata/{rating_key}"
            response = plex_request(url, token)
            metadata = response.get("MediaContainer", {}).get("Metadata", [])
            if metadata:
                if debug:
                    print("OK")
            else:
                if debug:
                    print("MISSING")
                missing.append((card_id, rating_key, artist, title))
        except Exception as e:
            if debug:
                print(f"MISSING ({e})")
            missing.append((card_id, rating_key, artist, title))

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Check complete: {len(entries_with_keys)} tracks checked")
    if missing:
        print(f"\nMISSING TRACKS ({len(missing)}):")
        for card_id, rating_key, artist, title in missing:
            print(f"  Card #{card_id}: {artist} - {title} (ratingKey: {rating_key})")

        if fix:
            # Remove missing entries from mapping
            for card_id, _, _, _ in missing:
                mapping[card_id] = None
            with open(mapping_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, indent=2)
            print(f"\nRemoved {len(missing)} missing tracks from mapping.")
        else:
            print(f"\nUse --fix to remove these tracks from the mapping.")
    else:
        print("All tracks exist in Plex!")
    print("=" * 50)


def enrich_mapping(server_url: str, token: str, mapping_path: Path, debug: bool = False) -> None:
    """Re-fetch metadata for all tracks in a mapping file using their existing ratingKey.

    This updates tracks with:
    - guid and mbid (stable identifiers)
    - alternativeKeys (from remapper, for old cards)
    - Any metadata changes (year, artist, title from remapper)
    """
    if not mapping_path.exists():
        print(f"Error: Mapping file not found: {mapping_path}")
        sys.exit(1)

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    # Get all entries with rating keys
    entries_with_keys = [(card_id, entry) for card_id, entry in mapping.items()
                         if entry is not None and entry.get("ratingKey")]

    print(f"Enriching {len(entries_with_keys)} tracks in {mapping_path.name}...\n")

    enriched = 0
    missing = 0
    unchanged = 0

    for i, (card_id, entry) in enumerate(entries_with_keys):
        rating_key = entry.get("ratingKey")
        old_artist = entry.get("artist", "Unknown")
        old_title = entry.get("title", "Unknown")

        if debug:
            print(f"[{i + 1}/{len(entries_with_keys)}] Fetching {rating_key}: {old_artist} - {old_title}... ", end="", flush=True)

        new_track = fetch_plex_track(server_url, token, rating_key, debug=False)

        if new_track:
            # Check what changed
            changes = []
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

            mapping[card_id] = new_track

            if changes:
                enriched += 1
                if debug:
                    print(f"UPDATED ({', '.join(changes)})")
                else:
                    print(f"[{i + 1}/{len(entries_with_keys)}] {old_artist} - {old_title}: UPDATED ({', '.join(changes)})")
            else:
                unchanged += 1
                if debug:
                    print("unchanged")
        else:
            missing += 1
            if debug:
                print("MISSING")
            else:
                print(f"[{i + 1}/{len(entries_with_keys)}] {old_artist} - {old_title}: MISSING (ratingKey: {rating_key})")

    # Write updated mapping
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Enrich complete: {len(entries_with_keys)} tracks processed")
    print(f"  Updated:   {enriched}")
    print(f"  Unchanged: {unchanged}")
    print(f"  Missing:   {missing}")
    print(f"\nMapping saved to: {mapping_path}")
    print("=" * 50)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tools for working with plex-mapping-*.json files"
    )

    # Required: mapping filename
    parser.add_argument(
        "--mapping", "-m", required=True,
        help="Mapping filename (e.g., plex-mapping-de.json)"
    )

    # Operations (mutually exclusive)
    ops = parser.add_mutually_exclusive_group(required=True)
    ops.add_argument(
        "--check", "-c", action="store_true",
        help="Verify all ratingKeys still exist in Plex"
    )
    ops.add_argument(
        "--enrich", "-e", action="store_true",
        help="Re-fetch metadata for all tracks (adds guid, mbid, alternativeKeys)"
    )

    # Modifiers
    parser.add_argument(
        "--fix", "-f", action="store_true",
        help="With --check: remove missing tracks from mapping"
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
        "--debug", "-d", action="store_true",
        help="Show detailed progress for each track"
    )

    args = parser.parse_args()

    # Validate --fix requires --check
    if args.fix and not args.check:
        parser.error("--fix requires --check")

    return args


def main():
    args = parse_args()

    # Resolve Plex credentials and file paths from config
    resolve_plex_credentials(args)
    server_url = args.server.rstrip("/")

    # Test connection
    test_plex_connection(server_url, args.token)
    print()

    # Resolve mapping path
    mapping_path = resolve_path(args, args.mapping)

    if args.check:
        check_mapping(server_url, args.token, mapping_path, args.debug, args.fix)

    elif args.enrich:
        # Load remapper from config path
        load_track_remapper(args.remapper_path)
        enrich_mapping(server_url, args.token, mapping_path, args.debug)


if __name__ == "__main__":
    main()
