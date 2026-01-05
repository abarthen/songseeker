#!/usr/bin/env python3
"""
Plex Mapping Generator for SongSeeker

Reads Hitster CSV files and searches your Plex library to create a mapping file.
Can also download missing songs from YouTube with proper metadata.

Usage:
    poetry run plex-mapper --csv hitster-de.csv
    poetry run plex-mapper --csv hitster-de.csv --download
    poetry run plex-mapper --server https://plex.example.com --token YOUR_TOKEN --csv hitster-de.csv
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests

from .plex_api import (
    load_plex_config,
    plex_request,
    fetch_plex_track,
    get_remapped_year,
    get_remapped_artist,
    get_remapped_title,
    extract_guids,
    load_track_remapper,
    normalize_for_comparison,
    resolve_plex_credentials,
    test_plex_connection,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate Plex mappings for SongSeeker Hitster cards"
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
        "--csv", "-c", required=True, help="Path to Hitster CSV file"
    )
    parser.add_argument(
        "--output", "-o", help="Output JSON file path (default: plex-mapping-{lang}_{timestamp}.json)"
    )
    parser.add_argument(
        "--download", "-D", action="store_true", help="Download missing songs from YouTube"
    )
    parser.add_argument(
        "--download-dir", help="Directory to save downloaded songs (default: ./downloads)"
    )
    parser.add_argument(
        "--cookies", help="Path to cookies.txt file or browser name (chrome, firefox, edge) for YouTube auth"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Enable debug output"
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=0, help="Only process first N songs (for testing)"
    )
    parser.add_argument(
        "--rematch", "-R", action="store_true", help="Re-match all songs (default: skip already matched)"
    )
    parser.add_argument(
        "--id", "-i", help="Only process a specific card ID (updates existing mapping)"
    )
    parser.add_argument(
        "--rating-key", "-k", help="Manually set Plex ratingKey for --id (skips search, fetches metadata directly)"
    )
    parser.add_argument(
        "--year-tolerance", "-y", type=int, default=0, help="Accept year matches within ± N years (default: 0 = exact match only)"
    )
    parser.add_argument(
        "--check", "-C", action="store_true", help="Check that all rating keys in existing mapping still exist in Plex"
    )
    parser.add_argument(
        "--fix", "-F", action="store_true", help="With --check: remove missing tracks from mapping so they can be re-matched"
    )
    parser.add_argument(
        "--enrich", "-E", action="store_true", help="Re-fetch metadata for existing mappings (updates guid/mbid, applies remapper)"
    )
    parser.add_argument(
        "--remapper", required=True, help="Path to plex-remapper.json (for metadata overrides)"
    )
    parser.add_argument(
        "--manifest", help="Path to plex-manifest.json (default: same directory as output)"
    )

    args = parser.parse_args()

    # Validate --rating-key requires --id
    if args.rating_key and not args.id:
        print("Error: --rating-key requires --id to specify which card to update")
        sys.exit(1)

    # Validate --fix requires --check
    if args.fix and not args.check:
        print("Error: --fix requires --check")
        sys.exit(1)

    # Load config file if server/token not provided
    resolve_plex_credentials(args)

    return args


def search_plex(server_url: str, token: str, artist: str, title: str, expected_year: int, debug: bool = False, year_tolerance: int = 0) -> dict | None:
    """Search Plex library for a track with year matching within tolerance."""
    # Clean up search terms (removes parenthetical content like "feat." or "[Remastered]")
    clean_artist = re.sub(r"feat\..*", "", artist, flags=re.IGNORECASE)
    clean_artist = re.sub(r",.*", "", clean_artist).strip()
    clean_title = re.sub(r"\(.*\)", "", title)
    clean_title = re.sub(r"\[.*\]", "", clean_title).strip()

    # Try different search strategies - original title first, then cleaned versions
    search_queries = [
        title,                                # Original title (preserves parenthetical content)
        f"{artist} {title}",                  # Full original search
        clean_title,                          # Cleaned title (fallback)
        f"{clean_artist} {clean_title}",      # Cleaned full search
        clean_artist,                         # Artist only (last resort)
    ]
    # Remove duplicates while preserving order
    search_queries = list(dict.fromkeys(search_queries))

    best_match = None
    best_year_diff = float("inf")

    for query in search_queries:
        try:
            search_url = f"{server_url}/search?query={quote(query)}&type=10&limit=100"
            if debug:
                print(f"  DEBUG: Searching: {search_url}")

            response = plex_request(search_url, token)

            if debug:
                size = response.get("MediaContainer", {}).get("size", 0)
                print(f"  DEBUG: Response size: {size}")

            metadata = response.get("MediaContainer", {}).get("Metadata", [])

            for track in metadata:
                track_title = (track.get("title") or "").lower()
                track_artist = (track.get("grandparentTitle") or track.get("originalTitle") or "").lower()
                track_year = track.get("parentYear") or track.get("year")

                if debug:
                    print(f"  DEBUG: Checking: \"{track.get('title')}\" by \"{track.get('grandparentTitle') or track.get('originalTitle')}\" ({track_year})")

                # Check if this is a reasonable match (using normalized comparison)
                # Compare against both original and cleaned versions
                norm_title = normalize_for_comparison(title)
                norm_clean_title = normalize_for_comparison(clean_title)
                norm_track_title = normalize_for_comparison(track_title)
                norm_artist = normalize_for_comparison(artist)
                norm_clean_artist = normalize_for_comparison(clean_artist)
                norm_track_artist = normalize_for_comparison(track_artist)

                title_match = (
                    norm_title in norm_track_title or
                    norm_track_title in norm_title or
                    norm_clean_title in norm_track_title or
                    norm_track_title in norm_clean_title
                )
                artist_match = (
                    norm_artist in norm_track_artist or
                    norm_track_artist in norm_artist or
                    norm_clean_artist in norm_track_artist or
                    norm_track_artist in norm_clean_artist
                )

                if title_match and artist_match:
                    year_diff = abs((track_year or 0) - expected_year)

                    if debug:
                        print(f"  DEBUG: Match found! Year diff: {year_diff} (track: {track_year}, expected: {expected_year})")

                    if year_diff < best_year_diff:
                        best_year_diff = year_diff
                        media = track.get("Media", [{}])[0]
                        parts = media.get("Part", [{}])[0]
                        rating_key = track.get("ratingKey")
                        plex_artist = track.get("grandparentTitle") or track.get("originalTitle")
                        plex_title = track.get("title")
                        remapped_year = get_remapped_year(rating_key, track_year)
                        remapped_artist = get_remapped_artist(rating_key, plex_artist)
                        remapped_title = get_remapped_title(rating_key, plex_title)
                        if debug and remapped_year != track_year:
                            print(f"  DEBUG: Year remapped from {track_year} to {remapped_year}")
                        if debug and remapped_artist != plex_artist:
                            print(f"  DEBUG: Artist remapped from {plex_artist} to {remapped_artist}")
                        if debug and remapped_title != plex_title:
                            print(f"  DEBUG: Title remapped from {plex_title} to {remapped_title}")

                        # Extract stable identifiers (guid, mbid)
                        plex_guid, mbid = extract_guids(track)

                        best_match = {
                            "ratingKey": rating_key,
                            "title": remapped_title,
                            "artist": remapped_artist,
                            "album": track.get("parentTitle"),
                            "year": remapped_year,
                            "duration": track.get("duration"),
                            "partKey": parts.get("key"),
                        }

                        # Add stable identifiers if available
                        if plex_guid:
                            best_match["guid"] = plex_guid
                        if mbid:
                            best_match["mbid"] = mbid

                        # If exact year match, we're done searching
                        if year_diff == 0:
                            if debug:
                                print("  DEBUG: Exact year match!")
                                if plex_guid:
                                    print(f"  DEBUG: GUID: {plex_guid}")
                                if mbid:
                                    print(f"  DEBUG: MBID: {mbid}")
                            return best_match

        except Exception as e:
            if debug:
                print(f"  DEBUG: Search error: {e}")
            continue

    # Return match if within tolerance
    if best_match and best_year_diff <= year_tolerance:
        if debug and best_year_diff > 0:
            print(f"  DEBUG: Accepting match within tolerance (diff: {best_year_diff}, tolerance: {year_tolerance})")
            if best_match.get("guid"):
                print(f"  DEBUG: GUID: {best_match['guid']}")
            if best_match.get("mbid"):
                print(f"  DEBUG: MBID: {best_match['mbid']}")
        return best_match

    if debug and best_match:
        print(f"  DEBUG: Rejecting match - year mismatch ({best_match['year']} vs expected {expected_year}, diff: {best_year_diff}, tolerance: {year_tolerance})")

    return None


def parse_csv(csv_path: str) -> tuple[list[str], list[list[str]]]:
    """Parse CSV file and return headers and rows."""
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    # Skip Excel's sep= directive if present
    if rows and rows[0] and rows[0][0].lower().startswith("sep="):
        rows = rows[1:]
    # Filter out empty rows
    headers = rows[0]
    data_rows = [row for row in rows[1:] if row and len(row) >= len(headers)]
    return headers, data_rows


def load_playlists_csv(playlists_path: Path) -> dict[str, str]:
    """Load playlists.csv and return a mapping of lang -> game name."""
    if not playlists_path.exists():
        return {}

    games = {}
    try:
        with open(playlists_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Skip header row
        for row in rows[1:]:
            if len(row) >= 2:
                # hitster-de.csv -> de, hitster-de-aaaa0007.csv -> de-aaaa0007
                csv_file = row[0]
                game_name = row[1].strip()
                lang = csv_file.replace("hitster-", "").replace(".csv", "")
                games[lang] = game_name
    except Exception as e:
        print(f"Warning: Could not read playlists.csv: {e}")

    return games


def update_manifest(output_dir: Path, playlists_dir: Path = None, manifest_path: Path = None) -> None:
    """Update plex-manifest.json with list of game objects including date ranges."""
    if manifest_path is None:
        manifest_path = output_dir / "plex-manifest.json"

    # Find all plex-mapping-*.json files in the manifest's directory (or output_dir)
    scan_dir = manifest_path.parent if manifest_path else output_dir
    mapping_files = list(scan_dir.glob("plex-mapping-*.json"))

    # Load existing manifest to preserve custom game names
    existing_names = {}
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                existing_manifest = json.load(f)
            for game in existing_manifest.get("games", []):
                if game.get("mapping") and game.get("name"):
                    existing_names[game["mapping"]] = game["name"]
        except (json.JSONDecodeError, IOError):
            pass

    # Load game names from playlists.csv if available
    game_names = {}
    if playlists_dir:
        playlists_path = playlists_dir / "playlists.csv"
        game_names = load_playlists_csv(playlists_path)

    # Build list of game objects
    games_list = []
    for f in mapping_files:
        # plex-mapping-de.json -> de
        mapping_id = f.stem.replace("plex-mapping-", "")

        # Calculate stats from mapping file
        try:
            with open(f, "r", encoding="utf-8") as mf:
                mapping = json.load(mf)
            total = len(mapping)
            matched = sum(1 for v in mapping.values() if v is not None)
            match_rate = round(matched / total * 100, 1) if total > 0 else 0

            # Calculate min/max years from matched tracks
            years = [v.get("year") for v in mapping.values() if v is not None and v.get("year")]
            min_date = min(years) if years else None
            max_date = max(years) if years else None
        except (json.JSONDecodeError, IOError):
            match_rate = 0
            total = 0
            min_date = None
            max_date = None

        # Priority: playlists.csv > existing manifest > fallback
        game_name = game_names.get(mapping_id) or existing_names.get(mapping_id) or f"Unknown ({mapping_id})"

        game_obj = {
            "mapping": mapping_id,
            "name": game_name,
            "songCount": total,
            "matchRate": match_rate,
        }
        if min_date is not None:
            game_obj["minDate"] = min_date
        if max_date is not None:
            game_obj["maxDate"] = max_date

        games_list.append(game_obj)

    # Sort by mapping name
    games_list.sort(key=lambda g: g["mapping"])

    manifest = {"games": games_list}

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Updated manifest: {manifest_path} ({len(games_list)} games)")


def download_song(url: str, artist: str, title: str, year: str, output_dir: Path, cookies: str = None, debug: bool = False) -> bool:
    """Download a song from YouTube with proper metadata."""
    try:
        import yt_dlp
    except ImportError:
        print("Error: yt-dlp not installed. Run: poetry install")
        return False

    # Sanitize names for filesystem (remove invalid characters)
    safe_artist = re.sub(r'[<>:"/\\|?*]', "", artist).strip()
    safe_title = re.sub(r'[<>:"/\\|?*]', "", title).strip()

    # Create Plex-friendly folder structure: artist/album/song (using song title as album for singles)
    song_dir = output_dir / safe_artist / safe_title

    # Check if file already exists
    expected_file = song_dir / f"{safe_title} ({year}).mp3"
    if expected_file.exists():
        if debug:
            print(f"  DEBUG: File already exists: {expected_file}")
        return None  # None indicates skipped

    song_dir.mkdir(parents=True, exist_ok=True)

    # Filename: "song name (year).mp3"
    output_template = str(song_dir / f"{safe_title} ({year}).%(ext)s")

    ydl_opts = {
        # Let yt-dlp pick the best available format
        "format": "bestaudio/best",
        # Use web_creator client which works better currently
        "extractor_args": {
            "youtube": {
                "player_client": ["web_creator", "mweb", "ios"],
                # Allow formats that may need PO Token
                "formats": ["missing_pot"],
            }
        },
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
        ],
        "postprocessor_args": {
            "ffmpeg": [
                "-metadata", f"artist={artist}",
                "-metadata", f"title={title}",
                "-metadata", f"date={year}",
            ],
        },
        "outtmpl": output_template,
        "quiet": not debug,
        "no_warnings": not debug,
        "ignoreerrors": False,
        "retries": 3,
        "fragment_retries": 3,
        # Skip unavailable videos instead of failing
        "skip_unavailable_fragments": True,
    }

    # Add cookies if provided (helps bypass 403 errors)
    if cookies:
        if cookies in ("chrome", "firefox", "edge", "safari", "opera", "brave"):
            ydl_opts["cookiesfrombrowser"] = (cookies,)
        else:
            ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        if debug:
            print(f"  DEBUG: Download error: {e}")
        return False
    finally:
        # Clean up .part and .ytdl temp files
        for temp_file in song_dir.glob("*.part"):
            try:
                temp_file.unlink()
                if debug:
                    print(f"  DEBUG: Cleaned up {temp_file}")
            except OSError:
                pass
        for temp_file in song_dir.glob("*.ytdl"):
            try:
                temp_file.unlink()
                if debug:
                    print(f"  DEBUG: Cleaned up {temp_file}")
            except OSError:
                pass


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
            print("Run plex-mapper again to re-match these tracks.")
        else:
            print(f"\nUse --fix to remove these tracks from the mapping.")
    else:
        print("All tracks exist in Plex!")
    print("=" * 50)


def enrich_mapping(server_url: str, token: str, mapping_path: Path, debug: bool = False) -> None:
    """Re-fetch metadata for all tracks in a mapping file using their existing ratingKey."""
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
            if new_track.get("year") != entry.get("year"):
                changes.append(f"year:{entry.get('year')}->{new_track.get('year')}")
            if new_track.get("artist") != entry.get("artist"):
                changes.append(f"artist")
            if new_track.get("title") != entry.get("title"):
                changes.append(f"title")

            mapping[card_id] = new_track

            if changes:
                enriched += 1
                if debug:
                    print(f"UPDATED ({', '.join(changes)})")
                elif not debug:
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


def main():
    args = parse_args()

    # Load track remapper (for year/artist/title overrides)
    remapper_path = Path(args.remapper) if args.remapper else None
    load_track_remapper(remapper_path)

    # Normalize server URL
    server_url = args.server.rstrip("/")

    # Read and parse CSV
    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    # Determine output/mapping filename
    if args.output:
        output_path = Path(args.output)
    else:
        csv_basename = csv_path.stem
        lang = csv_basename.replace("hitster-", "")
        output_path = Path(f"plex-mapping-{lang}.json")

    # Handle --check mode
    if args.check:
        test_plex_connection(server_url, args.token)
        print()
        check_mapping(server_url, args.token, output_path, args.debug, args.fix)
        sys.exit(0)

    # Handle --enrich mode
    if args.enrich:
        test_plex_connection(server_url, args.token)
        print()
        enrich_mapping(server_url, args.token, output_path, args.debug)

        # Update manifest after enriching
        manifest_path = Path(args.manifest) if args.manifest else None
        update_manifest(output_path.parent, csv_path.parent, manifest_path)
        sys.exit(0)

    print(f"Reading CSV: {csv_path}")
    headers, rows = parse_csv(str(csv_path))

    # Get column indices
    try:
        card_idx = headers.index("Card#")
        artist_idx = headers.index("Artist")
        title_idx = headers.index("Title")
        year_idx = headers.index("Year")
    except ValueError as e:
        print(f"Error: CSV must have Card#, Artist, Title, and Year columns")
        print(f"Found headers: {headers}")
        sys.exit(1)

    url_idx = headers.index("URL") if "URL" in headers else -1

    # Test Plex connection and search API
    test_plex_connection(server_url, args.token, test_search=True)

    # Load existing mapping if not rematching (or if using --id, always load)
    existing_mapping = {}
    if (args.id or not args.rematch) and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_mapping = json.load(f)
            matched_count = sum(1 for v in existing_mapping.values() if v is not None)
            print(f"\nLoaded existing mapping: {matched_count} matched, {len(existing_mapping) - matched_count} unmatched")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load existing mapping: {e}")

    # Process each song
    mapping = dict(existing_mapping)  # Start with existing
    songs = rows
    found = 0
    not_found = 0
    skipped = 0
    missing_songs = []

    # Filter to specific ID if specified
    if args.id:
        songs = [row for row in rows if row[card_idx] == args.id]
        if not songs:
            print(f"\nError: Card ID '{args.id}' not found in CSV")
            sys.exit(1)

        # Handle manual ratingKey override
        if args.rating_key:
            print(f"\nManually setting card ID {args.id} to ratingKey {args.rating_key}...\n")
            plex_track = fetch_plex_track(server_url, args.token, args.rating_key, args.debug)
            if plex_track:
                mapping[args.id] = plex_track
                print(f"SUCCESS: {plex_track['artist']} - {plex_track['title']} ({plex_track['year']})")
                # Write output and exit early
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(mapping, f, indent=2)
                print(f"\nMapping saved to: {output_path}")
                return
            else:
                print("FAILED: Could not fetch track metadata")
                sys.exit(1)

        print(f"\nProcessing card ID {args.id}...\n")
    # Apply limit if specified
    elif args.limit > 0:
        songs = songs[:args.limit]
        print(f"\nProcessing first {args.limit} songs (limit applied)...\n")
    else:
        print(f"\nProcessing {len(songs)} songs...\n")

    for i, row in enumerate(songs):
        card_id = row[card_idx]
        artist = row[artist_idx]
        title = row[title_idx]
        year = row[year_idx]
        url = row[url_idx] if url_idx >= 0 else ""

        # Skip already matched songs (unless rematching or specific ID)
        if not args.id and not args.rematch and card_id in existing_mapping and existing_mapping[card_id] is not None:
            if args.debug:
                print(f"[{i + 1}/{len(songs)}] Skipping (already matched): {artist} - {title}")
            skipped += 1
            found += 1  # Count as found for stats
            continue

        if args.debug:
            print(f"\n[{i + 1}/{len(songs)}] Searching: \"{artist}\" - \"{title}\" ({year})")
        else:
            print(f"[{i + 1}/{len(songs)}] Searching: {artist} - {title} ({year})... ", end="", flush=True)

        try:
            year_int = int(year)
        except ValueError:
            year_int = 0

        plex_track = search_plex(server_url, args.token, artist, title, year_int, args.debug, args.year_tolerance)

        if plex_track:
            mapping[card_id] = plex_track
            if args.debug:
                print(f"  FOUND: {plex_track['artist']} - {plex_track['title']} (key: {plex_track['ratingKey']})")
            else:
                print(f"FOUND ({plex_track['artist']} - {plex_track['title']})")
            found += 1
        else:
            mapping[card_id] = None
            if args.debug:
                print("  NOT FOUND")
            else:
                print("NOT FOUND")
            not_found += 1
            missing_songs.append({
                "card_id": card_id,
                "artist": artist,
                "title": title,
                "year": year,
                "url": url,
            })

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    # Update manifest.json to list available mappings (pass CSV dir for playlists.csv)
    manifest_path = Path(args.manifest) if args.manifest else None
    update_manifest(output_path.parent, csv_path.parent, manifest_path)

    # Download missing songs if requested
    if args.download and missing_songs:
        download_dir = Path(args.download_dir) if args.download_dir else Path("downloads")
        download_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 40}")
        print(f"Downloading {len(missing_songs)} missing songs to: {download_dir}")
        print("=" * 40 + "\n")

        downloaded = 0
        skipped = 0
        failed = 0

        for i, song in enumerate(missing_songs):
            progress = f"[{i + 1}/{len(missing_songs)}]"
            song_info = f"{song['artist']} - {song['title']} ({song['year']})"

            if not song["url"]:
                print(f"{progress} {song_info} - SKIPPED (no URL)")
                failed += 1
                continue

            print(f"{progress} Downloading: {song_info}")

            result = download_song(song["url"], song["artist"], song["title"], song["year"], download_dir, args.cookies, args.debug)
            if result is None:
                print(f"  -> SKIPPED (already exists)")
                skipped += 1
            elif result:
                print(f"  -> DOWNLOADED")
                downloaded += 1
            else:
                print(f"  -> FAILED")
                failed += 1

        print(f"\nDownload complete: {downloaded} succeeded, {skipped} skipped, {failed} failed")
        print(f"Files saved to: {download_dir.resolve()}")

    # Print summary
    print(f"\n{'=' * 40}")
    print("Results:")
    if skipped > 0:
        print(f"  Skipped (already matched): {skipped}")
    print(f"  Found in Plex: {found}")
    print(f"  Not found:     {not_found}")
    print(f"  Total:         {len(songs)}")
    print(f"  Match rate:    {(found / len(songs) * 100):.1f}%")
    print(f"\nMapping saved to: {output_path}")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()
