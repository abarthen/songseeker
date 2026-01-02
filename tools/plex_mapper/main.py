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


def load_plex_config(config_path: Path) -> tuple[str, str]:
    """Load Plex server URL and token from config file."""
    if not config_path.exists():
        return None, None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("serverUrl"), config.get("token")
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not read config file: {e}")
        return None, None


def normalize_for_comparison(text: str) -> str:
    """Normalize text for fuzzy comparison by removing spaces, punctuation, and lowercasing."""
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Normalize & to and (before removing spaces)
    text = text.replace(" & ", " and ").replace("&", " and ")
    # Remove common punctuation and spaces
    text = re.sub(r"[\s\-_'.,:;!?]+", "", text)
    # Remove accents (basic normalization)
    text = text.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    text = text.replace("é", "e").replace("è", "e").replace("ê", "e")
    text = text.replace("á", "a").replace("à", "a").replace("â", "a")
    text = text.replace("ó", "o").replace("ò", "o").replace("ô", "o")
    text = text.replace("ú", "u").replace("ù", "u").replace("û", "u")
    text = text.replace("ñ", "n").replace("ß", "ss")
    return text


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

    args = parser.parse_args()

    # Validate --rating-key requires --id
    if args.rating_key and not args.id:
        print("Error: --rating-key requires --id to specify which card to update")
        sys.exit(1)

    # Load config file if server/token not provided
    if not args.server or not args.token:
        config_path = Path(args.config) if args.config else Path(__file__).parent.parent.parent / "plex-config.json"
        config_server, config_token = load_plex_config(config_path)

        if not args.server:
            args.server = config_server
        if not args.token:
            args.token = config_token

    # Validate we have required values
    if not args.server or not args.token:
        print("Error: Plex server and token are required.")
        print("Either provide --server and --token, or create plex-config.json")
        sys.exit(1)

    return args


def plex_request(url: str, token: str) -> dict:
    """Make a request to the Plex API."""
    headers = {"Accept": "application/json"}
    params = {"X-Plex-Token": token}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_plex_track(server_url: str, token: str, rating_key: str, debug: bool = False) -> dict | None:
    """Fetch track metadata directly by ratingKey."""
    try:
        url = f"{server_url}/library/metadata/{rating_key}"
        if debug:
            print(f"  DEBUG: Fetching: {url}")

        response = plex_request(url, token)
        metadata = response.get("MediaContainer", {}).get("Metadata", [])

        if not metadata:
            print(f"  Error: No track found with ratingKey {rating_key}")
            return None

        track = metadata[0]
        media = track.get("Media", [{}])[0]
        parts = media.get("Part", [{}])[0]

        result = {
            "ratingKey": track.get("ratingKey"),
            "title": track.get("title"),
            "artist": track.get("grandparentTitle") or track.get("originalTitle"),
            "album": track.get("parentTitle"),
            "year": track.get("parentYear") or track.get("year"),
            "duration": track.get("duration"),
            "partKey": parts.get("key"),
        }

        if debug:
            print(f"  DEBUG: Found: {result['artist']} - {result['title']} ({result['year']})")

        return result

    except Exception as e:
        print(f"  Error fetching track: {e}")
        return None


