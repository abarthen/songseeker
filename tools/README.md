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

### Basic mapping (search Plex only)

```bash
poetry run plex-mapper \
  --server https://your-plex-server:32400 \
  --token YOUR_PLEX_TOKEN \
  --csv ../songseeker-hitster-playlists/hitster-de.csv
```

### With download of missing songs

```bash
poetry run plex-mapper \
  --server https://your-plex-server:32400 \
  --token YOUR_PLEX_TOKEN \
  --csv ../songseeker-hitster-playlists/hitster-de.csv \
  --download \
  --cookies firefox
```

### Test with limited songs

```bash
poetry run plex-mapper \
  --server https://your-plex-server:32400 \
  --token YOUR_PLEX_TOKEN \
  --csv ../songseeker-hitster-playlists/hitster-de.csv \
  --download \
  --cookies firefox \
  --limit 5 \
  --debug
```

### Finding your Plex token

1. Sign in to Plex Web App
2. Browse to any media item and click "Get Info"
3. Click "View XML"
4. The token is in the URL as `X-Plex-Token=...`

## Command Line Arguments

| Argument | Short | Description |
|----------|-------|-------------|
| `--server` | `-s` | Plex server URL (required) |
| `--token` | `-t` | Plex authentication token (required) |
| `--csv` | `-c` | Path to Hitster CSV file (required) |
| `--output` | `-o` | Output JSON file path (default: auto-generated with timestamp) |
| `--download` | `-D` | Download missing songs from YouTube |
| `--download-dir` | | Directory for downloads (default: `./downloads`) |
| `--cookies` | | Browser name (`firefox`, `chrome`, `edge`) or path to cookies.txt |
| `--debug` | `-d` | Enable debug output |
| `--limit` | `-l` | Only process first N songs (for testing) |

## Output Files

The script generates:

1. **`plex-mapping-{lang}_{timestamp}.json`** - Mapping file for SongSeeker web app
2. **`...-missing-soundiiz.csv`** - Import to [Soundiiz](https://soundiiz.com) to create playlists
3. **`...-missing-full.csv`** - Full details with YouTube Music URLs

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

Copy the generated JSON to the web app root:

```bash
cp plex-mapping-de_*.json ../plex-mapping.json
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
