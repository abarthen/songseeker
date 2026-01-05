#!/usr/bin/env python3
"""
Custom Game Creator for SongSeeker

Creates custom Hitster-style games from a list of Plex rating keys.
Generates mapping files, updates the manifest, and creates printable PDF cards.

Usage:
    poetry run custom-game --name "80s Classics" --mapping "80s-classics" --keys "12345,67890" --cards-pdf cards.pdf
    poetry run custom-game --name "Party Mix" --mapping "party-mix" --keys rating-keys.txt --cards-pdf cards.pdf
"""

import argparse
import hashlib
import json
import os
import sys
import textwrap
from io import BytesIO
from pathlib import Path

import qrcode
import requests
from PIL import Image
from qrcode.image.styledpil import StyledPilImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from .plex_api import fetch_plex_track, load_plex_config, list_plex_playlists, get_playlist_tracks, load_date_remapper


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create custom SongSeeker games from Plex rating keys or playlists"
    )
    parser.add_argument(
        "--name", "-n", help="Game name for display (e.g., '80s Classics')"
    )
    parser.add_argument(
        "--mapping", "-m", help="Mapping identifier (e.g., '80s-classics')"
    )
    parser.add_argument(
        "--extend", "-e", help="Path to existing mapping JSON to extend (skips existing songs)"
    )
    parser.add_argument(
        "--keys", "-k", help="Comma-separated rating keys OR path to file with one key per line"
    )
    parser.add_argument(
        "--playlist", "-P", help="Plex playlist name or ratingKey to use as source"
    )
    parser.add_argument(
        "--list-playlists", "-L", action="store_true", help="List available Plex playlists and exit"
    )
    parser.add_argument(
        "--output-dir", "-o", default=".", help="Directory to save mapping JSON (default: current directory)"
    )
    parser.add_argument(
        "--cards-pdf", "-p", help="Output PDF path for generated cards"
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
        "--icon", help="Path or URL to icon to embed in QR codes (max 300x300px, transparent background)"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Enable debug output"
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


def parse_keys(keys_arg: str) -> list[str]:
    """Parse rating keys from argument (file path or comma-separated string)."""
    keys_path = Path(keys_arg)

    if keys_path.exists() and keys_path.is_file():
        # Read from file (one key per line)
        with open(keys_path, "r", encoding="utf-8") as f:
            keys = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    else:
        # Treat as comma-separated string
        keys = [k.strip() for k in keys_arg.split(",") if k.strip()]

    return keys


def update_manifest(manifest_path: Path, mapping_name: str, game_name: str, tracks: list[dict]) -> None:
    """Add custom game to plex-manifest.json."""
    # Load existing manifest or create new
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"games": []}

    # Ensure games is a list (migrate from old format if needed)
    if "games" not in manifest or not isinstance(manifest.get("games"), list):
        manifest = {"games": []}

    # Calculate min/max years from tracks
    years = [t.get("year") for t in tracks if t.get("year")]
    min_date = min(years) if years else None
    max_date = max(years) if years else None

    # Build new game entry
    game_obj = {
        "mapping": mapping_name,
        "name": game_name,
        "matchRate": 100.0,
    }
    if min_date is not None:
        game_obj["minDate"] = min_date
    if max_date is not None:
        game_obj["maxDate"] = max_date

    # Find and update existing entry, or add new one
    existing_idx = next((i for i, g in enumerate(manifest["games"]) if g.get("mapping") == mapping_name), None)
    if existing_idx is not None:
        manifest["games"][existing_idx] = game_obj
    else:
        manifest["games"].append(game_obj)

    # Sort by mapping name
    manifest["games"].sort(key=lambda g: g.get("mapping", ""))

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


# --- Card Generation Functions (ported from songseeker-card-generator) ---

def generate_qr_code(data: str, file_path: str, icon_path: str = None, icon_cache: dict = None) -> None:
    """Generate QR code image and save to file."""
    if icon_cache is None:
        icon_cache = {}

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    if icon_path is None:
        img = qr.make_image(fill_color="black", back_color="white")
    else:
        if icon_path.startswith("http"):
            if icon_path not in icon_cache:
                response = requests.get(icon_path)
                icon_cache[icon_path] = BytesIO(response.content)
            icon_image = icon_cache[icon_path]
            img = qr.make_image(image_factory=StyledPilImage, embeded_image_path=icon_image)
        else:
            img = qr.make_image(image_factory=StyledPilImage, embeded_image_path=icon_path)

    img.save(file_path)


