# YouTube Music Playlist Adder

Automates adding songs/albums to a YouTube Music playlist using ISRC codes from CSV files.

## Setup

1. Install dependencies:
   ```bash
   cd tools
   poetry install
   ```

2. Start Brave with remote debugging:
   ```cmd
   "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
   ```

3. Log into YouTube Music in that Brave window (if not already logged in)

## Usage

### Verify connection
```bash
poetry run ytm-adder --login
```

### Process a CSV file
```bash
poetry run ytm-adder --csv path/to/hitster-de-aaaa0019.csv
```

### Options
- `--playlist "#3"` - Target playlist name (default: `#3`)
- `--start-from 50` - Skip to card number 50
- `--dry-run` - Preview without making changes
- `--clear-progress` - Reset progress and start fresh

## How it works

For each ISRC code in the CSV:
1. Searches YouTube Music for the ISRC
2. Navigates to the album
3. If album artist is "Various Artists" → adds just the song
4. Otherwise → adds the entire album to the playlist
5. Handles duplicate dialogs automatically

Progress is saved to `progress.json` so you can resume interrupted runs.
