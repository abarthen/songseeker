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

**Runtime behavior**: On container start, built-in mapping files are deployed to `/plex-data/`, overwriting any existing files. This ensures you always have the latest mappings from the build. Your `plex-config.json` is not affected (it's not included in the defaults).

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

**Single-page application** with these main files:
- `app.js` - All application logic (QR scanning, Plex playback, link parsing)
- `musicbrainz.js` - Release year lookup for songs not in any edition mapping
- `player-manager.js`, `plex-player.js` - Audio playback
- `index.html` - UI structure
- `style.css` - Styling

**Core functionality in app.js:**
- QR scanning via [qr-scanner](https://github.com/nimiq/qr-scanner) library (imported from unpkg CDN)
- Plex playback via direct audio streaming (requires plex-mapping-{lang}.json and plex-config.json)
- Hitster link parsing (`hitstergame.com/{lang}/{id}`) - looked up in Plex mapping
- Random playback mode with configurable duration
- Cookie-based settings persistence

**Game modes** (toggle below the divider, saved in the `gameMode` cookie):
- **Hitster Mode** - Scan cards
- **Plex Mode** - "Play Random Song" from the selected editions and Plex playlists (weighted by size), or from the whole Plex music library when nothing is selected. Library and playlist picks fetch a single item at a random offset (`X-Plex-Container-Start`/`Size`), so no track list is downloaded

**Song info sources:**
- Edition mappings are the source of truth: any song (scanned, from a playlist or the library) is looked up by ratingKey in all loaded mappings first, even unselected ones. If mappings disagree, the first in manifest order wins and a warning is shown
- Otherwise artist/title come from Plex. Year priority: edition JSON > locked Plex track year > MusicBrainz (`musicbrainz.js`: the earlier of the recording behind the Plex track's MusicBrainz track ID and an artist + title search taking the earliest non-live match) > unlocked Plex year (usually the album year, shown as unverified). There is deliberately no browser cache; Plex is the only store of verified years
- Verified years (from JSON or MusicBrainz) are written back to the Plex *track* (not the album) and locked (`PUT /library/sections/{id}/all?type=10&id={ratingKey}&year.value=...&year.locked=1`). A locked track year is what marks a Plex year as trustworthy. Plex list endpoints don't return field locks, so random picks load the track via `/library/metadata/{ratingKey}`. Controlled by the "Save verified years to Plex" setting; writes stop for the session after a failure
- Non-edition years have an Edit button in the song info to correct disputed years; the edited year is always written to Plex and locked. Edition years can't be edited, since the JSON files are replaced on the next release
- The Song Info area shows the source (Edition/Plex badge) and where the year came from

**Plex Integration:**
- `plex-config.json` - Plex server URL and token (gitignored, must be created manually)
- `plex-manifest.json` - Array of game objects with mapping ID, name, songCount, matchRate, minDate, maxDate
- `plex-mapping-{lang}.json` - Maps Hitster card IDs to Plex track metadata (one per language/edition)
- Debug info shows Plex lookup status for each card
- Unmatched cards show "Card #X not available" feedback to the user
- Supports direct rating key QR codes (`plex:12345` format) for custom games; keys not in any mapping are played straight from Plex

To enable Plex, create `plex-config.json` in the root:
```json
{
  "serverUrl": "https://your-plex-server:32400",
  "token": "YOUR_PLEX_TOKEN",
  "files-path": "/path/to/hitster/files",
  "remapper-filename": "plex-remapper.json",
  "manifest-filename": "plex-manifest.json",
  "game-registry-filename": "game-registry.json"
}
```

The `files-path` and filename fields are used by the tools (not the web app). All tool file parameters accept filenames only, resolved from `files-path`. The `game-registry.json` maps mapping IDs to display names and determines which mappings are included in the manifest.

**Card ID Normalization:**
- Card IDs are normalized by parsing as integer (removes leading zeros)
- e.g., "00257" matches "257" in the mapping

### Plex Mapper Tools (tools/)

Python tools to generate and maintain Plex mappings. Located in `tools/plex_mapper/`.

**Workflow:**
```
1. Create mapping     → plex-mapper (from CSV) or custom-game (from playlist/keys)
2. Enrich mapping     → mapping-tools --enrich
3. Check mappings     → check-mappings (against Plex or playlist)
4. Fix missing        → check-mappings --fix
5. Validate years     → validate-years (against MusicBrainz)
6. Update manifest    → update-manifest
```

**Available tools:**
| Tool | Purpose |
|------|---------|
| `plex-mapper` | Create mappings from Hitster CSV files by searching Plex |
| `custom-game` | Create custom games from Plex rating keys or playlists |
| `mapping-tools` | Enrich mapping files with additional metadata |
| `check-mappings` | Verify mappings against Plex or a playlist |
| `validate-years` | Validate year values against MusicBrainz database |
| `update-manifest` | Regenerate manifest from existing mapping files |

**Key features:**
- Searches Plex library for songs with year matching (configurable tolerance)
- Incremental matching (skips already-matched songs by default)
- Downloads missing songs from YouTube with metadata embedded
- Track remapper (`plex-remapper.json`) allows overriding year/artist/title
- Title normalization removes version suffixes like "(Remaster)", "(Extended Version)"

See `tools/README.md` for detailed usage instructions.

## Related Repositories

- [songseeker-plex-lists](https://github.com/abarthen/songseeker-plex-lists) - Pre-built Plex mapping files (cloned during Docker build)
- [songseeker-hitster-playlists](https://github.com/andygruber/songseeker-hitster-playlists) - CSV files mapping Hitster card IDs to YouTube URLs
- [songseeker-card-generator](https://github.com/andygruber/songseeker-card-generator) - Generate QR code game cards
