# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Structure

This project uses a multi-folder workspace with two git repositories:
- `c:\Users\andreas\Projects\songseeker\` - Main web application (this repo)
- `c:\Users\andreas\Projects\songseeker-hitster-playlists\` - CSV playlist files mapping Hitster card IDs to YouTube URLs

## Project Overview

SongSeeker is a music guessing game web application inspired by Hitster and Rockster. Players scan QR codes containing song links, and the app plays the audio via Plex while hiding song info for guessing.

Live demo: https://songseeker.grub3r.io/

## Development

This is a static web app with no build system. To develop locally:

1. Serve the files over HTTPS (required for camera/QR scanning)
2. Open index.html in a browser

## Docker Build

```bash
docker build -t songseeker -f imagebuild/Dockerfile \
  --secret id=github_token,src=/path/to/.github_token .
```

Or inline (token not stored in image):
```bash
echo "ghp_your_token" | docker build -t songseeker -f imagebuild/Dockerfile \
  --secret id=github_token,src=/dev/stdin .
```

The Docker image uses nginx to serve the app. Plex mapping files (`plex-manifest.json`, `plex-mapping-*.json`) are cloned from [songseeker-plex-lists](https://github.com/abarthen/songseeker-plex-lists) during build and copied to `/plex-data/` at startup if not already present.

**Build secrets:**
- `github_token` - GitHub Personal Access Token (required for private repo, needs `repo` or `Contents: read` scope)

**Build args (optional):**
- `PLEX_LISTS_REPO` - Override repository URL
- `PLEX_LISTS_BRANCH` - Override branch (default: main)

**Runtime behavior**: On container start, any mapping files not present in `/plex-data/` are automatically copied from the built-in defaults. This allows the volume mount to overlay `/plex-data/` while still providing default mapping files.

### Authentication

The deployed site uses cookie-based authentication with a proper login page (password manager friendly).

**Components:**
- `login.html` - Login page with form
- `imagebuild/auth_server.py` - Python auth server that validates credentials and issues session cookies
- Credentials stored in htpasswd format

**Setup:**
1. Generate htpasswd: `htpasswd -c .htpasswd username`
2. Generate cookie secret: `openssl rand -hex 32 > .cookie_secret`

**Required mounts:**
- `.htpasswd` → `/etc/nginx/.htpasswd`
- `.cookie_secret` → `/etc/nginx/.cookie_secret`
- `plex-config.json` → `/plex-data/plex-config.json`

**Session cookies** are valid for 30 days and signed with HMAC-SHA256.

## Architecture

### Web Application

**Single-page application** with three main files:
- `app.js` - All application logic (QR scanning, Plex playback, link parsing)
- `index.html` - UI structure
- `style.css` - Styling

**Core functionality in app.js:**
- QR scanning via [qr-scanner](https://github.com/nimiq/qr-scanner) library (imported from unpkg CDN)
- Plex playback via direct audio streaming (requires plex-mapping-{lang}.json and plex-config.json)
- Hitster link parsing (`hitstergame.com/{lang}/{id}`) - looked up in Plex mapping
- Random playback mode with configurable duration
- Cookie-based settings persistence

**Plex Integration:**
- `plex-config.json` - Plex server URL and token (gitignored, must be created manually)
- `plex-manifest.json` - Array of game objects with mapping ID, name, songCount, matchRate, minDate, maxDate
- `plex-mapping-{lang}.json` - Maps Hitster card IDs to Plex track metadata (one per language/edition)
- Debug info shows Plex lookup status for each card
- Unmatched cards show "Card #X not available" feedback to the user
- Supports direct rating key QR codes (`plex:12345` format) for custom games

To enable Plex, create `plex-config.json` in the root:
```json
{
  "serverUrl": "https://your-plex-server:32400",
  "token": "YOUR_PLEX_TOKEN",
  "files-path": "/path/to/hitster/files",
  "remapper-filename": "plex-remapper.json",
  "manifest-filename": "plex-manifest.json"
}
```

The `files-path`, `remapper-filename`, and `manifest-filename` fields are used by the tools (not the web app). All tool file parameters accept filenames only, resolved from `files-path`.

**Card ID Normalization:**
- Card IDs are normalized by parsing as integer (removes leading zeros)
- e.g., "00257" matches "257" in the mapping

### Plex Mapper Tool (tools/)

Python tool to generate Plex mappings and download missing songs.

**Location:** `tools/plex_mapper/`

**Key files:**
- `main.py` - Main script with Plex search and yt-dlp download
- `pyproject.toml` - Poetry configuration

**Features:**
- Searches Plex library for songs with year matching (exact by default, configurable tolerance with `--year-tolerance`)
- Incremental matching (skips already-matched songs by default, use `--rematch` to re-match all)
- Generates `plex-mapping-{lang}.json` for the web app
- Generates `plex-manifest.json` with available mappings, game edition names, and match rates
- Downloads missing songs from YouTube with metadata embedded
- Plex-friendly folder structure: `Artist/Song Title/Song Title (Year).mp3`
- Artist/title normalization handles accents (ä→a, é→e) and ligatures (æ→ae, œ→oe)
- Title normalization removes version suffixes like "(Remaster)", "(Extended Version)", etc.
- Track remapper (`plex-remapper.json`) allows overriding year/artist/title for specific tracks

See `tools/README.md` for usage instructions.

### Custom Game Creator (tools/)

Create custom Hitster-style games from Plex rating keys or playlists.

**Location:** `tools/plex_mapper/custom_game.py`

**Features:**
- Input: List of Plex rating keys (comma-separated or from file) or a Plex playlist
- Output: Mapping JSON, updated manifest, and printable PDF cards (auto-named from game name)
- Cards contain QR codes with `plex:{ratingKey}` format
- Invalid rating keys are skipped with a warning

**Usage:**
```bash
poetry run custom-game --name "80s Classics" --mapping "80s-classics" --playlist "My 80s Playlist"
poetry run custom-game --name "Party Mix" --mapping "party-mix" --keys "12345,67890"
```

### Plex Scan Tool (tools/)

Trigger targeted Plex library scans on specific folders (faster than full library scan).

**Location:** `tools/plex_mapper/plex_scan.py`

**Features:**
- Scan specific folders instead of entire library
- Auto-detects library section if only one exists
- Supports relative paths (converted to absolute using library root)
- Works with any library type (Music, Movies, etc.)

**Usage:**
```bash
poetry run plex-scan -s Music "Unsorted/Artist Name/Album"
poetry run plex-scan --list-sections
```

**Note:** The `--force` flag can trigger broader metadata refreshes than intended. Plex's targeted scan API has some quirks - if files aren't being picked up, sometimes a manual scan from the Plex UI works better.

## Related Repositories

- [songseeker-plex-lists](https://github.com/abarthen/songseeker-plex-lists) - Pre-built Plex mapping files (cloned during Docker build)
- [songseeker-hitster-playlists](https://github.com/andygruber/songseeker-hitster-playlists) - CSV files mapping Hitster card IDs to YouTube URLs
- [songseeker-card-generator](https://github.com/andygruber/songseeker-card-generator) - Generate QR code game cards
