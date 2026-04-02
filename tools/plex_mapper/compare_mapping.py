#!/usr/bin/env python3
"""
Compare Mapping to CSV for SongSeeker

Compares a plex-mapping JSON file against its corresponding Hitster CSV file.
Reports year mismatches and warns about significant artist/title differences.

Usage:
    # Compare using mapping ID (resolves both files from config)
    poetry run compare-mapping de-aaaa0039

    # Compare with verbose output (show all entries, not just mismatches)
    poetry run compare-mapping de-aaaa0039 --verbose
"""

import argparse
import csv
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import json5

from .plex_api import load_plex_config, normalize_for_comparison


# Similarity threshold below which we warn about artist/title differences
SIMILARITY_THRESHOLD = 0.6


def parse_csv(csv_path: Path) -> dict[str, dict]:
    """Parse CSV file and return dict of card# -> {title, artist, year}."""
    entries = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        first_line = f.readline()
        if first_line.startswith("sep="):
            # Excel sep= directive — use the specified delimiter
            delimiter = first_line.strip().replace("sep=", "")
        else:
            f.seek(0)
            # Auto-detect: if header contains semicolons but no commas, use semicolon
            header_line = f.readline()
            f.seek(0)
            delimiter = ";" if ";" in header_line and "," not in header_line else ","

        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            card = row.get("Card#", "").strip()
            if card:
                entries[card] = {
                    "title": row.get("Title", "").strip(),
                    "artist": row.get("Artist", "").strip(),
                    "year": row.get("Year", "").strip(),
                }
    return entries


def strip_title_noise(text: str) -> str:
    """Remove parenthesized/bracketed content and everything after ' - '."""
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"\s*\[[^\]]*\]", "", text)
    text = re.sub(r"\s+-\s+.*$", "", text)
    return text.strip()


def similarity(a: str, b: str) -> float:
    """Compare two strings using normalized form, return 0.0-1.0 similarity.

    Strips parenthesized content before comparing, so 'Foo (Remaster)' matches 'Foo'.
    """
    a = strip_title_noise(a)
    b = strip_title_noise(b)
    na = normalize_for_comparison(a)
    nb = normalize_for_comparison(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def compare(mapping: dict, csv_entries: dict, verbose: bool = False) -> tuple[int, int, int]:
    """Compare mapping against CSV entries.

    Returns (year_mismatches, artist_warnings, title_warnings).
    """
    year_mismatches = 0
    artist_warnings = 0
    title_warnings = 0

    for card_id, csv_entry in sorted(csv_entries.items(), key=lambda x: int(x[0])):
        json_entry = mapping.get(card_id)

        if json_entry is None:
            if verbose:
                print(f"  [{card_id:>3}] NOT MATCHED in JSON")
            continue

        csv_year = csv_entry["year"]
        json_year = str(json_entry.get("year", ""))

        csv_artist = csv_entry["artist"]
        json_artist = json_entry.get("artist", "")

        csv_title = csv_entry["title"]
        json_title = json_entry.get("title", "")

        issues = []

        # Year comparison
        if csv_year and json_year and csv_year != json_year:
            issues.append(f"YEAR: CSV={csv_year} JSON={json_year}")
            year_mismatches += 1

        # Artist comparison
        artist_sim = similarity(csv_artist, json_artist)
        if artist_sim < SIMILARITY_THRESHOLD:
            issues.append(f"ARTIST: CSV=\"{csv_artist}\" JSON=\"{json_artist}\" ({artist_sim:.0%})")
            artist_warnings += 1

        # Title comparison
        title_sim = similarity(csv_title, json_title)
        if title_sim < SIMILARITY_THRESHOLD:
            issues.append(f"TITLE: CSV=\"{csv_title}\" JSON=\"{json_title}\" ({title_sim:.0%})")
            title_warnings += 1

        if issues:
            print(f"  [{card_id:>3}] {csv_artist} - {csv_title}")
            for issue in issues:
                print(f"        {issue}")
        elif verbose:
            print(f"  [{card_id:>3}] OK - {csv_artist} - {csv_title}")

    return year_mismatches, artist_warnings, title_warnings


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare a plex-mapping JSON against its Hitster CSV"
    )

    parser.add_argument(
        "mapping_id",
        help="Mapping ID (e.g., de-aaaa0039). Resolves to plex-mapping-{id}.json and hitster-{id}.csv"
    )
    parser.add_argument(
        "--config",
        help="Path to plex-config.json (default: ../plex-config.json)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show all entries, not just mismatches"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Load config
    config_path = Path(args.config) if args.config else Path(__file__).parent.parent.parent / "plex-config.json"
    config = load_plex_config(config_path)

    files_path = config.get("files_path")
    csv_files_path = config.get("csv_files_path", files_path)

    if not files_path:
        print("Error: files-path is required in plex-config.json")
        sys.exit(1)

    # Resolve file paths
    mapping_id = args.mapping_id
    json_path = files_path / f"plex-mapping-{mapping_id}.json"
    csv_path = csv_files_path / f"hitster-{mapping_id}.csv"

    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    # Load files
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print()

    with open(json_path, "r", encoding="utf-8") as f:
        mapping = json5.load(f)

    csv_entries = parse_csv(csv_path)

    print(f"JSON entries: {len(mapping)}, CSV entries: {len(csv_entries)}")

    if not csv_entries:
        print("\nError: No entries found in CSV. Check the file format and delimiter.")
        sys.exit(1)

    print()

    # Compare
    year_mismatches, artist_warnings, title_warnings = compare(
        mapping, csv_entries, args.verbose
    )

    # Summary
    print()
    print("=" * 50)
    total_issues = year_mismatches + artist_warnings + title_warnings
    if total_issues == 0:
        print("All entries match!")
    else:
        print(f"Year mismatches:   {year_mismatches}")
        print(f"Artist warnings:   {artist_warnings}")
        print(f"Title warnings:    {title_warnings}")


if __name__ == "__main__":
    main()
