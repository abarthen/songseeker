#!/usr/bin/env node

/**
 * Plex Mapping Generator for SongSeeker
 *
 * This script reads Hitster CSV files and searches your Plex library
 * to create a mapping file (CardID → Plex track info).
 *
 * Usage:
 *   node generate-plex-mapping.js --server http://192.168.1.100:32400 --token YOUR_PLEX_TOKEN --csv ../path/to/hitster-de.csv
 *
 * Output:
 *   plex-mapping-de.json in current directory
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

// Parse command line arguments
function parseArgs() {
    const args = process.argv.slice(2);
    const config = {
        server: null,
        token: null,
        csv: null,
        output: null,
        help: false,
        debug: false,
        limit: 0  // 0 = no limit
    };

    for (let i = 0; i < args.length; i++) {
        switch (args[i]) {
            case '--server':
            case '-s':
                config.server = args[++i];
                break;
            case '--token':
            case '-t':
                config.token = args[++i];
                break;
            case '--csv':
            case '-c':
                config.csv = args[++i];
                break;
            case '--output':
            case '-o':
                config.output = args[++i];
                break;
            case '--help':
            case '-h':
                config.help = true;
                break;
            case '--debug':
            case '-d':
                config.debug = true;
                break;
            case '--limit':
            case '-l':
                config.limit = parseInt(args[++i], 10);
                break;
        }
    }

    return config;
}

function showHelp() {
    console.log(`
Plex Mapping Generator for SongSeeker

Usage:
  node generate-plex-mapping.js [options]

Options:
  --server, -s <url>     Plex server URL (e.g., http://192.168.1.100:32400)
  --token, -t <token>    Plex authentication token (X-Plex-Token)
  --csv, -c <path>       Path to Hitster CSV file (e.g., ../playlists/hitster-de.csv)
  --output, -o <path>    Output JSON file path (default: plex-mapping-{lang}.json)
  --debug, -d            Enable debug output for troubleshooting
  --limit, -l <num>      Only process first N songs (for testing)
  --help, -h             Show this help message

Example:
  node generate-plex-mapping.js -s http://192.168.1.100:32400 -t abc123 -c ../../songseeker-hitster-playlists/hitster-de.csv

Debug example (test with first 5 songs):
  node generate-plex-mapping.js -s http://192.168.1.100:32400 -t abc123 -c hitster-de.csv --debug --limit 5

Output files:
  plex-mapping-{lang}.json          Main mapping file (CardID -> Plex track info)
  plex-mapping-{lang}-missing-soundiiz.csv   For Soundiiz import (bulk playlist creation)
  plex-mapping-{lang}-missing-full.csv       With YouTube URLs for manual download

How to find your Plex token:
  1. Open Plex Web App and sign in
  2. Browse to any media item
  3. Click "Get Info" or view XML
  4. Look for "X-Plex-Token" in the URL

  Or visit: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
`);
}

// Parse CSV content
function parseCSV(text) {
    const lines = text.split('\n').filter(line => line.trim());
    return lines.map(line => {
        const result = [];
        let startValueIdx = 0;
        let inQuotes = false;
        for (let i = 0; i < line.length; i++) {
            if (line[i] === '"' && line[i - 1] !== '\\') {
                inQuotes = !inQuotes;
            } else if (line[i] === ',' && !inQuotes) {
                result.push(line.substring(startValueIdx, i).trim().replace(/^"(.*)"$/, '$1'));
                startValueIdx = i + 1;
            }
        }
        result.push(line.substring(startValueIdx).trim().replace(/^"(.*)"$/, '$1'));
        return result;
    });
}

// Make HTTP/HTTPS request to Plex
function plexRequest(url, token) {
    return new Promise((resolve, reject) => {
        const fullUrl = new URL(url);
        fullUrl.searchParams.set('X-Plex-Token', token);

        const protocol = fullUrl.protocol === 'https:' ? https : http;
        const options = {
            hostname: fullUrl.hostname,
            port: fullUrl.port || (fullUrl.protocol === 'https:' ? 443 : 80),
            path: fullUrl.pathname + fullUrl.search,
            method: 'GET',
            headers: {
                'Accept': 'application/json'
            }
        };

        const req = protocol.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    reject(new Error(`Failed to parse Plex response: ${e.message}`));
                }
            });
        });

        req.on('error', reject);
        req.end();
    });
}

// Search Plex library for a track
async function searchPlex(serverUrl, token, artist, title, expectedYear, debug = false) {
    // Clean up search terms
    const cleanArtist = artist.replace(/feat\..*/i, '').replace(/,.*/, '').trim();
    const cleanTitle = title.replace(/\(.*\)/g, '').replace(/\[.*\]/g, '').trim();
    const targetYear = parseInt(expectedYear, 10);

    // Try different search strategies
    const searchQueries = [
        cleanTitle,                        // Title only (most reliable)
        `${cleanArtist} ${cleanTitle}`,    // Full search
        cleanArtist                        // Artist only
    ];

    let bestMatch = null;
    let bestYearDiff = Infinity;

    for (const query of searchQueries) {
        try {
            const searchUrl = `${serverUrl}/search?query=${encodeURIComponent(query)}&type=10`; // type=10 is tracks
            if (debug) {
                console.log(`  DEBUG: Searching: ${searchUrl}`);
            }
            const response = await plexRequest(searchUrl, token);

            if (debug) {
                console.log(`  DEBUG: Response size: ${response.MediaContainer?.size || 0}`);
                if (response.MediaContainer?.Metadata) {
                    console.log(`  DEBUG: Found ${response.MediaContainer.Metadata.length} tracks`);
                }
            }

            if (response.MediaContainer && response.MediaContainer.Metadata) {
                const tracks = response.MediaContainer.Metadata;

                // Find best match
                for (const track of tracks) {
                    const trackTitle = (track.title || '').toLowerCase();
                    const trackArtist = (track.grandparentTitle || track.originalTitle || '').toLowerCase();
                    const trackYear = track.parentYear || track.year;

                    if (debug) {
                        console.log(`  DEBUG: Checking: "${track.title}" by "${track.grandparentTitle || track.originalTitle}" (${trackYear})`);
                    }

                    // Check if this is a reasonable match
                    const titleMatch = trackTitle.includes(cleanTitle.toLowerCase()) ||
                        cleanTitle.toLowerCase().includes(trackTitle);
                    const artistMatch = trackArtist.includes(cleanArtist.toLowerCase()) ||
                        cleanArtist.toLowerCase().includes(trackArtist);

                    if (titleMatch && artistMatch) {
                        const yearDiff = Math.abs((trackYear || 0) - targetYear);

                        if (debug) {
                            console.log(`  DEBUG: Match found! Year diff: ${yearDiff} (track: ${trackYear}, expected: ${targetYear})`);
                        }

                        // Track the best match by year proximity
                        if (yearDiff < bestYearDiff) {
                            bestYearDiff = yearDiff;
                            bestMatch = {
                                ratingKey: track.ratingKey,
                                title: track.title,
                                artist: track.grandparentTitle || track.originalTitle,
                                album: track.parentTitle,
                                year: trackYear,
                                duration: track.duration,
                                partKey: track.Media?.[0]?.Part?.[0]?.key
                            };

                            // If exact year match, we're done
                            if (yearDiff === 0) {
                                if (debug) {
                                    console.log(`  DEBUG: Exact year match!`);
                                }
                                return bestMatch;
                            }
                        }
                    }
                }
            }
        } catch (e) {
            if (debug) {
                console.log(`  DEBUG: Search error: ${e.message}`);
            }
            // Continue to next search strategy
        }
    }

    // Only return exact year matches
    if (bestMatch && bestYearDiff === 0) {
        return bestMatch;
    }

    if (debug && bestMatch) {
        console.log(`  DEBUG: Rejecting match - year mismatch (${bestMatch.year} vs expected ${targetYear})`);
    }

    return null;
}

