#!/usr/bin/env python3
"""
Lock Years in Remapper for SongSeeker

Writes the year from each track in a mapping JSON file into plex-remapper.json.
This prevents Plex metadata changes from altering the year shown on cards.

For official games, run compare-mapping first to verify years match the CSV,
then run this tool. For custom games (no CSV), run this directly.

Usage:
    # Lock years for a mapping file
    poetry run lock-years -m plex-mapping-de-aaaa0039.json

    # Dry run (show what would be done)
    poetry run lock-years -m plex-mapping-de-aaaa0039.json --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

import json5

from .plex_api import load_plex_config, resolve_path


def lock_years(mapping: dict, remapper_path: Path, dry_run: bool = False) -> None:
    """Write all mapping years into plex-remapper.json."""
    # Load existing remapper
    if remapper_path.exists():
        with open(remapper_path, "r", encoding="utf-8") as f:
            remapper = json5.load(f)
        print(f"Loaded {len(remapper)} existing entries from {remapper_path.name}")
    else:
        remapper = []
        print(f"Creating new {remapper_path.name}")

    # Build index by ratingKey
    remapper_index = {entry["ratingKey"]: entry for entry in remapper}

    added = 0
    skipped_same = 0
    skipped_conflict = 0
    skipped_null = 0

    for card_id, entry in sorted(mapping.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        if entry is None:
            skipped_null += 1
            continue

        rating_key = str(entry.get("ratingKey", ""))
        if not rating_key:
            continue

        year = entry.get("year")
        if year is None:
            continue
        year = int(year)

        artist = entry.get("artist", "")
        title = entry.get("title", "")

        if rating_key in remapper_index:
            existing = remapper_index[rating_key]
            existing_year = existing.get("replaceData", {}).get("year")

            # Always update metadata
            if not dry_run:
                if "metadata" not in existing:
                    existing["metadata"] = {}
                existing["metadata"]["artist"] = artist
                existing["metadata"]["title"] = title

            if existing_year is not None:
                if existing_year == year:
                    skipped_same += 1
                    continue
                else:
                    print(f"  WARNING: {artist} - {title} (ratingKey {rating_key}): "
                          f"remapper has year={existing_year}, mapping says {year} - skipping")
                    skipped_conflict += 1
                    continue

            # Existing entry without year in replaceData - add it
            if not dry_run:
                if "replaceData" not in existing:
                    existing["replaceData"] = {}
                existing["replaceData"]["year"] = year
            added += 1
        else:
            # Create new entry
            if not dry_run:
                new_entry = {
                    "ratingKey": rating_key,
                    "metadata": {
                        "artist": artist,
                        "title": title,
                    },
                    "replaceData": {
                        "year": year,
                    },
                }
                remapper.append(new_entry)
                remapper_index[rating_key] = new_entry
            added += 1

    # Save
    if not dry_run:
        with open(remapper_path, "w", encoding="utf-8") as f:
            json.dump(remapper, f, indent=4, ensure_ascii=False)
            f.write("\n")

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Lock years complete:")
    print(f"  Added/updated: {added}")
    print(f"  Already correct: {skipped_same}")
    if skipped_null:
        print(f"  Unmatched cards: {skipped_null}")
    if skipped_conflict:
        print(f"  Conflicts (skipped): {skipped_conflict}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Lock mapping years into plex-remapper.json"
    )

    parser.add_argument(
        "--mapping", "-m", required=True,
        help="Mapping filename (e.g., plex-mapping-de-aaaa0039.json)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing"
    )
    parser.add_argument(
        "--config",
        help="Path to plex-config.json (default: ../plex-config.json)"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Load config
    config_path = Path(args.config) if args.config else Path(__file__).parent.parent.parent / "plex-config.json"
    config = load_plex_config(config_path)

    files_path = config.get("files_path")
    remapper_path = config.get("remapper_path")

    if not files_path:
        print("Error: files-path is required in plex-config.json")
        sys.exit(1)
    if not remapper_path:
        print("Error: remapper-filename not set in plex-config.json")
        sys.exit(1)

    # Resolve mapping file
    mapping_path = files_path / args.mapping
    if not mapping_path.exists():
        print(f"Error: Mapping file not found: {mapping_path}")
        sys.exit(1)

    # Load mapping
    print(f"Mapping: {mapping_path}")
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json5.load(f)

    matched = sum(1 for v in mapping.values() if v is not None)
    print(f"Entries: {len(mapping)} ({matched} matched)")
    print(f"Remapper: {remapper_path}")

    if not args.dry_run:
        print(f"\nThis will lock {matched} years into {remapper_path.name}.")
        response = input("Continue? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            return

    print()
    lock_years(mapping, remapper_path, args.dry_run)


if __name__ == "__main__":
    main()
