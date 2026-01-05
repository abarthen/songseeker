# SongSeeker Tools

Tools for generating Plex mappings and custom games for SongSeeker.

## Available Tools

- **plex-mapper** - Generate mappings from Hitster CSV files by searching your Plex library
- **custom-game** - Create custom games from a list of Plex rating keys with printable cards
- **plex-scan** - Trigger Plex library scan on specific folders (faster than full scan)
- **validate-years** - Validate year values in mapping files against MusicBrainz database

## Setup

```bash
cd tools
poetry install
```

### Requirements for downloading

- **deno** (JavaScript runtime for yt-dlp PO Token handling): `winget install DenoLand.Deno`
- **ffmpeg** (audio conversion): `winget install ffmpeg`

## Usage

The script reads Plex credentials from `../plex-config.json` by default.

**Incremental matching**: By default, the script loads any existing mapping file and skips songs that are already matched. This speeds up subsequent runs after adding songs to Plex.

### Basic mapping (search Plex only)

```bash
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv
```

### Re-match all songs (ignore existing mapping)

```bash
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --rematch
```

### With download of missing songs

```bash
poetry run plex-mapper \
  --csv ../songseeker-hitster-playlists/hitster-de.csv \
  --download \
  --cookies firefox
```

### Test with limited songs

```bash
poetry run plex-mapper \
  --csv ../songseeker-hitster-playlists/hitster-de.csv \
  --limit 5 \
  --debug
```

### Update a specific card

```bash
# Re-match a single card by ID
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --id 38

# Manually set a card using Plex ratingKey (bypasses search)
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --id 38 --rating-key 98870
```

The `--rating-key` option is useful when Plex search doesn't find a track but you can locate it manually. Get the ratingKey from the Plex URL (e.g., `/library/metadata/98870`) or XML.

### Allow fuzzy year matching

```bash
# Accept matches within ±2 years (useful for albums with incorrect metadata)
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --year-tolerance 2
```

### Check existing mapping

Verify that all rating keys in an existing mapping still exist in Plex (useful after reorganizing your library):

```bash
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --check
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --check --debug

# Check and remove missing tracks (so next run will re-match them)
poetry run plex-mapper --csv ../songseeker-hitster-playlists/hitster-de.csv --check --fix
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--server` | `-s` | Plex server URL (default: from plex-config.json) |
| `--token` | `-t` | Plex authentication token (default: from plex-config.json) |
| `--config` | | Path to plex-config.json (default: ../plex-config.json) |
| `--csv` | `-c` | Path to Hitster CSV file (required) |
| `--output` | `-o` | Output JSON file path (default: plex-mapping-{lang}.json) |
| `--download` | `-D` | Download missing songs from YouTube |
| `--download-dir` | | Directory for downloads (default: `./downloads`) |
| `--cookies` | | Browser name (`firefox`, `chrome`, `edge`) or path to cookies.txt |
| `--debug` | `-d` | Enable debug output |
| `--limit` | `-l` | Only process first N songs (for testing) |
| `--rematch` | `-R` | Re-match all songs (default: skip already matched) |
| `--id` | `-i` | Only process a specific card ID (updates existing mapping) |
| `--rating-key` | `-k` | Manually set Plex ratingKey for `--id` (skips search) |
| `--year-tolerance` | `-y` | Accept year matches within ± N years (default: 0 = exact) |
| `--check` | `-C` | Check that all rating keys in existing mapping still exist in Plex |
| `--fix` | `-F` | With --check: remove missing tracks from mapping so they can be re-matched |

## Output Files

The script generates (overwriting on each run):

1. **`plex-mapping-{lang}.json`** - Mapping file for SongSeeker web app
2. **`plex-manifest.json`** - Array of game objects (auto-generated)

The manifest uses this format:
```json
{
  "games": [
    {
      "mapping": "de",
      "name": "Hitster Deutschland",
      "songCount": 300,
      "matchRate": 100.0,
      "minDate": 1965,
      "maxDate": 2024
    }
  ]
}
```

Each game object contains: mapping ID, display name, song count, match rate (%), and year range. The website displays all these fields for each game edition.

## Download Folder Structure

Downloaded songs are saved in Plex-friendly format (song title used as album name):

```
downloads/
  Artist Name/
    Song Title/
      Song Title (Year).mp3
```

Files that already exist are skipped automatically.

## Deploying the Mapping

Copy the generated JSON files to the server's config folder:

```bash
cp plex-mapping-*.json plex-manifest.json /mnt/user/appdata/songseeker/
```

The web app reads `plex-manifest.json` to know which mapping files exist, avoiding 404 errors for missing languages.

## Web App Configuration

The SongSeeker web app needs a `plex-config.json` in the root directory:

```json
{
  "serverUrl": "https://your-plex-server:32400",
  "token": "YOUR_PLEX_TOKEN"
}
```

This file is gitignored and must be created manually on the server.

## Track Remapper

Some songs in Plex may have incorrect years (e.g., from best-of/compilation albums) or wrong artist/title (e.g., compilation albums). You can override metadata for specific tracks using `plex-date-remapper.json`:

