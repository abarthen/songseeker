# SongSeeker Tools

Tools for generating Plex mappings and custom games for SongSeeker.

## Available Tools

| Tool | Purpose |
|------|---------|
| **plex-mapper** | Create mappings from Hitster CSV files by searching Plex |
| **custom-game** | Create custom games from Plex rating keys or playlists |
| **mapping-tools** | Enrich mapping files with additional metadata |
| **check-mappings** | Verify mappings against Plex or a playlist |
| **compare-mapping** | Compare mapping JSON against its Hitster CSV (year, artist, title) |
| **lock-years** | Lock mapping years into plex-remapper.json to prevent drift |
| **validate-years** | Validate year values against MusicBrainz database |
| **create-playlist** | Create a Plex playlist from a mapping file |
| **update-manifest** | Regenerate manifest from existing mapping files |
| **ytm-adder** | Add songs to YouTube Music playlist using ISRC codes from CSV |

## Setup

```bash
cd tools
poetry install
```

### Requirements for downloading

- **deno** (JavaScript runtime for yt-dlp PO Token handling): `winget install DenoLand.Deno`
- **ffmpeg** (audio conversion): `winget install ffmpeg`

### Related: music-tagger

The [music-tagger](../../music-tagger) project (separate repo at `c:\Users\andreas\Projects\music-tagger`) assigns track numbers to music files based on file modification date. This is useful after bulk-downloading songs, since the downloader adds them in order. Run it before Plex scans so track numbers are correct:

```bash
cd c:/Users/andreas/Projects/music-tagger
poetry run music-tagger /path/to/music/root --newer-than 2026-04-01 --dry-run --verbose
```

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

## Workflows

### Adding an Official Game (from Hitster CSV)

