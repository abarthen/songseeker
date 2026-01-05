#!/usr/bin/env python3
"""
Year Validation Tool for SongSeeker Plex Mappings

Validates the year values in plex-mapping-*.json files against MusicBrainz database.
Reports tracks where the year in Plex differs from MusicBrainz's first release date.

Usage:
    poetry run validate-years --mapping ../plex-mapping-de-at-2026.json
    poetry run validate-years --mapping ../plex-mapping-de-at-2026.json --tolerance 1
    poetry run validate-years --mapping ../plex-mapping-de-at-2026.json --output report.json
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests


MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
USER_AGENT = "SongSeeker-YearValidator/1.0 (https://github.com/andygruber/songseeker)"
RATE_LIMIT_DELAY = 1.5  # MusicBrainz requires max 1 request per second, use 1.5 for safety
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # Base delay for exponential backoff


def escape_lucene(text: str) -> str:
    """Escape special Lucene characters in search query."""
    special_chars = r'+-&|!(){}[]^"~*?:\/'
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


def _do_musicbrainz_search(query: str, debug: bool = False) -> list[dict]:
    """Execute a single MusicBrainz search query with retry logic."""
    url = f"{MUSICBRAINZ_API}/recording"
    params = {
        "query": query,
        "fmt": "json",
        "limit": 100,
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)

            if response.status_code == 503:
                retry_delay = RETRY_BASE_DELAY * (2 ** attempt)
                if debug:
                    print(f"  [!] Rate limited (503), waiting {retry_delay}s before retry {attempt + 1}/{MAX_RETRIES}")
                time.sleep(retry_delay)
                continue

            response.raise_for_status()
            data = response.json()

            results = []
            for recording in data.get("recordings", []):
                first_release = recording.get("first-release-date", "")
                year = None
                if first_release:
                    year = int(first_release[:4]) if len(first_release) >= 4 else None

                artist_credit = ""
                for credit in recording.get("artist-credit", []):
                    if isinstance(credit, dict):
                        artist_credit += credit.get("name", "") + credit.get("joinphrase", "")

                results.append({
                    "title": recording.get("title", ""),
                    "artist": artist_credit,
                    "first_release_year": year,
                    "first_release_date": first_release,
                    "score": recording.get("score", 0),
                    "mbid": recording.get("id", ""),
                })

            return results

        except (requests.RequestException, ConnectionError) as e:
            retry_delay = RETRY_BASE_DELAY * (2 ** attempt)
            if attempt < MAX_RETRIES - 1:
                if debug:
                    print(f"  [!] Connection error, waiting {retry_delay}s before retry {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(retry_delay)
            else:
                print(f"  [!] MusicBrainz API error after {MAX_RETRIES} retries: {e}", file=sys.stderr)

    return []


def search_musicbrainz(artist: str, title: str, debug: bool = False) -> list[dict]:
    """
    Search MusicBrainz for recordings matching artist and title.
    Does multiple searches to find original releases:
    1. Official singles/albums only (most likely to have original)
    2. General search with artist
    3. Search for older recordings if needed
    Returns combined deduplicated results.
    """
    artist_escaped = escape_lucene(artist)
    title_escaped = escape_lucene(title)

    all_results = []
    seen_mbids = set()

    def add_results(new_results: list[dict]) -> None:
        for r in new_results:
            if r["mbid"] not in seen_mbids:
                all_results.append(r)
                seen_mbids.add(r["mbid"])

    # Search 1: Official singles/albums only (excludes live, compilations, bootlegs)
    # This prioritizes original studio recordings
    official_query = (
        f'artist:"{artist_escaped}" AND recording:"{title_escaped}" '
        f'AND status:official AND (primarytype:single OR primarytype:album) '
        f'AND NOT secondarytype:live AND NOT secondarytype:compilation'
    )
    if debug:
        print(f"  -> Searching official singles/albums...")
    official_results = _do_musicbrainz_search(official_query, debug)
    add_results(official_results)

    # Search 2: General search with artist (catches anything missed)
    time.sleep(RATE_LIMIT_DELAY)
    general_query = f'artist:"{artist_escaped}" AND recording:"{title_escaped}"'
    general_results = _do_musicbrainz_search(general_query, debug)
    add_results(general_results)

    if not all_results:
        return []

    # Find earliest year in current results
    years = [r["first_release_year"] for r in all_results if r["first_release_year"]]
    if not years:
        return all_results

    earliest_year = min(years)

    # Search 3: Look for recordings released BEFORE our current earliest
    if earliest_year > 1950:
        time.sleep(RATE_LIMIT_DELAY)
        older_query = f'artist:"{artist_escaped}" AND recording:"{title_escaped}" AND firstreleasedate:[1900 TO {earliest_year - 1}]'
        if debug:
            print(f"  -> Searching for recordings before {earliest_year}...")
        older_results = _do_musicbrainz_search(older_query, debug)
        add_results(older_results)
        if older_results and debug:
            print(f"  -> Found {len(older_results)} additional older recordings")

    return all_results


def normalize_for_comparison(text: str) -> str:
    """Normalize text for fuzzy comparison - keep only alphanumeric."""
    if not text:
        return ""
    import re
    text = text.lower()
    # Replace & with "and" before stripping
    text = text.replace("&", "and")
    # Remove accents first
    replacements = {
        "ä": "a", "ö": "o", "ü": "u", "é": "e", "è": "e", "ê": "e",
        "á": "a", "à": "a", "â": "a", "ó": "o", "ò": "o", "ô": "o",
        "ú": "u", "ù": "u", "û": "u", "ñ": "n", "ß": "ss", "æ": "ae", "œ": "oe"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Keep only alphanumeric characters
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def find_best_match(plex_artist: str, plex_title: str, mb_results: list[dict], debug: bool = False) -> dict | None:
    """Find the best matching MusicBrainz result for the Plex track."""
    if not mb_results:
        return None

    plex_artist_norm = normalize_for_comparison(plex_artist)
    plex_title_norm = normalize_for_comparison(plex_title)

    if debug:
        print(f"  -> MusicBrainz returned {len(mb_results)} results:")
        for r in mb_results[:5]:  # Show top 5
            print(f"     [{r['score']:3d}] {r['artist']} - {r['title']} ({r['first_release_year'] or '?'})")
        if len(mb_results) > 5:
            print(f"     ... and {len(mb_results) - 5} more")

    candidates = []

    for result in mb_results:
        # Check title match
        mb_title_norm = normalize_for_comparison(result["title"])
        if plex_title_norm != mb_title_norm:
            # Allow partial match for title, but require significant overlap
            # This handles cases like "Satisfaction" matching "(I Can't Get No) Satisfaction"
            # but prevents "Reborn" from matching "Queen of Hearts Reborn"
            shorter = min(len(plex_title_norm), len(mb_title_norm))
            longer = max(len(plex_title_norm), len(mb_title_norm))

            if plex_title_norm in mb_title_norm or mb_title_norm in plex_title_norm:
                # Require shorter to be at least 50% of longer
                if shorter / longer < 0.5:
                    continue
            else:
                continue

        # Check artist match (more lenient)
        mb_artist_norm = normalize_for_comparison(result["artist"])
        artist_match = (
            plex_artist_norm in mb_artist_norm or
            mb_artist_norm in plex_artist_norm or
            any(part in mb_artist_norm for part in plex_artist_norm.split())
        )

        if not artist_match:
            continue

        # This result matches - add to candidates
        candidates.append(result)

    if not candidates:
        return None

    if debug:
        print(f"  -> {len(candidates)} candidates after filtering:")
        for c in candidates:
            print(f"     [{c['score']:3d}] {c['artist']} - {c['title']} ({c['first_release_year'] or '?'})")

    # Among matching candidates, prefer:
    # 1. Results with a year
    # 2. The EARLIEST first-release-year (original release, not remaster)
    # 3. Higher MusicBrainz score as tiebreaker
    candidates_with_year = [c for c in candidates if c["first_release_year"]]

    if candidates_with_year:
        # Sort by year (earliest first), then by score (highest first)
        candidates_with_year.sort(key=lambda c: (c["first_release_year"], -c["score"]))
        selected = candidates_with_year[0]
    else:
        # No year info - just use highest score
        selected = max(candidates, key=lambda c: c["score"])

    if debug:
        print(f"  -> Selected: {selected['artist']} - {selected['title']} ({selected['first_release_year'] or '?'})")

    return selected


def validate_tracks(mapping: dict, tolerance: int = 0, limit: int | None = None, debug: bool = False, filter_str: str | None = None) -> list[dict]:
    """
    Validate years in a mapping dict against MusicBrainz.

    Args:
        mapping: Dict of ratingKey -> track info (from mapping file or converted report)
        tolerance: Allowed year difference (0 = exact match required)
        limit: Max number of tracks to check (None = all)
        debug: Print debug info for each track
        filter_str: Only check tracks where artist or title contains this (case-insensitive)

    Returns:
        List of discrepancies found
    """
    # Apply filter if specified
    if filter_str:
        filter_lower = filter_str.lower()
        mapping = {
            k: v for k, v in mapping.items()
            if filter_lower in v.get("artist", "").lower() or filter_lower in v.get("title", "").lower()
        }
        print(f"Filter '{filter_str}' matched {len(mapping)} tracks")

    discrepancies = []
    checked = 0
    not_found = 0

    total = len(mapping) if limit is None else min(limit, len(mapping))

    print(f"Validating {total} tracks against MusicBrainz...")
    print(f"Tolerance: ±{tolerance} year(s)")
    print()

    for i, (rating_key, track) in enumerate(mapping.items()):
        if limit and checked >= limit:
            break

        artist = track.get("artist", "")
        title = track.get("title", "")
        plex_year = track.get("year")

        if not artist or not title or not plex_year:
            continue

        checked += 1

        if debug:
            print(f"[{checked}/{total}] Checking: {artist} - {title} ({plex_year})")
        else:
            # Progress indicator
            if checked % 10 == 0:
                print(f"  Progress: {checked}/{total}", end="\r")

        # Query MusicBrainz
        mb_results = search_musicbrainz(artist, title, debug=debug)
        time.sleep(RATE_LIMIT_DELAY)  # Respect rate limit

        if not mb_results:
            not_found += 1
            if debug:
                print(f"  -> No results found on MusicBrainz")
            continue

        # Find best match
        best_match = find_best_match(artist, title, mb_results, debug=debug)

        if not best_match:
            not_found += 1
            if debug:
                print(f"  -> No matching result found (got {len(mb_results)} results but none matched)")
            continue

        mb_year = best_match["first_release_year"]

        if not mb_year:
            not_found += 1
            if debug:
                print(f"  -> Match found but no year available")
            continue

        year_diff = abs(plex_year - mb_year)

        if debug:
            status = "✓" if year_diff <= tolerance else "✗"
            print(f"  -> MusicBrainz: {best_match['artist']} - {best_match['title']} ({mb_year}) [{status}]")

        if year_diff > tolerance:
            discrepancy = {
                "ratingKey": rating_key,
                "artist": artist,
                "title": title,
                "album": track.get("album", ""),
                "plex_year": plex_year,
                "musicbrainz_year": mb_year,
                "difference": mb_year - plex_year,
                "musicbrainz_date": best_match["first_release_date"],
                "musicbrainz_mbid": best_match["mbid"],
            }
            discrepancies.append(discrepancy)

            if not debug:
                print(f"  MISMATCH: {artist} - {title}")
                print(f"           Plex: {plex_year}, MusicBrainz: {mb_year} (diff: {mb_year - plex_year:+d})")

    print()
    print(f"Checked: {checked} tracks")
    print(f"Not found on MusicBrainz: {not_found}")
    print(f"Discrepancies found: {len(discrepancies)}")

    return discrepancies


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate Plex mapping years against MusicBrainz"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--mapping", "-m",
        help="Path to plex-mapping-*.json file (initial full scan)"
    )
    input_group.add_argument(
        "--report", "-r",
        help="Path to previous report.json (re-check only previously flagged tracks)"
    )
    input_group.add_argument(
        "--apply", "-a",
        help="Apply report to plex-date-remapper.json (updates year in replaceData)"
    )
    parser.add_argument(
        "--tolerance", "-t", type=int, default=0,
        help="Allowed year difference (default: 0 = exact match)"
    )
    parser.add_argument(
        "--limit", "-l", type=int,
        help="Limit number of tracks to check (for testing)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file for discrepancy report"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true",
        help="Show detailed progress for each track"
    )
    parser.add_argument(
        "--filter", "-f",
        help="Only check tracks where artist or title contains this string (case-insensitive)"
    )
    return parser.parse_args()


def load_tracks_from_report(report_path: Path) -> dict:
    """Convert a report JSON back to a mapping-like structure for re-validation."""
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Convert report entries to mapping format
    mapping = {}
    for entry in report:
        rating_key = entry["ratingKey"]
        mapping[rating_key] = {
            "ratingKey": rating_key,
            "title": entry["title"],
            "artist": entry["artist"],
            "album": entry.get("album", ""),
            "year": entry["plex_year"],
        }
    return mapping


def apply_report_to_remapper(report_path: Path, debug: bool = False) -> None:
    """
    Apply year corrections from a report to plex-date-remapper.json.
    Creates or updates entries based on ratingKey.
    """
    remapper_path = report_path.parent / "plex-date-remapper.json"

    # Load report
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    if not report:
        print("Report is empty, nothing to apply.")
        return

    # Load existing remapper or start fresh
    if remapper_path.exists():
        with open(remapper_path, "r", encoding="utf-8") as f:
            remapper = json.load(f)
        print(f"Loaded {len(remapper)} existing entries from {remapper_path.name}")
    else:
        remapper = []
        print(f"Creating new {remapper_path.name}")

    # Build index by ratingKey for quick lookup
    remapper_index = {entry["ratingKey"]: entry for entry in remapper}

    added = 0
    updated = 0

    for item in report:
        rating_key = item["ratingKey"]
        mb_year = item["musicbrainz_year"]
        artist = item["artist"]
        title = item["title"]

        if rating_key in remapper_index:
            # Update existing entry
            existing = remapper_index[rating_key]
            old_year = existing.get("replaceData", {}).get("year")

            if "replaceData" not in existing:
                existing["replaceData"] = {}

            if old_year != mb_year:
                existing["replaceData"]["year"] = mb_year
                updated += 1
                if debug:
                    if old_year:
                        print(f"  Updated: {artist} - {title} (year: {old_year} -> {mb_year})")
                    else:
                        print(f"  Updated: {artist} - {title} (added year: {mb_year})")
            elif debug:
                print(f"  Unchanged: {artist} - {title} (year already {mb_year})")
        else:
            # Create new entry
            new_entry = {
                "ratingKey": rating_key,
                "metadata": {
                    "artist": artist,
                    "title": title,
                },
                "replaceData": {
                    "year": mb_year,
                },
            }
            remapper.append(new_entry)
            remapper_index[rating_key] = new_entry
            added += 1
            if debug:
                print(f"  Added: {artist} - {title} (year: {mb_year})")

    # Save updated remapper
    with open(remapper_path, "w", encoding="utf-8") as f:
        json.dump(remapper, f, indent=4, ensure_ascii=False)
        f.write("\n")

    print(f"\nApplied {len(report)} entries from report:")
    print(f"  Added: {added}")
    print(f"  Updated: {updated}")
    print(f"  Unchanged: {len(report) - added - updated}")
    print(f"\nSaved to: {remapper_path}")


def main():
    args = parse_args()

    # Handle --apply mode separately
    if args.apply:
        apply_path = Path(args.apply)
        if not apply_path.exists():
            print(f"Error: Report file not found: {apply_path}", file=sys.stderr)
            sys.exit(1)
        apply_report_to_remapper(apply_path, debug=args.debug)
        sys.exit(0)

    # Load tracks from either mapping or previous report
    if args.mapping:
        input_path = Path(args.mapping)
        if not input_path.exists():
            print(f"Error: Mapping file not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        with open(input_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        print(f"Loaded {len(mapping)} tracks from mapping file")
    else:
        input_path = Path(args.report)
        if not input_path.exists():
            print(f"Error: Report file not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        mapping = load_tracks_from_report(input_path)
        print(f"Loaded {len(mapping)} tracks from previous report (re-checking)")

    discrepancies = validate_tracks(
        mapping,
        tolerance=args.tolerance,
        limit=args.limit,
        debug=args.debug,
        filter_str=args.filter,
    )

    # Determine output path: explicit --output, or same as --report if used (but not with filter)
    output_path = None
    if args.output:
        output_path = Path(args.output)
    elif args.report and not args.filter:
        # Default to overwriting the report file when re-checking (but not when filtering)
        output_path = Path(args.report)
    elif args.report and args.filter:
        print("\nNote: Not auto-saving when using --filter with --report (use --output to save)")
        output_path = None

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(discrepancies, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved to: {output_path}")

    if discrepancies:
        print("\n--- Summary of Discrepancies ---")
        for d in discrepancies:
            print(f"{d['artist']} - {d['title']}: Plex={d['plex_year']}, MB={d['musicbrainz_year']} ({d['difference']:+d})")

    sys.exit(0 if not discrepancies else 1)


if __name__ == "__main__":
    main()