```json
[
    {
        "ratingKey": "85677",
        "metadata": {
            "artist": "Whitesnake",
            "title": "Here I Go Again"
        },
        "replaceData": {
            "year": 1982
        }
    },
    {
        "ratingKey": "70022",
        "metadata": {
            "artist": "Emiliana Torrini",
            "title": "White Rabbit"
        },
        "replaceData": {
            "year": 2011,
            "artist": "Emiliana Torrini"
        }
    }
]
```

**Format:**
- JSON array of track override objects
- `ratingKey`: The Plex rating key to override
- `metadata`: For your reference only (ignored by the script) - put artist/title here for easy lookup
- `replaceData`: Contains values to override. Any combination of:
  - `year`: Replace the year from Plex
  - `artist`: Replace the artist from Plex
  - `title`: Replace the title from Plex

**Location:** `tools/plex-date-remapper.json` (automatically loaded by both plex-mapper and custom-game)

Only properties present in `replaceData` are overridden - omit properties you don't want to change.

Debug output shows `(remapped from XXXX)` when values are overridden.

## Title Normalization

Song titles are automatically cleaned to remove version/format suffixes that don't affect the song's identity:

**Automatically removed:**
- `(Extended Version)`, `(Single Version)`, `(Soundtrack Version)`
- `(Remaster)`, `(2015 - Remaster)`, `(Remastered)`
- `(50th Anniversary Edition)` and similar
- `(Mono)`, `(Stereo)`
- `(Reworked)`
- `({something} Mix)` - e.g., "(Radio Mix)", "(Club Mix)"

**Kept (part of song identity):**
- `(feat. Artist)` - featuring credits
- `(From "Movie")` - source attribution
- Subtitles like `(Thunderdome)`, `(We All)`

**Warning only (not removed):**
- `(Instrumental)` - shows ⚠️ warning, song may not be suitable for the game
- `(Live at ...)` - shows ⚠️ warning, live versions often have different arrangements

Debug output shows `(normalized from XXXX)` when titles are cleaned.

---

# Custom Game Creator

Create your own Hitster-style games with custom song selections from your Plex library.

## Usage

### From a Plex Playlist (recommended)

The easiest way to create a custom game is to curate a playlist in Plex, then use it directly:

```bash
# List available playlists
poetry run custom-game --list-playlists

# Create game from a playlist (by name or ratingKey)
poetry run custom-game \
  --name "80s Classics" \
  --mapping "80s-classics" \
  --playlist "My 80s Playlist" \
  --cards-pdf ../cards-80s-classics.pdf
```

### Extend an Existing Game

Add new songs from a playlist to an existing game. Songs already in the mapping are skipped:

```bash
# Extend existing game with new songs from playlist
poetry run custom-game \
  --extend plex-mapping-de-80s-classics.json \
  --playlist "My 80s Playlist" \
  --cards-pdf ../cards-80s-classics.pdf
```

This generates:
- Updated `plex-mapping-de-80s-classics.json` with all songs
- `cards-80s-classics-full.pdf` - all cards (existing + new)
- `cards-80s-classics-new.pdf` - only new cards to print

### From Rating Keys

```bash
# Create custom game from comma-separated rating keys
poetry run custom-game \
  --name "80s Classics" \
  --mapping "80s-classics" \
  --keys "12345,67890,11111,22222" \
  --cards-pdf ../cards-80s-classics.pdf

# Create from file (one rating key per line)
poetry run custom-game \
  --name "Party Mix" \
  --mapping "party-mix" \
  --keys rating-keys.txt \
  --cards-pdf ../cards-party-mix.pdf
```

## Finding Rating Keys

Rating keys can be found in several ways:

1. **Plex Playlist**: Create a playlist in Plex, then use `--playlist` option
2. **Plex Web UI**: Open a track, the URL contains `/library/metadata/{ratingKey}`
3. **Plex API**: Query `/library/sections/{id}/all` and look for `ratingKey` in the XML/JSON
4. **plex-mapper debug output**: Use `--debug` flag to see rating keys for matched tracks

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--name` | `-n` | Game name for display (required for new games) |
| `--mapping` | `-m` | Mapping identifier, e.g., "80s-classics" (required for new games) |
| `--extend` | `-e` | Path to existing mapping JSON to extend (skips existing songs) |
| `--keys` | `-k` | Comma-separated keys OR path to file with one key per line |
| `--playlist` | `-P` | Plex playlist name or ratingKey to use as source |
| `--list-playlists` | `-L` | List available Plex playlists and exit |
| `--cards-pdf` | `-p` | Output PDF path for printable cards (required) |
| `--output-dir` | `-o` | Directory to save mapping JSON (default: current directory) |
| `--server` | `-s` | Plex server URL (default: from plex-config.json) |
| `--token` | `-t` | Plex authentication token (default: from plex-config.json) |
| `--config` | | Path to plex-config.json (default: ../plex-config.json) |
| `--icon` | | Path or URL to icon for QR codes (max 300x300px) |
| `--debug` | `-d` | Enable debug output |

**Note:** Either `--keys` or `--playlist` is required. Use `--extend` OR `--name`/`--mapping`.

## Output

1. **`plex-mapping-{mapping}.json`** - Mapping file with rating keys as identifiers
2. **Updated `plex-manifest.json`** - Includes new game with 100% match rate
3. **`{cards-pdf}`** - Printable PDF with QR codes (front) and song info (back)

## Card Format

Cards contain:
- **Front**: QR code with `plex:{ratingKey}` data
- **Back**: Artist name, year (large), and song title

The PDF is laid out for double-sided printing (16 cards per sheet, A4).

## Error Handling

Invalid rating keys (not found in Plex) are:
- Skipped with a warning message
- Not included in the mapping or cards
- Reported in the final summary

---

# Plex Scan

Trigger a Plex library scan on specific folders. Much faster than a full library scan when adding individual files.

## Usage

```bash
# List available library sections
poetry run plex-scan --list-sections

