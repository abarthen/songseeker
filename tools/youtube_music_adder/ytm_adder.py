#!/usr/bin/env python3
"""
YouTube Music Playlist Adder

Automates adding songs/albums to a YouTube Music playlist using ISRC codes from CSV files.

Prerequisites:
    1. Start Brave with remote debugging:
       "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222
    2. Log into YouTube Music in that browser window

Usage:
    # Verify connection
    poetry run ytm-adder --login

    # Process a CSV file
    poetry run ytm-adder --csv path/to/hitster-de-aaaa0019.csv --playlist "#3"

    # Resume from a specific card number
    poetry run ytm-adder --csv path/to/hitster-de-aaaa0019.csv --playlist "#3" --start-from 50
"""

import argparse
import csv
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Path to store browser state (cookies, localStorage, etc.)
# Use actual Chrome profile to avoid Google's automation detection
CHROME_USER_DATA = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
PROGRESS_FILE = Path(__file__).parent / "progress.json"

# Browser executable paths (Windows) - tried in order
BROWSER_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# Delays to avoid rate limiting (in seconds)
DELAY_BETWEEN_SONGS = 2.0  # Between processing each song
DELAY_AFTER_ACTION = 0.75  # After each UI action (click, etc.)
DELAY_PAGE_LOAD = 1.25     # After page navigation


