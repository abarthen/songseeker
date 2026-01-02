# Plex Mapper for SongSeeker

Generate Plex mappings for SongSeeker Hitster cards and download missing songs.

## Setup

```bash
cd tools
poetry install
```

### Requirements for downloading

- **deno** (JavaScript runtime for yt-dlp): `winget install DenoLand.Deno`
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

## Output Files

The script generates (overwriting on each run):

1. **`plex-mapping-{lang}.json`** - Mapping file for SongSeeker web app
2. **`missing-{lang}.csv`** - Songs not found in Plex (with YouTube Music URLs)

## Download Folder Structure

Downloaded songs are saved in Plex-friendly format:

```
downloads/
  Artist Name/
    Song Title/
      Song Title (Year).mp3
```

Files that already exist are skipped automatically.

## Deploying the Mapping

Copy the generated JSON to the server's playlists folder:

```bash
cp plex-mapping-de.json /path/to/server/playlists/
```

## Web App Configuration

The SongSeeker web app needs a `plex-config.json` in the root directory:

```json
{
  "serverUrl": "https://your-plex-server:32400",
  "token": "YOUR_PLEX_TOKEN"
}
```

This file is gitignored and must be created manually on the server.