def add_qr_code_to_canvas(c: canvas.Canvas, data: str, position: tuple, box_size: float,
                          icon_path: str = None, game_name: str = None, rating_key: str = None) -> None:
    """Generate QR code and draw it on the canvas with border and labels."""
    hash_object = hashlib.sha256(data.encode())
    hex_dig = hash_object.hexdigest()

    qr_code_path = f"qr_{hex_dig}.png"
    generate_qr_code(data, qr_code_path, icon_path)

    x, y = position
    c.drawImage(qr_code_path, x, y, width=box_size, height=box_size)

    os.remove(qr_code_path)

    # Draw border
    c.rect(x, y, box_size, box_size)

    # Draw corner labels
    font_label = "Helvetica"
    font_size_label = 8
    label_margin = 4
    c.setFont(font_label, font_size_label)
    c.setFillColorRGB(0, 0, 0)

    # Game name in lower left
    if game_name:
        c.drawString(x + label_margin, y + label_margin, game_name)

    # Rating key in lower right
    if rating_key:
        key_text = str(rating_key)
        key_width = c.stringWidth(key_text, font_label, font_size_label)
        c.drawString(x + box_size - key_width - label_margin, y + label_margin, key_text)


def add_text_box(c: canvas.Canvas, track: dict, position: tuple, box_size: float,
                 game_name: str = None) -> None:
    """Draw card back with artist, title, year, and corner labels."""
    x, y = position
    text_indent = 8

    # Font settings
    font_artist = "Helvetica-Bold"
    font_size_artist = 14
    font_title = "Helvetica"
    font_size_title = 14
    font_year = "Helvetica-Bold"
    font_size_year = 50
    text_margin = 5

    # Set font color to black
    c.setFillColorRGB(0, 0, 0)

    # Draw corner labels
    font_label = "Helvetica"
    font_size_label = 8
    label_margin = 4

    # Game name in lower left
    if game_name:
        c.setFont(font_label, font_size_label)
        c.drawString(x + label_margin, y + label_margin, game_name)

    # Rating key in lower right
    rating_key = track.get("ratingKey", "")
    if rating_key:
        key_text = str(rating_key)
        c.setFont(font_label, font_size_label)
        key_width = c.stringWidth(key_text, font_label, font_size_label)
        c.drawString(x + box_size - key_width - label_margin, y + label_margin, key_text)

    # Draw artist (top, centered)
    artist = track.get("artist", "Unknown Artist")
    if artist:
        artist_lines = textwrap.wrap(artist, width=20)
        artist_y = y + box_size - (text_indent + font_size_artist)

        for line in artist_lines:
            artist_x = x + (box_size - c.stringWidth(line, font_artist, font_size_artist)) / 2
            c.setFont(font_artist, font_size_artist)
            c.drawString(artist_x, artist_y, line)
            artist_y -= text_margin + font_size_artist

    # Draw year (center, large)
    year = str(track.get("year", ""))
    if year:
        year_x = x + (box_size - c.stringWidth(year, font_year, font_size_year)) / 2
        year_y = y + box_size / 2 - font_size_year / 4
        c.setFont(font_year, font_size_year)
        c.drawString(year_x, year_y, year)

    # Draw title (bottom, centered)
    title = track.get("title", "Unknown Title")
    if title:
        title_lines = textwrap.wrap(title, width=20)
        title_y = y + (len(title_lines) - 1) * (text_margin + font_size_title) + font_size_title / 2 + text_indent

        for line in title_lines:
            title_x = x + (box_size - c.stringWidth(line, font_title, font_size_title)) / 2
            c.setFont(font_title, font_size_title)
            c.drawString(title_x, title_y, line)
            title_y -= text_margin + font_size_title