def load_progress() -> dict:
    """Load progress from previous runs."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"processed_isrcs": [], "added_albums": [], "not_found": []}


def save_progress(progress: dict) -> None:
    """Save progress to file."""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def get_browser_context(playwright, headless: bool = False):
    """Connect to Brave running with remote debugging."""
    # Connect to existing Brave instance with remote debugging
    print("Connecting to Brave on port 9222...")

    try:
        browser = playwright.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]  # Use the default context
        print(f"Connected! Found {len(context.pages)} open tabs.")
        return context
    except Exception as e:
        print(f"\nError: Could not connect to Brave.")
        print(f"Details: {e}")
        print("\nPlease start Brave with remote debugging:")
        print('  "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222')
        print("\nThen run this script again.")
        raise


def login_flow() -> None:
    """Verify connection to Brave and YouTube Music access."""
    print("Verifying connection to Brave...")

    with sync_playwright() as p:
        context = get_browser_context(p, headless=False)
        # Create a new tab and navigate to YouTube Music
        page = context.new_page()
        print(f"Navigating to YouTube Music...")
        page.goto("https://music.youtube.com/", wait_until="domcontentloaded")
        print(f"Page loaded: {page.url}")
        print("\nSuccess! You can now run the script with --csv to process songs.")
        print("Press Enter to close this tab...")
        input()
        page.close()


def read_csv_isrcs(csv_path: Path) -> list[dict]:
    """Read ISRC codes and metadata from CSV file."""
    entries = []
    with open(csv_path, "r", encoding="utf-8") as f:
        # Skip the separator line if present
        first_line = f.readline()
        if not first_line.startswith("sep="):
            f.seek(0)

        reader = csv.DictReader(f)
        for row in reader:
            isrc = row.get("ISRC", "").strip()
            if isrc:
                entries.append({
                    "card": row.get("Card#", ""),
                    "title": row.get("Title", ""),
                    "artist": row.get("Artist", ""),
                    "year": row.get("Year", ""),
                    "isrc": isrc,
                })
    return entries


def add_songs_to_playlist(
    csv_path: Path,
    playlist_name: str,
    start_from: int = 1,
    headless: bool = False,
    dry_run: bool = False,
) -> None:
    """Main automation flow to add songs/albums to playlist."""

    entries = read_csv_isrcs(csv_path)
    print(f"Found {len(entries)} entries with ISRC codes in {csv_path.name}")

    progress = load_progress()

    with sync_playwright() as p:
        context = get_browser_context(p, headless=headless)
        # Create a new tab for automation
        page = context.new_page()

        # Navigate to YouTube Music to verify login
        print("Navigating to YouTube Music...")
        page.goto("https://music.youtube.com/", wait_until="domcontentloaded")
        print(f"Page loaded: {page.url}")
        time.sleep(DELAY_PAGE_LOAD)

        for entry in entries:
            card_num = int(entry["card"]) if entry["card"].isdigit() else 0
            if card_num < start_from:
                continue

            isrc = entry["isrc"]
            if isrc in progress["processed_isrcs"]:
                print(f"[{entry['card']}] Already processed: {entry['artist']} - {entry['title']}")
                continue

            print(f"\n[{entry['card']}] Processing: {entry['artist']} - {entry['title']} (ISRC: {isrc})")

            if dry_run:
                print("  [DRY RUN] Would search and add to playlist")
                continue

            try:
                result = process_single_track(page, entry, playlist_name, progress)
                # Only mark as processed if successfully added or definitively not found
                if result is True or result == "not_found":
                    progress["processed_isrcs"].append(isrc)
                    # Track not-found entries separately for manual lookup
                    if result == "not_found":
                        progress.setdefault("not_found", []).append({
                            "card": entry["card"],
                            "artist": entry["artist"],
                            "title": entry["title"],
                            "year": entry["year"],
                            "isrc": isrc,
                        })
                    save_progress(progress)
                else:
                    # False means a transient error (timeout, etc.) - don't mark as processed
                    print(f"  Will retry on next run")
            except Exception as e:
                print(f"  Error: {e}")
                import traceback
                traceback.print_exc()
                save_progress(progress)

            time.sleep(DELAY_BETWEEN_SONGS)

        print("\n\nDone! Close the browser window to exit.")
        try:
            while browser.pages:
                time.sleep(1)
        except Exception:
            pass


def process_single_track(page, entry: dict, playlist_name: str, progress: dict) -> bool:
    """Process a single track: search, check album artist, add to playlist."""
    isrc = entry["isrc"]

    # Search for the ISRC
    search_url = f"https://music.youtube.com/search?q={isrc}"
    page.goto(search_url)
    time.sleep(DELAY_PAGE_LOAD)

    # Wait for search results or "no results" message
    try:
        # Wait for either results or the "no results" message
        page.wait_for_selector(
            "ytmusic-card-shelf-renderer, ytmusic-message-renderer",
            timeout=5000
        )

        # Check if we have actual results (card shelf takes priority)
        has_results = page.query_selector("ytmusic-card-shelf-renderer")
        if not has_results:
            # No card shelf found - check if it's the "no results" message
            print(f"  NOT FOUND: No results on YouTube Music for ISRC {isrc}")
            return "not_found"

    except PlaywrightTimeout:
        print(f"  TIMEOUT: Search timed out for ISRC: {isrc}")
        return False

    # Click the 3-dot "Action menu" button on the search results page
    # This should be available without navigating away
    try:
        menu_button = page.wait_for_selector('button[aria-label="Action menu"]', timeout=3000)
        menu_button.click()
        time.sleep(DELAY_AFTER_ACTION)

        # Click "Go to album" in the dropdown
        go_to_album = page.wait_for_selector(
            "ytmusic-menu-navigation-item-renderer:has-text('Go to album')",
            timeout=2000
        )
        go_to_album.click()
        time.sleep(DELAY_PAGE_LOAD)
    except PlaywrightTimeout:
        # No album link - add song directly from search results
        page.keyboard.press("Escape")
        time.sleep(DELAY_AFTER_ACTION)
        print(f"  No album found - adding song only")
        return add_song_to_playlist_direct(page, playlist_name)

    # Check if album artist is "Various Artists"
    try:
        album_artist_el = page.query_selector(
            "yt-formatted-string.strapline-text.ytmusic-responsive-header-renderer"
        )
        album_artist = album_artist_el.inner_text() if album_artist_el else ""
    except Exception:
        album_artist = ""

    if album_artist.lower() == "various artists":
        print(f"  Various Artists album - adding song only")
        # Go back to search results
        page.go_back()
        time.sleep(DELAY_PAGE_LOAD)
        return add_song_to_playlist_direct(page, playlist_name)
    else:
        # Add the whole album
        album_id = page.url
        if album_id in progress["added_albums"]:
            print(f"  Album already added: {album_artist}")
            return True

        print(f"  Adding album by: {album_artist}")
        result = add_album_to_playlist(page, playlist_name)
        if result:
            progress["added_albums"].append(album_id)
        return result


def add_song_to_playlist_direct(page, playlist_name: str) -> bool:
    """Add a single song using the direct 'Save to playlist' button on the card."""
    try:
        # Find the card shelf result
        first_song = page.query_selector("ytmusic-card-shelf-renderer")
        if not first_song:
            print(f"  Could not find song card to add")
            return False

        # The "Save" button has aria-label="Save to playlist"
        save_btn = first_song.query_selector('button[aria-label="Save to playlist"]')
        if save_btn:
            save_btn.click()
            time.sleep(DELAY_AFTER_ACTION)
            return select_playlist(page, playlist_name)

        print(f"  Could not find Save to playlist button")
        return False

    except Exception as e:
        print(f"  Error adding song: {e}")
        return False


def add_album_to_playlist(page, playlist_name: str) -> bool:
    """Add the current album to playlist via three dots menu."""
    try:
        # Click the 3-dot "Action menu" button specifically (not download button)
        three_dots = page.wait_for_selector('button[aria-label="Action menu"]', timeout=3000)
        three_dots.click()
        time.sleep(DELAY_AFTER_ACTION)

        # Click "Save to playlist"
        save_to_playlist = page.wait_for_selector(
            "ytmusic-menu-navigation-item-renderer:has-text('Save to playlist')",
            timeout=2000
        )
        save_to_playlist.click()
        time.sleep(DELAY_AFTER_ACTION)

        return select_playlist(page, playlist_name)

    except PlaywrightTimeout as e:
        print(f"  Timeout while adding album: {e}")
        return False


def select_playlist(page, playlist_name: str) -> bool:
    """Select a playlist from the dialog and handle duplicates."""
    try:
        # Wait for playlist dialog
        playlist_option = page.wait_for_selector(
            f"yt-formatted-string#title:has-text('{playlist_name}')",
            timeout=3000
        )
        playlist_option.click()
        time.sleep(DELAY_AFTER_ACTION)

        # Check for duplicates dialog
        try:
            duplicates_dialog = page.wait_for_selector(
                "yt-confirm-dialog-renderer:has-text('Duplicates')",
                timeout=1000
            )
            if duplicates_dialog:
                # Click the skip/cancel button (first button typically)
                skip_btn = duplicates_dialog.query_selector("yt-button-renderer button")
                if skip_btn:
                    skip_btn.click()
                    time.sleep(DELAY_AFTER_ACTION)
                    print(f"  (skipped duplicates)")
        except PlaywrightTimeout:
            # No duplicates dialog, that's fine
            pass

        print(f"  Added to playlist '{playlist_name}'")
        return True

    except PlaywrightTimeout as e:
        print(f"  Timeout selecting playlist: {e}")
        return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Add songs/albums to YouTube Music playlist using ISRC codes"
    )

    parser.add_argument(
        "--login",
        action="store_true",
        help="Open browser for manual login (run this first)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="CSV file containing ISRC codes",
    )
    parser.add_argument(
        "--playlist",
        default="#3",
        help="Playlist name to add songs to (default: '#3')",
    )
    parser.add_argument(
        "--start-from",
        type=int,
        default=1,
        help="Start from this card number (skip earlier entries)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible window)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually add to playlist, just show what would be done",
    )
    parser.add_argument(
        "--clear-progress",
        action="store_true",
        help="Clear saved progress and start fresh",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.clear_progress and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print("Progress cleared.")

    if args.login:
        login_flow()
    elif args.csv:
        if not args.csv.exists():
            print(f"Error: CSV file not found: {args.csv}")
            return
        add_songs_to_playlist(
            args.csv,
            args.playlist,
            args.start_from,
            args.headless,
            args.dry_run,
        )
    else:
        print("Usage: poetry run ytm-adder --login  (first time)")
        print("       poetry run ytm-adder --csv <file.csv> --playlist '#3'")


if __name__ == "__main__":
    main()
