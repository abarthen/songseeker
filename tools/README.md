# SongSeeker Tools

Tools for generating Plex mappings and custom games for SongSeeker.

## Available Tools

| Tool | Purpose |
|------|---------|
| **plex-mapper** | Create mappings from Hitster CSV files by searching Plex |
| **custom-game** | Create custom games from Plex rating keys or playlists |
| **mapping-tools** | Enrich mapping files with additional metadata |
| **check-mappings** | Verify mappings against Plex or a playlist |
| **validate-years** | Validate year values against MusicBrainz database |
| **update-manifest** | Regenerate manifest from existing mapping files |

## Workflow

```
1. Create mapping     → plex-mapper (from CSV) or custom-game (from playlist/keys)
2. Enrich mapping     → mapping-tools --enrich
3. Check mapping      → check-mappings (against Plex or playlist)
4. Fix missing        → check-mappings --fix
5. Validate years     → validate-years (against MusicBrainz)
6. Update manifest    → update-manifest
```

## Setup

```bash
cd tools
poetry install
```

### Requirements for downloading

- **deno** (JavaScript runtime for yt-dlp PO Token handling): `winget install DenoLand.Deno`
- **ffmpeg** (audio conversion): `winget install ffmpeg`

## Configuration

All tools read settings from `../plex-config.json` (relative to the tools folder):

```json
{
  "serverUrl": "https://your-plex-server:32400",
  "token": "YOUR_PLEX_TOKEN",
  "files-path": "/path/to/your/hitster/files",
  "remapper-filename": "plex-remapper.json",
  "manifest-filename": "plex-manifest.json",
  "game-registry-filename": "game-registry.json"
}
```

| Field | Description |
|-------|-------------|
| `serverUrl` | Your Plex server URL |
| `token` | Plex authentication token |
| `files-path` | Directory containing all mapping files, CSVs, and output |
| `remapper-filename` | Track remapper file (in files-path) |
| `manifest-filename` | Manifest file (in files-path) |
| `game-registry-filename` | Game registry file mapping IDs to display names |

All file parameters accept **filenames only** (not paths). Files are resolved relative to `files-path`.

---

# plex-mapper

Create mappings from Hitster CSV files by searching your Plex library.

## Usage

```bash
# Basic mapping (search Plex only)
poetry run plex-mapper --csv hitster-de.csv

# Re-match all songs (ignore existing mapping)
poetry run plex-mapper --csv hitster-de.csv --rematch

# With download of missing songs
poetry run plex-mapper --csv hitster-de.csv --download --cookies firefox

# Test with limited songs
poetry run plex-mapper --csv hitster-de.csv --limit 5 --debug

# Update a specific card
poetry run plex-mapper --csv hitster-de.csv --id 38

# Manually set a card using Plex ratingKey (bypasses search)
poetry run plex-mapper --csv hitster-de.csv --id 38 --rating-key 98870

# Allow fuzzy year matching (±2 years)
poetry run plex-mapper --csv hitster-de.csv --year-tolerance 2
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--csv` | `-c` | Hitster CSV filename (resolved from files-path) |
| `--output` | `-o` | Output mapping filename (default: plex-mapping-{lang}.json) |
| `--server` | `-s` | Plex server URL (default: from config) |
| `--token` | `-t` | Plex authentication token (default: from config) |
| `--config` | | Path to plex-config.json |
| `--download` | `-D` | Download missing songs from YouTube |
| `--download-dir` | | Directory for downloads (default: ./downloads) |
| `--cookies` | | Browser name or path to cookies.txt for YouTube |
| `--debug` | `-d` | Enable debug output |
| `--limit` | `-l` | Only process first N songs (for testing) |
| `--rematch` | `-R` | Re-match all songs (default: skip already matched) |
| `--id` | `-i` | Only process a specific card ID |
| `--rating-key` | `-k` | Manually set Plex ratingKey for --id |
| `--year-tolerance` | `-y` | Accept year matches within ± N years (default: 0) |

---

# custom-game

Create custom Hitster-style games from Plex playlists or rating keys.

## Usage

```bash
# List available playlists
poetry run custom-game --list-playlists

# Create game from a Plex playlist
poetry run custom-game --name "80s Classics" --mapping "80s-classics" --playlist "My 80s Playlist"

# Create from rating keys
poetry run custom-game --name "Party Mix" --mapping "party-mix" --keys "12345,67890,11111"

# Extend an existing game with new songs
poetry run custom-game --extend plex-mapping-80s-classics.json --playlist "My 80s Playlist"
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--name` | `-n` | Game name for display (required for new games) |
| `--mapping` | `-m` | Mapping identifier (e.g., "80s-classics") |
| `--extend` | `-e` | Existing mapping filename to extend |
| `--keys` | `-k` | Comma-separated keys or filename with one key per line |
| `--playlist` | `-P` | Plex playlist name or ratingKey |
| `--list-playlists` | `-L` | List available playlists and exit |
| `--output` | `-o` | Output mapping filename |
| `--icon` | | Path or URL to icon for QR codes |
| `--server` | `-s` | Plex server URL (default: from config) |
| `--token` | `-t` | Plex token (default: from config) |
| `--config` | | Path to plex-config.json |
| `--debug` | `-d` | Enable debug output |

## Output

