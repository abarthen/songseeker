# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace Structure

This project uses a multi-folder workspace with two git repositories:
- `c:\Users\andreas\Projects\songseeker\` - Main web application (this repo)
- `c:\Users\andreas\Projects\songseeker-hitster-playlists\` - CSV playlist files mapping Hitster card IDs to YouTube URLs

## Project Overview

SongSeeker is a music guessing game web application inspired by Hitster and Rockster. Players scan QR codes containing song links, and the app plays the audio via YouTube while hiding song info for guessing.

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

## Architecture

**Single-page application** with three main files:
- `app.js` - All application logic (QR scanning, YouTube API, link parsing)
- `index.html` - UI structure
- `style.css` - Styling

**Core functionality in app.js:**
- QR scanning via [qr-scanner](https://github.com/nimiq/qr-scanner) library (imported from unpkg CDN)
- YouTube playback via YouTube IFrame API
- Link detection and parsing for three formats:
  - Direct YouTube links
  - Hitster links (`hitstergame.com/{lang}/{id}`) - looked up in CSV playlists
  - Rockster links (`rockster.brettspiel.digital/?yt={id}`)
- Random playback mode with configurable duration
- Cookie-based settings persistence

**Related repositories:**
- [songseeker-hitster-playlists](https://github.com/andygruber/songseeker-hitster-playlists) - CSV files mapping Hitster card IDs to YouTube URLs (included in workspace)
- [songseeker-card-generator](https://github.com/andygruber/songseeker-card-generator) - Generate QR code game cards
