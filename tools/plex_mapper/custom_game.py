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

from .plex_api import fetch_plex_track, load_plex_config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create custom SongSeeker games from Plex rating keys"
    )
    parser.add_argument(
        "--name", "-n", required=True, help="Game name for display (e.g., '80s Classics')"
    )
    parser.add_argument(
        "--mapping", "-m", required=True, help="Mapping identifier (e.g., '80s-classics')"
    )
    parser.add_argument(
        "--keys", "-k", required=True, help="Comma-separated rating keys OR path to file with one key per line"
    )
    parser.add_argument(
        "--output-dir", "-o", default=".", help="Directory to save mapping JSON (default: current directory)"
    )
    parser.add_argument(
        "--cards-pdf", "-p", required=True, help="Output PDF path for generated cards"
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


def update_manifest(manifest_path: Path, mapping_name: str, game_name: str) -> None:
    """Add custom game to plex-manifest.json."""
    # Load existing manifest or create new
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {"mappings": [], "games": {}, "matchRates": {}}

    # Add/update the custom game
    if mapping_name not in manifest["mappings"]:
        manifest["mappings"].append(mapping_name)
        manifest["mappings"].sort()

    manifest["games"][mapping_name] = game_name
    manifest["matchRates"][mapping_name] = 100.0

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

    # Normalize server URL
    server_url = args.server.rstrip("/")

    # Parse rating keys
    keys = parse_keys(args.keys)
    if not keys:
        print("Error: No rating keys provided")
        sys.exit(1)

    print(f"Creating custom game: {args.name}")
    print(f"Mapping identifier: {args.mapping}")
    print(f"Processing {len(keys)} rating keys...\n")

    # Fetch metadata for each key
    mapping = {}
    tracks = []
    skipped = 0

    for i, key in enumerate(keys):
        print(f"[{i + 1}/{len(keys)}] Fetching key {key}... ", end="", flush=True)

        track = fetch_plex_track(server_url, args.token, key, args.debug)

        if track:
            # Use rating key as both key and ratingKey value
            mapping[key] = track
            tracks.append(track)
            print(f"OK ({track['artist']} - {track['title']})")
        else:
            print("SKIPPED (not found)")
            skipped += 1

    if not tracks:
        print("\nError: No valid tracks found. Cannot create game.")
        sys.exit(1)

    # Write mapping file
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / f"plex-mapping-{args.mapping}.json"

    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    print(f"\nMapping saved to: {mapping_path}")

    # Update manifest
    manifest_path = output_dir / "plex-manifest.json"
    update_manifest(manifest_path, args.mapping, args.name)
    print(f"Manifest updated: {manifest_path}")

    # Generate cards PDF
    print(f"\nGenerating cards PDF: {args.cards_pdf}")
    generate_cards_pdf(tracks, args.cards_pdf, args.icon, game_name=args.name)

    # Summary
    print(f"\n{'=' * 40}")
    print(f"Custom game created successfully!")
    print(f"  Game name: {args.name}")
    print(f"  Tracks: {len(tracks)}")
    if skipped > 0:
        print(f"  Skipped: {skipped} (invalid keys)")
    print(f"  Mapping: {mapping_path}")
    print(f"  Cards PDF: {args.cards_pdf}")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()
