#!/usr/bin/env python3
"""
Trigger Plex library scan on specific folders.

This is much faster than a full library scan when adding individual files.
"""

import argparse
import sys
import urllib.parse
from pathlib import Path

from .plex_api import load_plex_config, plex_request


def get_sections(server_url: str, token: str) -> list[dict]:
    """Get all library sections with their IDs, names, types, and root paths."""
    try:
        response = plex_request(f"{server_url}/library/sections", token)
        sections = response.get("MediaContainer", {}).get("Directory", [])

        result = []
        for section in sections:
            locations = section.get("Location", [])
            root_path = locations[0].get("path") if locations else None
            result.append({
                "id": section.get("key"),
                "title": section.get("title"),
                "type": section.get("type"),
                "root": root_path,
            })
        return result
    except Exception as e:
        print(f"Error getting sections: {e}")
        return []


def scan_path(server_url: str, token: str, section_id: str, path: str, debug: bool = False, force: bool = False) -> bool:
    """Trigger a scan on a specific path."""
    try:
        import requests

        # Build URL with path as query parameter
        url = f"{server_url}/library/sections/{section_id}/refresh"
        headers = {"Accept": "application/json"}
        params = {
            "path": path,
            "X-Plex-Token": token,
        }
        # force=1 makes Plex rescan even if directory timestamp hasn't changed
        # but can cause broader rescans, so only use when needed
        if force:
            params["force"] = "1"

        if debug:
            print(f"\n  DEBUG: GET {url}")
            print(f"  DEBUG: params={params}")

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if debug:
            print(f"  DEBUG: Response status={response.status_code}")

        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error triggering scan: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Trigger Plex library scan on specific folders"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Path(s) to scan (relative to library root or absolute)",
    )
    parser.add_argument(
        "--config",
        default="../plex-config.json",
        help="Path to plex-config.json (default: ../plex-config.json)",
    )
    parser.add_argument(
        "--section",
        "-s",
        help="Library section ID or name (auto-detected if only one library exists)",
    )
    parser.add_argument(
        "--list-sections",
        "-l",
        action="store_true",
        help="List all library sections and exit",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug output",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force rescan even if Plex thinks nothing changed (use sparingly)",
    )

    args = parser.parse_args()

    # Load Plex config
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).parent.parent / args.config

    server_url, token = load_plex_config(config_path)
    if not server_url or not token:
        print(f"Error: Could not load Plex config from {config_path}")
        sys.exit(1)

    # Get all sections
    sections = get_sections(server_url, token)
    if not sections:
        print("Error: No library sections found")
        sys.exit(1)

    # List sections mode
    if args.list_sections:
        print("Library sections:")
        for section in sections:
            print(f"  [{section['id']}] {section['title']} ({section['type']})")
            if section['root']:
                print(f"      {section['root']}")
        return

    # Validate paths are provided for scan mode
    if not args.paths:
        print("Error: At least one path is required")
        sys.exit(1)

    # Find section to use
    section = None
    if args.section:
        # Find by ID or name
        for s in sections:
            if s['id'] == args.section or s['title'].lower() == args.section.lower():
                section = s
                break
        if not section:
            print(f"Error: Section '{args.section}' not found")
            print("\nAvailable sections:")
            for s in sections:
                print(f"  [{s['id']}] {s['title']} ({s['type']})")
            sys.exit(1)
    elif len(sections) == 1:
        section = sections[0]
    else:
        print("Error: Multiple libraries found. Use --section to specify which one:")
        for s in sections:
            print(f"  [{s['id']}] {s['title']} ({s['type']})")
        sys.exit(1)

    print(f"Using [{section['id']}] {section['title']} (root: {section['root']})")

    # Scan each path
    success_count = 0
    for path in args.paths:
        # If path is relative and we know the library root, make it absolute
        library_root = section['root']
        if library_root and not path.startswith("/") and not path.startswith("\\"):
            full_path = f"{library_root}/{path}"
        else:
            full_path = path

        print(f"Scanning: {full_path}... ", end="", flush=True)
        if scan_path(server_url, token, section['id'], full_path, args.debug, args.force):
            print("OK")
            success_count += 1
        else:
            print("FAILED")

    print(f"\nScanned {success_count}/{len(args.paths)} paths")


if __name__ == "__main__":
    main()