def generate_cards_pdf(tracks: list[dict], output_path: str, icon_path: str = None,
                       game_name: str = None) -> None:
    """Generate PDF with QR code cards (front) and info cards (back)."""
    c = canvas.Canvas(output_path, pagesize=A4)
    page_width, page_height = A4

    box_size = 6.5 * cm
    boxes_per_row = int(page_width // box_size)
    boxes_per_column = int(page_height // box_size)
    boxes_per_page = boxes_per_row * boxes_per_column
    vpageindent = 0.8 * cm
    hpageindent = (page_width - (box_size * boxes_per_row)) / 2

    for i in range(0, len(tracks), boxes_per_page):
        # Page 1: QR codes (front)
        for index in range(i, min(i + boxes_per_page, len(tracks))):
            track = tracks[index]
            position_index = index % boxes_per_page
            column_index = position_index % boxes_per_row
            row_index = position_index // boxes_per_row
            x = hpageindent + (column_index * box_size)
            y = page_height - vpageindent - (row_index + 1) * box_size

            # QR code contains "plex:{ratingKey}"
            qr_data = f"plex:{track['ratingKey']}"
            add_qr_code_to_canvas(c, qr_data, (x, y), box_size, icon_path,
                                  game_name=game_name, rating_key=track['ratingKey'])

        c.showPage()

        # Page 2: Text info (back, mirrored for double-sided printing)
        for index in range(i, min(i + boxes_per_page, len(tracks))):
            track = tracks[index]
            position_index = index % boxes_per_page
            # Mirror horizontally for back side
            column_index = (boxes_per_row - 1) - position_index % boxes_per_row
            row_index = position_index // boxes_per_row
            x = hpageindent + (column_index * box_size)
            y = page_height - vpageindent - (row_index + 1) * box_size

            add_text_box(c, track, (x, y), box_size, game_name=game_name)

        c.showPage()

    c.save()


def main():
    args = parse_args()

    # Load date remapper (for overriding years from best-of albums etc.)
    load_date_remapper()

    # Normalize server URL
    server_url = args.server.rstrip("/")

    # Handle --list-playlists mode
    if args.list_playlists:
        print("Fetching playlists from Plex...\n")
        playlists = list_plex_playlists(server_url, args.token, args.debug)
        if not playlists:
            print("No audio playlists found.")
            sys.exit(0)

        print(f"{'ratingKey':<12} {'Tracks':<8} Title")
        print("-" * 60)
        for pl in playlists:
            print(f"{pl['ratingKey']:<12} {pl['leafCount']:<8} {pl['title']}")
        sys.exit(0)

    # Handle extend mode vs create mode
    existing_mapping = {}
    existing_tracks = []
    extend_mode = False

    if args.extend:
        extend_mode = True
        extend_path = Path(args.extend)
        if not extend_path.exists():
            print(f"Error: File not found: {args.extend}")
            sys.exit(1)

        # Load existing mapping
        with open(extend_path, "r", encoding="utf-8") as f:
            existing_mapping = json.load(f)

        # Extract mapping_id from filename (e.g., plex-mapping-de-custom.json -> de-custom)
        filename = extend_path.name
        if filename.startswith("plex-mapping-") and filename.endswith(".json"):
            mapping_id = filename[len("plex-mapping-"):-len(".json")]
        else:
            print(f"Error: Cannot extract mapping ID from filename: {filename}")
            print("Expected format: plex-mapping-{id}.json")
            sys.exit(1)

        # Get game name from manifest or --name
        output_dir = extend_path.parent
        manifest_path = output_dir / "plex-manifest.json"
        game_name = args.name
        if not game_name and manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            game_name = manifest.get("games", {}).get(mapping_id)

        if not game_name:
            print("Error: --name is required when extending (or game must exist in manifest)")
            sys.exit(1)

        # Build list of existing tracks for full PDF
        existing_tracks = list(existing_mapping.values())
        print(f"Extending existing mapping: {extend_path}")
        print(f"  Existing tracks: {len(existing_mapping)}")

    else:
        # Create mode - validate required arguments
        if not args.name:
            print("Error: --name is required")
            sys.exit(1)
        if not args.mapping:
            print("Error: --mapping is required")
            sys.exit(1)

        game_name = args.name
        mapping_id = args.mapping if args.mapping.startswith("de-") else f"de-{args.mapping}"
        output_dir = Path(args.output_dir)

    if not args.cards_pdf:
        print("Error: --cards-pdf is required")
        sys.exit(1)
    if not args.keys and not args.playlist:
        print("Error: Either --keys or --playlist is required")
        sys.exit(1)

    # Get rating keys from playlist or direct input
    if args.playlist:
        print(f"Fetching tracks from playlist: {args.playlist}")
        playlists = list_plex_playlists(server_url, args.token, args.debug)

        # Find playlist by name or ratingKey
        playlist_key = None
        for pl in playlists:
            if pl['ratingKey'] == args.playlist or pl['title'].lower() == args.playlist.lower():
                playlist_key = pl['ratingKey']
                print(f"Found playlist: {pl['title']} ({pl['leafCount']} tracks)")
                break

        if not playlist_key:
            print(f"Error: Playlist '{args.playlist}' not found")
            print("\nAvailable playlists:")
            for pl in playlists:
                print(f"  {pl['ratingKey']}: {pl['title']}")
            sys.exit(1)

        keys = get_playlist_tracks(server_url, args.token, playlist_key, args.debug)
        if not keys:
            print("Error: No tracks found in playlist")
            sys.exit(1)
        print(f"Retrieved {len(keys)} rating keys from playlist")
    else:
        # Parse rating keys from --keys argument
        keys = parse_keys(args.keys)
        if not keys:
            print("Error: No rating keys provided")
            sys.exit(1)

    # Filter out existing keys in extend mode
    if extend_mode:
        original_count = len(keys)
        keys = [k for k in keys if k not in existing_mapping]
        skipped_existing = original_count - len(keys)
        if skipped_existing > 0:
            print(f"Skipping {skipped_existing} tracks already in mapping")
        if not keys:
            print("\nNo new tracks to add. Mapping is already up to date.")
            sys.exit(0)

    print(f"\n{'Extending' if extend_mode else 'Creating'} custom game: {game_name}")
    print(f"Mapping identifier: {mapping_id}")
    print(f"Processing {len(keys)} {'new ' if extend_mode else ''}rating keys...\n")

    # Fetch metadata for each key
    new_mapping = {}
    new_tracks = []
    skipped = 0

    for i, key in enumerate(keys):
        print(f"[{i + 1}/{len(keys)}] Fetching key {key}... ", end="", flush=True)

        track = fetch_plex_track(server_url, args.token, key, args.debug)

        if track:
            # Use rating key as both key and ratingKey value
            new_mapping[key] = track
            new_tracks.append(track)
            print(f"OK ({track['artist']} - {track['title']})")
        else:
            print("SKIPPED (not found)")
            skipped += 1

    if not new_tracks and not existing_tracks:
        print("\nError: No valid tracks found. Cannot create game.")
        sys.exit(1)

    # Merge mappings
    final_mapping = {**existing_mapping, **new_mapping}
    all_tracks = existing_tracks + new_tracks

    # Write mapping file
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / f"plex-mapping-{mapping_id}.json"

    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(final_mapping, f, indent=2)

    print(f"\nMapping saved to: {mapping_path}")

    # Update manifest
    manifest_path = output_dir / "plex-manifest.json"
    update_manifest(manifest_path, mapping_id, game_name, all_tracks)
    print(f"Manifest updated: {manifest_path}")

    # Generate cards PDFs
    if extend_mode and new_tracks:
        # Generate both full and new-only PDFs
        base_pdf = Path(args.cards_pdf)
        full_pdf = base_pdf.with_stem(f"{base_pdf.stem}-full")
        new_pdf = base_pdf.with_stem(f"{base_pdf.stem}-new")

        print(f"\nGenerating full PDF ({len(all_tracks)} cards): {full_pdf}")
        generate_cards_pdf(all_tracks, str(full_pdf), args.icon, game_name=game_name)

        print(f"Generating new-only PDF ({len(new_tracks)} cards): {new_pdf}")
        generate_cards_pdf(new_tracks, str(new_pdf), args.icon, game_name=game_name)

        cards_summary = f"\n  Full PDF: {full_pdf}\n  New-only PDF: {new_pdf}"
    else:
        print(f"\nGenerating cards PDF: {args.cards_pdf}")
        generate_cards_pdf(all_tracks if extend_mode else new_tracks, args.cards_pdf, args.icon, game_name=game_name)
        cards_summary = f"\n  Cards PDF: {args.cards_pdf}"

    # Summary
    print(f"\n{'=' * 40}")
    print(f"Custom game {'extended' if extend_mode else 'created'} successfully!")
    print(f"  Game name: {game_name}")
    if extend_mode:
        print(f"  Existing tracks: {len(existing_tracks)}")
        print(f"  New tracks: {len(new_tracks)}")
        print(f"  Total tracks: {len(all_tracks)}")
    else:
        print(f"  Tracks: {len(new_tracks)}")
    if skipped > 0:
        print(f"  Skipped: {skipped} (invalid keys)")
    print(f"  Mapping: {mapping_path}")
    print(cards_summary)
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()
