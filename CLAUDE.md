# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Structure

This project uses a multi-folder workspace with two git repositories:
- `c:\Users\andreas\Projects\songseeker\` - Main web application (this repo)
- `c:\Users\andreas\Projects\songseeker-hitster-playlists\` - CSV playlist files mapping Hitster card IDs to YouTube URLs

## Project Overview

SongSeeker is a music guessing game web application inspired by Hitster and Rockster. Players scan QR codes containing song links, and the app plays the audio via YouTube or Plex while hiding song info for guessing.

Live demo: https://songseeker.grub3r.io/

## Development

This is a static web app with no build system. To develop locally:

1. Serve the files over HTTPS (required for camera/QR scanning)
2. Open index.html in a browser

## Docker Build

```bash
docker build -t songseeker -f imagebuild/Dockerfile .
```

The Docker image uses nginx to serve the app and automatically fetches Hitster playlist CSV files from the [songseeker-hitster-playlists](https://github.com/andygruber/songseeker-hitster-playlists) repository.

### Authentication

The deployed site uses cookie-based authentication with a proper login page (password manager friendly).

**Components:**
- `login.html` - Login page with form
- `imagebuild/auth_server.py` - Python auth server that validates credentials and issues session cookies
- Credentials stored in htpasswd format

**Setup:**
1. Generate htpasswd: `htpasswd -c .htpasswd username`
2. Generate cookie secret: `openssl rand -hex 32`
3. Set `COOKIE_SECRET` environment variable in docker-compose
4. Mount `.htpasswd` file to `/etc/nginx/.htpasswd`

**Session cookies** are valid for 30 days and signed with HMAC-SHA256.

## Architecture

### Web Application

**Single-page application** with three main files:
- `app.js` - All application logic (QR scanning, YouTube/Plex playback, link parsing)
- `index.html` - UI structure
- `style.css` - Styling

**Core functionality in app.js:**
- QR scanning via [qr-scanner](https://github.com/nimiq/qr-scanner) library (imported from unpkg CDN)
- YouTube playback via YouTube IFrame API
- Plex playback via direct audio streaming (requires plex-mapping.json and plex-config.json)
- Link detection and parsing for three formats:
  - Direct YouTube links
  - Hitster links (`hitstergame.com/{lang}/{id}`) - looked up in CSV playlists
  - Rockster links (`rockster.brettspiel.digital/?yt={id}`)
- Random playback mode with configurable duration
- Cookie-based settings persistence

**Plex Integration:**
- `plex-config.json` - Plex server URL and token (gitignored, must be created manually)
- `plex-mapping.json` - Maps Hitster card IDs to Plex track metadata
- Source indicator shows "Plex" or "YouTube" based on playback source
- Debug info shows why Plex was/wasn't used for each card

To enable Plex, create `plex-config.json` in the root:
```json
{
  "serverUrl": "https://your-plex-server:32400",
  "token": "YOUR_PLEX_TOKEN"
}
```

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
- Searches Plex library for songs with exact year matching
- Incremental matching (skips already-matched songs by default, use `--rematch` to re-match all)
- Generates `plex-mapping-{lang}.json` for the web app
- Generates `missing-{lang}.csv` with unmatched songs
- Downloads missing songs from YouTube with metadata embedded
- Plex-friendly folder structure: `artist/song name/song name (year).mp3`

See `tools/README.md` for usage instructions.

## Related Repositories

- [songseeker-hitster-playlists](https://github.com/andygruber/songseeker-hitster-playlists) - CSV files mapping Hitster card IDs to YouTube URLs (included in workspace)
- [songseeker-card-generator](https://github.com/andygruber/songseeker-card-generator) - Generate QR code game cards