def search_plex(server_url: str, token: str, artist: str, title: str, expected_year: int, debug: bool = False) -> dict | None:
    """Search Plex library for a track with exact year match."""
    # Clean up search terms
    clean_artist = re.sub(r"feat\..*", "", artist, flags=re.IGNORECASE)
    clean_artist = re.sub(r",.*", "", clean_artist).strip()
    clean_title = re.sub(r"\(.*\)", "", title)
    clean_title = re.sub(r"\[.*\]", "", clean_title).strip()

    # Try different search strategies
    search_queries = [
        clean_title,                          # Title only (most reliable)
        f"{clean_artist} {clean_title}",      # Full search
        clean_artist,                         # Artist only
    ]

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
                norm_clean_title = normalize_for_comparison(clean_title)
                norm_track_title = normalize_for_comparison(track_title)
                norm_clean_artist = normalize_for_comparison(clean_artist)
                norm_track_artist = normalize_for_comparison(track_artist)

                title_match = (
                    norm_clean_title in norm_track_title or
                    norm_track_title in norm_clean_title
                )
                artist_match = (
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
                        best_match = {
                            "ratingKey": track.get("ratingKey"),
                            "title": track.get("title"),
                            "artist": track.get("grandparentTitle") or track.get("originalTitle"),
                            "album": track.get("parentTitle"),
                            "year": track_year,
                            "duration": track.get("duration"),
                            "partKey": parts.get("key"),
                        }

                        # If exact year match, we're done
                        if year_diff == 0:
                            if debug:
                                print("  DEBUG: Exact year match!")
                            return best_match

        except Exception as e:
            if debug:
                print(f"  DEBUG: Search error: {e}")
            continue

    # Only return exact year matches
    if best_match and best_year_diff == 0:
        return best_match

    if debug and best_match:
        print(f"  DEBUG: Rejecting match - year mismatch ({best_match['year']} vs expected {expected_year})")

    return None


def parse_csv(csv_path: str) -> tuple[list[str], list[list[str]]]:
    """Parse CSV file and return headers and rows."""
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    # Skip Excel's sep= directive if present
    if rows and rows[0] and rows[0][0].lower().startswith("sep="):
        rows = rows[1:]
    return rows[0], rows[1:]


def youtube_to_music_url(url: str) -> str:
    """Convert YouTube URL to YouTube Music URL."""
    if not url:
        return ""

    # Handle youtu.be short URLs
    match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
    if match:
        return f"https://music.youtube.com/watch?v={match.group(1)}"

    # Handle regular youtube.com URLs
    url = url.replace("https://www.youtube.com/", "https://music.youtube.com/")
    url = url.replace("https://youtube.com/", "https://music.youtube.com/")
    return url


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

    # Create Plex-friendly folder structure: artist/album/song
    # For singles, album = song name
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


def main():
    args = parse_args()

    # Normalize server URL
    server_url = args.server.rstrip("/")

    # Read and parse CSV
    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

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

    # Test Plex connection
    print(f"Testing Plex connection: {server_url}")
    try:
        server_info = plex_request(f"{server_url}/", args.token)
        container = server_info.get("MediaContainer", {})
        print(f"Plex connection successful!")
        print(f"  Server: {container.get('friendlyName', 'Unknown')}")
        print(f"  Version: {container.get('version', 'Unknown')}")
    except Exception as e:
        print(f"Error: Cannot connect to Plex server: {e}")
        sys.exit(1)

    # Test search API
    print("\nTesting Plex search API...")
    try:
        test_search = plex_request(f"{server_url}/search?query=test&type=10", args.token)
        size = test_search.get("MediaContainer", {}).get("size", 0)
        print(f"Search API working! (Found {size} results for 'test')")
    except Exception as e:
        print(f"Warning: Search API test failed: {e}")

    # Determine output filename (no timestamp)
    if args.output:
        output_path = Path(args.output)
    else:
        csv_basename = csv_path.stem
        lang = csv_basename.replace("hitster-", "")
        output_path = Path(f"plex-mapping-{lang}.json")

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

        plex_track = search_plex(server_url, args.token, artist, title, year_int, args.debug)

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

    # Generate missing songs CSV (overwrites each run, skip when using --id)
    if missing_songs and not args.id:
        csv_basename = csv_path.stem
        lang = csv_basename.replace("hitster-", "")
        missing_path = Path(f"missing-{lang}.csv")
        with open(missing_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Card#", "Artist", "Title", "Year", "YouTube Music URL"])
            for song in missing_songs:
                yt_music_url = youtube_to_music_url(song["url"])
                writer.writerow([song["card_id"], song["artist"], song["title"], song["year"], yt_music_url])

        print(f"\nMissing songs CSV saved to: {missing_path}")

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
            if not song["url"]:
                print(f"[{i + 1}/{len(missing_songs)}] Skipping (no URL): {song['artist']} - {song['title']}")
                failed += 1
                continue

            print(f"[{i + 1}/{len(missing_songs)}] {song['artist']} - {song['title']} ({song['year']})... ", end="", flush=True)

            result = download_song(song["url"], song["artist"], song["title"], song["year"], download_dir, args.cookies, args.debug)
            if result is None:
                print("SKIPPED (exists)")
                skipped += 1
            elif result:
                print("DOWNLOADED")
                downloaded += 1
            else:
                print("FAILED")
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
