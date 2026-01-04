# SongSeeker Tools

Tools for generating Plex mappings and custom games for SongSeeker.

## Available Tools

- **plex-mapper** - Generate mappings from Hitster CSV files by searching your Plex library
- **custom-game** - Create custom games from a list of Plex rating keys with printable cards

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

## Output Files

The script generates (overwriting on each run):

1. **`plex-mapping-{lang}.json`** - Mapping file for SongSeeker web app
2. **`plex-manifest.json`** - Lists available mapping files, game names, and match rates (auto-generated)

The manifest includes match rates (percentage of cards matched to Plex tracks) which are displayed on the website next to each game edition.

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

---

# Custom Game Creator

Create your own Hitster-style games with custom song selections from your Plex library.

## Usage

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

1. **Plex Web UI**: Open a track, the URL contains `/library/metadata/{ratingKey}`
2. **Plex API**: Query `/library/sections/{id}/all` and look for `ratingKey` in the XML/JSON
3. **plex-mapper debug output**: Use `--debug` flag to see rating keys for matched tracks

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--name` | `-n` | Game name for display (required) |
| `--mapping` | `-m` | Mapping identifier, e.g., "80s-classics" (required) |
| `--keys` | `-k` | Comma-separated keys OR path to file with one key per line (required) |
| `--cards-pdf` | `-p` | Output PDF path for printable cards (required) |
| `--output-dir` | `-o` | Directory to save mapping JSON (default: current directory) |
| `--server` | `-s` | Plex server URL (default: from plex-config.json) |
| `--token` | `-t` | Plex authentication token (default: from plex-config.json) |
| `--config` | | Path to plex-config.json (default: ../plex-config.json) |
| `--icon` | | Path or URL to icon for QR codes (max 300x300px) |
| `--debug` | `-d` | Enable debug output |

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
