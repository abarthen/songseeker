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
import os
import re
import sys
from datetime import datetime
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

    args = parser.parse_args()

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
            search_url = f"{server_url}/search?query={quote(query)}&type=10"
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

                # Check if this is a reasonable match
                title_match = (
                    clean_title.lower() in track_title or
                    track_title in clean_title.lower()
                )
                artist_match = (
                    clean_artist.lower() in track_artist or
                    track_artist in clean_artist.lower()
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

    # Process each song
    mapping = {}
    songs = rows
    found = 0
    not_found = 0
    missing_songs = []

    # Apply limit if specified
    if args.limit > 0:
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

    # Determine output filename with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    if args.output:
        output_path = Path(args.output)
    else:
        csv_basename = csv_path.stem
        lang = csv_basename.replace("hitster-", "")
        output_path = Path(f"plex-mapping-{lang}_{timestamp}.json")

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    # Generate missing songs CSVs
    if missing_songs:
        # Soundiiz CSV format
        soundiiz_path = output_path.with_name(output_path.stem + "-missing-soundiiz.csv")
        with open(soundiiz_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Track Name", "Artist Name", "Album Name"])
            for song in missing_songs:
                writer.writerow([song["title"], song["artist"], ""])

        print(f"\nSoundiiz CSV saved to: {soundiiz_path}")
        print("  -> Upload to Soundiiz (soundiiz.com) to create a YouTube Music playlist")

        # Full details CSV with YouTube Music URLs
        full_path = output_path.with_name(output_path.stem + "-missing-full.csv")
        with open(full_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Artist", "Title", "Year", "YouTube Music URL"])
            for song in missing_songs:
                yt_music_url = youtube_to_music_url(song["url"])
                writer.writerow([song["artist"], song["title"], song["year"], yt_music_url])

        print(f"\nFull details CSV saved to: {full_path}")
        print("  -> Contains YouTube Music URLs for playlist creation")

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

            print(f"[{i + 1}/{len(missing_songs)}] Downloading: {song['artist']} - {song['title']}... ", end="", flush=True)

            result = download_song(song["url"], song["artist"], song["title"], song["year"], download_dir, args.cookies, args.debug)
            if result is None:
                print("SKIPPED (already exists)")
                skipped += 1
            elif result:
                print("OK")
                downloaded += 1
            else:
                print("FAILED")
                failed += 1

        print(f"\nDownload complete: {downloaded} succeeded, {skipped} skipped, {failed} failed")
        print(f"Files saved to: {download_dir.resolve()}")

    # Print summary
    print(f"\n{'=' * 40}")
    print("Results:")
    print(f"  Found in Plex: {found}")
    print(f"  Not found:     {not_found}")
    print(f"  Total:         {len(songs)}")
    print(f"  Match rate:    {(found / len(songs) * 100):.1f}%")
    print(f"\nMapping saved to: {output_path}")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()