# Scan a folder (specify section by name or ID)
poetry run plex-scan -s Music "Unsorted/Artist Name/Album"

# Scan multiple folders
poetry run plex-scan -s 3 "Artist 1/Album 1" "Artist 2/Album 2"

# Scan with absolute path
poetry run plex-scan -s Music "/data/Music/Artist Name/Album"
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `paths` | | Path(s) to scan (relative to library root or absolute) |
| `--config` | | Path to plex-config.json (default: ../plex-config.json) |
| `--section` | `-s` | Library section ID or name (required if multiple libraries exist) |
| `--list-sections` | `-l` | List all library sections and exit |
| `--debug` | `-d` | Enable debug output (shows API calls and responses) |
| `--force` | `-f` | Force rescan even if Plex thinks nothing changed (use sparingly) |

**Note about `--force`:** This flag adds `force=1` to the Plex API request, which can trigger a broader metadata refresh beyond just the specified path. Use only when a normal scan doesn't pick up changes.

## How It Works

1. If only one library exists, uses it automatically; otherwise requires `--section`
2. Converts relative paths to absolute paths using the library root
3. Triggers a targeted scan on each folder via the Plex API

This is much faster than a full library scan because Plex only checks the specified folders for changes.

---

# Year Validation Tool

Validate the year values in your Plex mapping files against the MusicBrainz database. This helps identify tracks where Plex has incorrect release years (common with compilation albums or remasters).

## Usage

```bash
# Validate all tracks in a mapping file (initial scan)
poetry run validate-years --mapping ../plex-mapping-de-at-2026.json --output report.json

# Re-check only previously flagged tracks (auto-saves to same file)
poetry run validate-years --report report.json

# Allow ±1 year tolerance (some databases differ on exact release year)
poetry run validate-years --mapping ../plex-mapping-de-at-2026.json --tolerance 1

# Debug a specific artist/track
poetry run validate-years --mapping ../plex-mapping-de-at-2026.json --filter "Whitesnake" --debug

# Test with limited tracks
poetry run validate-years --mapping ../plex-mapping-de-at-2026.json --limit 10 --debug

# Apply report findings to plex-date-remapper.json
poetry run validate-years --apply report.json --debug
```

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--mapping` | `-m` | Path to plex-mapping-*.json file (initial full scan) |
| `--report` | `-r` | Path to previous report.json (re-check only flagged tracks, auto-saves back) |
| `--apply` | `-a` | Apply report to plex-date-remapper.json (adds/updates year in replaceData) |
| `--tolerance` | `-t` | Allowed year difference (default: 0 = exact match) |
| `--limit` | `-l` | Limit number of tracks to check (for testing) |
| `--output` | `-o` | Output JSON file for discrepancy report |
| `--filter` | `-f` | Only check tracks where artist or title contains this string |
| `--debug` | `-d` | Show detailed progress for each track |

**Note:** One of `--mapping`, `--report`, or `--apply` is required (mutually exclusive).

## How It Works

1. Reads the Plex mapping file
2. For each track, queries MusicBrainz for recordings matching artist + title
3. Finds the best match and compares the "first release date" with Plex's year
4. Reports discrepancies where the years differ beyond the tolerance

## Rate Limiting

MusicBrainz requires max 1 request per second. The tool automatically respects this limit, so validation takes approximately 1 second per track. Use `--limit` to test with a subset first.

## Output

The tool displays discrepancies as they're found:

```
MISMATCH: Queen - We Will Rock You
         Plex: 1992, MusicBrainz: 1977 (diff: -15)
```

A negative difference means Plex has a later year than MusicBrainz (common for "best of" albums).

## JSON Report Format

When using `--output`, discrepancies are saved as:

```json
[
  {
    "ratingKey": "12345",
    "artist": "Queen",
    "title": "We Will Rock You",
    "album": "Greatest Hits",
    "plex_year": 1992,
    "musicbrainz_year": 1977,
    "difference": -15,
    "musicbrainz_date": "1977-10-07",
    "musicbrainz_mbid": "abc123..."
  }
]
```

## Fixing Discrepancies

For tracks with incorrect years, you have two options:

1. **Fix in Plex**: Edit the track/album metadata directly
2. **Use the remapper**: Add entries to `plex-date-remapper.json` (see Track Remapper section above)