- **Mapping JSON** with rating keys as identifiers
- **Cards PDF** for double-sided printing (front: QR codes, back: song info)

---

# mapping-tools

Enrich mapping files with additional metadata (guid, mbid, alternativeKeys).

## Usage

```bash
# Enrich a mapping with stable identifiers
poetry run mapping-tools --enrich --mapping plex-mapping-de.json

# With debug output
poetry run mapping-tools --enrich --mapping plex-mapping-de.json --debug

# Adjust parallel workers
poetry run mapping-tools --enrich --mapping plex-mapping-de.json --workers 5
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--mapping` | `-m` | Mapping filename (required) |
| `--enrich` | `-e` | Re-fetch metadata for all tracks (required) |
| `--workers` | `-w` | Number of parallel workers (default: 10) |
| `--server` | `-s` | Plex server URL (default: from config) |
| `--token` | `-t` | Plex token (default: from config) |
| `--config` | | Path to plex-config.json |
| `--debug` | `-d` | Show detailed progress |

---

# check-mappings

Verify that mapping files are still valid (ratingKeys exist in Plex or tracks exist in playlist).

Uses parallel requests for speed (default 10 workers).

## Usage

```bash
# Check ALL mappings in game-registry.json against Plex
poetry run check-mappings

# Check a specific mapping against Plex
poetry run check-mappings -m plex-mapping-de.json

# Check a mapping against a specific playlist
poetry run check-mappings -m plex-mapping-de.json -p "My Playlist"

# Mark missing tracks in mapping(s)
poetry run check-mappings --fix
poetry run check-mappings -m plex-mapping-de.json --fix
```

## Missing Track Handling

When `--fix` is used, tracks that no longer exist in Plex are marked with `"missing": true` instead of being deleted. This preserves the track metadata (artist, title, year) so you know what song to look for.

When running checks (with or without `--fix`), tracks that were previously marked as missing but now exist in Plex are automatically "recovered" - the `missing` flag is removed.

The `mapping-tools --enrich` command also removes the `missing` flag when re-fetching track metadata successfully.

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--mapping` | `-m` | Mapping filename (if omitted, checks all in game-registry.json) |
| `--playlist` | `-p` | Playlist name or ratingKey to check against (requires --mapping) |
| `--fix` | `-f` | Mark missing tracks (only for Plex checks, not playlist) |
| `--workers` | `-w` | Number of parallel workers (default: 10) |
| `--server` | `-s` | Plex server URL (default: from config) |
| `--token` | `-t` | Plex token (default: from config) |
| `--config` | | Path to plex-config.json |
| `--debug` | `-d` | Show detailed progress |

---

# validate-years

Validate year values in mapping files against MusicBrainz database.

## Usage

```bash
# Validate all tracks in a mapping file
poetry run validate-years --mapping plex-mapping-de.json --output report.json

# Re-check only previously flagged tracks
poetry run validate-years --report report.json

# Allow ±1 year tolerance
poetry run validate-years --mapping plex-mapping-de.json --tolerance 1

# Apply report findings to plex-remapper.json
poetry run validate-years --apply report.json
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--mapping` | `-m` | Mapping filename (initial full scan) |
| `--report` | `-r` | Previous report filename (re-check flagged tracks) |
| `--apply` | `-a` | Report filename to apply to plex-remapper.json |
| `--tolerance` | `-t` | Allowed year difference (default: 0) |
| `--limit` | `-l` | Limit number of tracks to check |
| `--output` | `-o` | Output filename for report |
| `--filter` | `-f` | Only check tracks containing this string |
| `--config` | | Path to plex-config.json |
| `--debug` | `-d` | Show detailed progress |

---

# update-manifest

Regenerate `plex-manifest.json` from existing mapping files.

## Usage

```bash
# Regenerate manifest
poetry run update-manifest

# With debug output
poetry run update-manifest --debug
```

The manifest is generated from mappings listed in `game-registry.json`. Only mappings with entries in the registry are included.

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--config` | | Path to plex-config.json |
| `--output` | `-o` | Output manifest path (default: from config) |
| `--scan-dir` | `-s` | Directory to scan (default: from config files-path) |
| `--debug` | `-d` | Enable debug output |

---

# Track Remapper

Override metadata for specific tracks using `plex-remapper.json`:

```json
[
    {
        "ratingKey": "85677",
        "metadata": { "artist": "Whitesnake", "title": "Here I Go Again" },
        "replaceData": { "year": 1982 }
    }
]
```

**Fields:**
- `ratingKey`: The Plex rating key to override
- `metadata`: Reference only (ignored by tools)
- `replaceData`: Values to override (`year`, `artist`, `title`, or `ratingKey`)

### Alternative Rating Keys

When replacing tracks in Plex, use `replaceData.ratingKey` to map old cards to new tracks:

```json
{
    "ratingKey": "12345",
    "replaceData": { "ratingKey": "67890" }
}
```

This keeps printed cards working while using the new track.

---

# Title Normalization

Song titles are automatically cleaned:

**Removed:** `(Extended Version)`, `(Remaster)`, `(50th Anniversary Edition)`, `(Mono)`, `(Stereo)`, `({any} Mix)`

**Kept:** `(feat. Artist)`, `(From "Movie")`

**Warning only:** `(Instrumental)`, `(Live at ...)`