// Main function
async function main() {
    const config = parseArgs();

    if (config.help) {
        showHelp();
        process.exit(0);
    }

    // Validate required arguments
    if (!config.server || !config.token || !config.csv) {
        console.error('Error: Missing required arguments.');
        console.error('Use --help for usage information.');
        process.exit(1);
    }

    // Normalize server URL (remove trailing slash)
    config.server = config.server.replace(/\/$/, '');

    // Read and parse CSV
    const csvPath = path.resolve(config.csv);
    if (!fs.existsSync(csvPath)) {
        console.error(`Error: CSV file not found: ${csvPath}`);
        process.exit(1);
    }

    console.log(`Reading CSV: ${csvPath}`);
    const csvContent = fs.readFileSync(csvPath, 'utf-8');
    const csvData = parseCSV(csvContent);

    // Get column indices
    const headers = csvData[0];
    const cardIndex = headers.indexOf('Card#');
    const artistIndex = headers.indexOf('Artist');
    const titleIndex = headers.indexOf('Title');
    const yearIndex = headers.indexOf('Year');
    const urlIndex = headers.indexOf('URL');

    if (cardIndex === -1 || artistIndex === -1 || titleIndex === -1) {
        console.error('Error: CSV must have Card#, Artist, and Title columns');
        console.error('Found headers:', headers);
        process.exit(1);
    }

    // Test Plex connection
    console.log(`Testing Plex connection: ${config.server}`);
    try {
        const serverInfo = await plexRequest(`${config.server}/`, config.token);
        if (serverInfo.MediaContainer) {
            console.log(`Plex connection successful!`);
            console.log(`  Server: ${serverInfo.MediaContainer.friendlyName || 'Unknown'}`);
            console.log(`  Version: ${serverInfo.MediaContainer.version || 'Unknown'}`);
        } else {
            console.log('Plex connection successful (no server info available)');
        }
    } catch (e) {
        console.error(`Error: Cannot connect to Plex server: ${e.message}`);
        if (config.debug) {
            console.error('Full error:', e);
        }
        process.exit(1);
    }

    // Test search functionality
    console.log(`\nTesting Plex search API...`);
    try {
        const testSearch = await plexRequest(`${config.server}/search?query=test&type=10`, config.token);
        if (testSearch.MediaContainer !== undefined) {
            console.log(`Search API working! (Found ${testSearch.MediaContainer.size || 0} results for "test")`);
        } else {
            console.log('Warning: Search API response format unexpected');
            if (config.debug) {
                console.log('Response:', JSON.stringify(testSearch, null, 2).slice(0, 500));
            }
        }
    } catch (e) {
        console.error(`Warning: Search API test failed: ${e.message}`);
    }

    // Process each song
    const mapping = {};
    let songs = csvData.slice(1);
    let found = 0;
    let notFound = 0;

    // Apply limit if specified
    if (config.limit > 0) {
        songs = songs.slice(0, config.limit);
        console.log(`\nProcessing first ${config.limit} songs (limit applied)...\n`);
    } else {
        console.log(`\nProcessing ${songs.length} songs...\n`);
    }

    for (let i = 0; i < songs.length; i++) {
        const row = songs[i];
        const cardId = row[cardIndex];
        const artist = row[artistIndex];
        const title = row[titleIndex];
        const year = row[yearIndex];

        if (config.debug) {
            console.log(`\n[${i + 1}/${songs.length}] Searching: "${artist}" - "${title}" (${year})`);
        } else {
            process.stdout.write(`[${i + 1}/${songs.length}] Searching: ${artist} - ${title} (${year})... `);
        }

        const plexTrack = await searchPlex(config.server, config.token, artist, title, year, config.debug);

        if (plexTrack) {
            mapping[cardId] = plexTrack;
            if (config.debug) {
                console.log(`  FOUND: ${plexTrack.artist} - ${plexTrack.title} (key: ${plexTrack.ratingKey})`);
            } else {
                console.log(`FOUND (${plexTrack.artist} - ${plexTrack.title})`);
            }
            found++;
        } else {
            mapping[cardId] = null;
            if (config.debug) {
                console.log(`  NOT FOUND`);
            } else {
                console.log('NOT FOUND');
            }
            notFound++;
        }

        // Small delay to avoid overwhelming Plex
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Determine output filename with timestamp
    const now = new Date();
    const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);

    let outputPath = config.output;
    if (!outputPath) {
        const csvBasename = path.basename(config.csv, '.csv');
        const lang = csvBasename.replace('hitster-', '');
        outputPath = `plex-mapping-${lang}_${timestamp}.json`;
    }

    // Write output
    fs.writeFileSync(outputPath, JSON.stringify(mapping, null, 2));

    // Generate missing songs CSV for Soundiiz import
    const missingSongs = [];
    for (let i = 0; i < songs.length; i++) {
        const row = songs[i];
        const cardId = row[cardIndex];
        if (mapping[cardId] === null) {
            missingSongs.push({
                artist: row[artistIndex],
                title: row[titleIndex],
                year: row[yearIndex],
                url: urlIndex !== -1 ? row[urlIndex] : ''
            });
        }
    }

    if (missingSongs.length > 0) {
        // Escape helper for CSV
        const escapeCSV = (str) => {
            if (!str) return '';
            if (str.includes(',') || str.includes('"')) {
                return `"${str.replace(/"/g, '""')}"`;
            }
            return str;
        };

        // Soundiiz CSV format: Track Name, Artist Name, Album Name (optional)
        const soundiizHeader = 'Track Name,Artist Name,Album Name';
        const soundiizRows = missingSongs.map(song => {
            return `${escapeCSV(song.title)},${escapeCSV(song.artist)},`;
        });
        const soundiizContent = [soundiizHeader, ...soundiizRows].join('\n');

        const soundiizPath = outputPath.replace('.json', '-missing-soundiiz.csv');
        fs.writeFileSync(soundiizPath, soundiizContent);

        console.log(`\nSoundiiz CSV saved to: ${soundiizPath}`);
        console.log(`  → Upload to Soundiiz (soundiiz.com) to create a YouTube Music playlist`);
        console.log(`  → Then download with Noteburner and add to Plex`);

        // Full details CSV with YouTube Music URLs for playlist import
        const fullHeader = 'Artist,Title,Year,YouTube Music URL';
        const fullRows = missingSongs.map(song => {
            // Convert YouTube URL to YouTube Music URL
            let ytMusicUrl = song.url;
            if (ytMusicUrl) {
                // Handle youtu.be short URLs
                const shortMatch = ytMusicUrl.match(/youtu\.be\/([a-zA-Z0-9_-]+)/);
                if (shortMatch) {
                    ytMusicUrl = `https://music.youtube.com/watch?v=${shortMatch[1]}`;
                } else {
                    // Handle regular youtube.com URLs
                    ytMusicUrl = ytMusicUrl.replace('https://www.youtube.com/', 'https://music.youtube.com/');
                    ytMusicUrl = ytMusicUrl.replace('https://youtube.com/', 'https://music.youtube.com/');
                }
            }
            return `${escapeCSV(song.artist)},${escapeCSV(song.title)},${escapeCSV(song.year)},${escapeCSV(ytMusicUrl)}`;
        });
        const fullContent = [fullHeader, ...fullRows].join('\n');

        const fullPath = outputPath.replace('.json', '-missing-full.csv');
        fs.writeFileSync(fullPath, fullContent);

        console.log(`\nFull details CSV saved to: ${fullPath}`);
        console.log(`  → Contains YouTube Music URLs for playlist creation`);
    }

    console.log(`\n========================================`);
    console.log(`Results:`);
    console.log(`  Found in Plex: ${found}`);
    console.log(`  Not found:     ${notFound}`);
    console.log(`  Total:         ${songs.length}`);
    console.log(`  Match rate:    ${((found / songs.length) * 100).toFixed(1)}%`);
    console.log(`\nMapping saved to: ${outputPath}`);
    console.log(`========================================\n`);
}

main().catch(e => {
    console.error(`Fatal error: ${e.message}`);
    process.exit(1);
});