Official games come with a CSV file (from [songseeker-hitster-playlists](https://github.com/andygruber/songseeker-hitster-playlists)) that maps card IDs to YouTube URLs, artist, title, year, and ISRC codes.

**1. Add songs to YouTube Music playlist** (to find and download missing songs):

```bash
# Start Brave with remote debugging first:
# "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222

poetry run ytm-adder --csv hitster-de-aaaa0039.csv --playlist "#3"
```

**2. Download missing songs** and add them to your Plex library.

**3. Assign track numbers** to newly downloaded files (uses file modification date):

```bash
cd c:/Users/andreas/Projects/music-tagger
poetry run music-tagger /path/to/music/root --newer-than 2026-04-01
```

**4. Scan Plex library**, then create/update the mapping:

```bash
poetry run plex-mapper --csv hitster-de-aaaa0039.csv --rematch
```

**5. Enrich mapping** with stable identifiers (guid, mbid):

```bash
poetry run mapping-tools --enrich --mapping plex-mapping-de-aaaa0039.json
```

**6. Compare mapping against CSV** to find year/artist/title mismatches:

```bash
poetry run compare-mapping de-aaaa0039
```

Review and fix any mismatches (manually adjust the mapping or add entries to `plex-remapper.json`).

**7. Lock years** into remapper to prevent Plex metadata drift:

```bash
poetry run lock-years -m plex-mapping-de-aaaa0039.json
```

**8. Create Plex playlist** from the mapping (optional, for playback):

```bash
poetry run create-playlist -i plex-mapping-de-aaaa0039.json -n "Hitster DE AAAA0039"
```

**9. Check existing mappings** to make sure nothing broke:

```bash
poetry run check-mappings
```

**10. Update manifest:**

```bash
poetry run update-manifest
```

### Adding a Custom Game (from Plex playlist)

Custom games are created from an existing Plex playlist. There is no CSV - songs are whatever is in the playlist.

**1. Create game from playlist:**

```bash
poetry run custom-game --name "My Custom Game" --mapping "my-custom" --playlist "My Playlist"
```

This produces a mapping JSON and a cards PDF for printing.

**2. Enrich mapping** with stable identifiers:

```bash
poetry run mapping-tools --enrich --mapping plex-mapping-my-custom.json
```

**3. Validate years** against MusicBrainz (since there's no CSV to compare against):

```bash
poetry run validate-years --mapping plex-mapping-my-custom.json --output year-report.json
```

Review the report and apply corrections:

```bash
poetry run validate-years --apply year-report.json
```

**4. Lock years** into remapper:

```bash
poetry run lock-years -m plex-mapping-my-custom.json
```

**5. Update manifest:**

```bash
poetry run update-manifest
```

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

# compare-mapping

Compare a plex-mapping JSON file against its corresponding Hitster CSV file. Reports year mismatches and warns about significant artist/title differences.

## Usage

```bash
# Compare mapping against CSV
poetry run compare-mapping de-aaaa0039

# Verbose output (show all entries)
poetry run compare-mapping de-aaaa0039 --verbose
```

Takes a mapping ID (e.g., `de-aaaa0039`) and resolves both files:
- `plex-mapping-de-aaaa0039.json` from `files-path`
- `hitster-de-aaaa0039.csv` from `csv-files-path` (or `files-path`)

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `mapping_id` | | Mapping ID (positional, e.g., `de-aaaa0039`) |
| `--config` | | Path to plex-config.json |
| `--verbose` | `-v` | Show all entries, not just mismatches |

---

# lock-years

Lock years from a mapping file into `plex-remapper.json`. This ensures that Plex metadata changes (e.g., remaster editions updating the year) don't affect the year shown on game cards.

For each track in the mapping:
- If the ratingKey already exists in the remapper with the same year: skip
- If it exists with a different year: warn and skip (resolve manually)
- Otherwise: create/update the entry with the year from the mapping

Always writes artist/title to the `metadata` field. Only writes `year` to `replaceData`.

## Usage

```bash
# Lock years (asks for confirmation)
poetry run lock-years -m plex-mapping-de-aaaa0039.json

# Dry run
poetry run lock-years -m plex-mapping-de-aaaa0039.json --dry-run
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--mapping` | `-m` | Mapping filename (required) |
| `--dry-run` | | Show what would be done without writing |
| `--config` | | Path to plex-config.json |

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

# create-playlist

Create a Plex audio playlist from a mapping file.

## Usage

```bash
poetry run create-playlist -i plex-mapping-de-aaaa0039.json -n "Hitster DE AAAA0039"
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--input` | `-i` | Input JSON mapping filename (resolved from files-path) |
| `--name` | `-n` | Playlist name to create |
| `--server` | `-s` | Plex server URL (default: from config) |
| `--token` | `-t` | Plex token (default: from config) |
| `--config` | | Path to plex-config.json |
| `--debug` | `-d` | Enable debug output |

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

# ytm-adder

Add songs/albums to a YouTube Music playlist using ISRC codes from Hitster CSV files. Uses Playwright to automate Brave browser.

## Prerequisites

Start Brave with remote debugging and log into YouTube Music:

```bash
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
```

## Usage

```bash
# Verify connection
poetry run ytm-adder --login

# Process a CSV file
poetry run ytm-adder --csv hitster-de-aaaa0039.csv --playlist "#3"

# Resume from a specific card number
poetry run ytm-adder --csv hitster-de-aaaa0039.csv --playlist "#3" --start-from 50

# Dry run
poetry run ytm-adder --csv hitster-de-aaaa0039.csv --playlist "#3" --dry-run

# Clear progress from previous runs
poetry run ytm-adder --clear-progress
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--login` | | Verify browser connection |
| `--csv` | | CSV file path containing ISRC codes |
| `--playlist` | | Playlist name (default: `#3`) |
| `--start-from` | | Start from this card number |
| `--headless` | | Run browser headless |
| `--dry-run` | | Show what would be done |
| `--clear-progress` | | Clear saved progress |

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
