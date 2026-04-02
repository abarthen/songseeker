#!/usr/bin/env python3
"""
Manifest Generator for SongSeeker

Regenerates plex-manifest.json from existing plex-mapping-*.json files.
This is a standalone tool that doesn't require Plex connectivity.

The game-registry.json file (configured via game-registry-filename in
plex-config.json) determines which mapping files to include and their display names.

Usage:
    poetry run update-manifest
    poetry run update-manifest --debug
"""

import argparse
import json
import sys
from pathlib import Path

import json5

from .plex_api import load_plex_config


def load_game_registry(registry_path: Path) -> dict[str, dict]:
    """Load game-registry.json and return a mapping of suffix -> game info.

    Supports both formats:
    - New: {"de": {"name": "Hitster Deutschland", "playlist": "Hitster DE"}}
    - Legacy: {"de": "Hitster Deutschland"}

    Returns dict of mapping_id -> {"name": str, "playlist": str | None}.
    """
    if not registry_path.exists():
        print(f"Warning: Game registry not found: {registry_path}")
        return {}

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            raw = json5.load(f)

        registry = {}
        for key, value in raw.items():
            if isinstance(value, str):
                registry[key] = {"name": value}
            else:
                registry[key] = value
        return registry
    except (json5.JSON5DecodeError, IOError) as e:
        print(f"Warning: Could not read game registry: {e}")
        return {}


def calculate_mapping_stats(mapping_path: Path) -> dict | None:
    """Calculate statistics for a single mapping file.

    Returns dict with keys: songCount, matchRate, minDate, maxDate
    Returns None if file cannot be read.
    """
    try:
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json5.load(f)

        total = len(mapping)
        matched = sum(1 for v in mapping.values() if v is not None)
        match_rate = round(matched / total * 100, 1) if total > 0 else 0

        # Calculate min/max years from matched tracks
        years = [v.get("year") for v in mapping.values()
                 if v is not None and v.get("year")]

        return {
            "songCount": total,
            "matchRate": match_rate,
            "minDate": min(years) if years else None,
            "maxDate": max(years) if years else None,
        }
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Warning: Could not read {mapping_path.name}: {e}")
        return None


def generate_manifest(scan_dir: Path, game_registry: dict[str, str], debug: bool = False) -> dict:
    """Generate manifest from mapping files based on game-registry.json.

    Only includes mappings that have an entry in game_registry.

    Args:
        scan_dir: Directory containing plex-mapping-*.json files
        game_registry: Dict of mapping suffix -> game name
        debug: Enable debug output

    Returns:
        Manifest dict with "games" list
    """
    if debug:
        print(f"Scanning directory: {scan_dir}")
        print(f"Game name mappings: {len(game_registry)}")

    games_list = []

    for mapping_id, game_info in game_registry.items():
        game_name = game_info["name"]
        mapping_path = scan_dir / f"plex-mapping-{mapping_id}.json"

        if not mapping_path.exists():
            if debug:
                print(f"  {mapping_id}: MISSING (file not found)")
            continue

        stats = calculate_mapping_stats(mapping_path)
        if stats is None:
            continue

        game_obj = {
            "mapping": mapping_id,
            "name": game_name,
            "songCount": stats["songCount"],
            "matchRate": stats["matchRate"],
        }
        if stats["minDate"] is not None:
            game_obj["minDate"] = stats["minDate"]
        if stats["maxDate"] is not None:
            game_obj["maxDate"] = stats["maxDate"]

        games_list.append(game_obj)

        if debug:
            years = ""
            if stats["minDate"] and stats["maxDate"]:
                years = f" ({stats['minDate']}-{stats['maxDate']})"
            print(f"  {mapping_id}: {stats['songCount']} songs, {stats['matchRate']}% matched{years}")

    # Sort by mapping name
    games_list.sort(key=lambda g: g["mapping"])

    return {"games": games_list}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Regenerate plex-manifest.json from existing mapping files"
    )
    parser.add_argument(
        "--config", help="Path to plex-config.json (default: ../plex-config.json)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output manifest path (default: from config manifest-filename)"
    )
    parser.add_argument(
        "--scan-dir", "-s",
        help="Directory to scan for mapping files (default: from config files-path)"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true",
        help="Enable debug output"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Load config
    config_path = Path(args.config) if args.config else Path(__file__).parent.parent.parent / "plex-config.json"
    config = load_plex_config(config_path)

    # Determine scan directory
    if args.scan_dir:
        scan_dir = Path(args.scan_dir)
    elif config.get("files_path"):
        scan_dir = config["files_path"]
    else:
        print("Error: No scan directory specified. Use --scan-dir or set files-path in config.")
        sys.exit(1)

    # Determine output path
    if args.output:
        manifest_path = Path(args.output)
        if not manifest_path.is_absolute():
            manifest_path = scan_dir / manifest_path
    elif config.get("manifest_path"):
        manifest_path = config["manifest_path"]
    else:
        manifest_path = scan_dir / "plex-manifest.json"

    # Load game registry
    game_registry_path = config.get("game_registry_path")
    if not game_registry_path:
        print("Error: game-registry-filename not set in plex-config.json")
        sys.exit(1)

    game_registry = load_game_registry(game_registry_path)
    if not game_registry:
        print("Error: No game registry entries found. Cannot generate manifest.")
        sys.exit(1)

    print(f"Scan directory: {scan_dir}")
    print(f"Output: {manifest_path}")
    print(f"Game registry: {game_registry_path}")
    print()

    # Generate manifest
    manifest = generate_manifest(scan_dir, game_registry, args.debug)

    # Write output
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest saved: {manifest_path}")
    print(f"Total games: {len(manifest['games'])}")

    # Summary table
    if len(manifest['games']) > 0:
        print(f"\n{'Mapping':<30} {'Songs':>8} {'Match%':>8} {'Years':<15}")
        print("-" * 65)
        for game in manifest['games']:
            years = ""
            if game.get("minDate") and game.get("maxDate"):
                years = f"{game['minDate']}-{game['maxDate']}"
            print(f"{game['mapping']:<30} {game['songCount']:>8} {game['matchRate']:>7.1f}% {years:<15}")


if __name__ == "__main__":
    main()
