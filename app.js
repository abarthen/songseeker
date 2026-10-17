import QrScanner from "https://unpkg.com/qr-scanner/qr-scanner.min.js";
import { playerManager } from "./player-manager.js";
import { lookupReleaseYear } from "./musicbrainz.js";

let playbackTimer; // hold the timer reference
let playbackDuration = 30; // Default playback duration
let qrScanner;
let lastDecodedText = ""; // Store the last decoded text
let currentStartTime = 0;
let autoShowSonginfoTimer = null; // Timer for auto-showing song info
let progressBarInterval = null; // Timer for updating progress bar
const selectedGames = new Set(); // Game editions selected for random playback
const selectedPlaylists = new Set(); // Plex playlist rating keys selected for random playback
let gameMode = 'hitster'; // 'hitster' (scan cards) or 'plex' (random songs from Plex)

// Button state management
// States: 'disabled' (grey, no song), 'loading' (green, loading), 'ready' (green, play),
//         'playing' (yellow, pause), 'ended' (green, replay)
function setButtonState(state) {
    const btn = document.getElementById('startstop-song');
    const seekBack = document.getElementById('seek-back');
    const seekForward = document.getElementById('seek-forward');

    // Remove all state classes
    btn.classList.remove('loading', 'ready', 'playing', 'ended');
    btn.disabled = false;

    switch(state) {
        case 'disabled':
            btn.disabled = true;
            btn.textContent = 'Play';
            seekBack.disabled = true;
            seekForward.disabled = true;
            break;
        case 'loading':
            btn.disabled = true;
            btn.classList.add('loading');
            btn.textContent = 'Loading...';
            seekBack.disabled = true;
            seekForward.disabled = true;
            break;
        case 'ready':
            btn.classList.add('ready');
            btn.textContent = 'Play';
            // Enable seek buttons when a song is ready
            seekBack.disabled = false;
            seekForward.disabled = false;
            break;
        case 'playing':
            btn.classList.add('playing');
            btn.textContent = 'Pause';
            seekBack.disabled = false;
            seekForward.disabled = false;
            break;
        case 'ended':
            btn.classList.add('ended');
            btn.textContent = 'Replay';
            seekBack.disabled = false;
            seekForward.disabled = false;
            break;
    }

    // Update progress bar visibility based on current state and checkbox
    updateProgressBarVisibility();
}

// Plex integration
let plexMappingCache = {}; // In-memory cache for Plex mappings
let plexConfig = { serverUrl: '', token: '' }; // Loaded from plex-config.json
let plexGames = {}; // Game names from manifest (mapping -> name)
let plexMatchRates = {}; // Match rates from manifest (mapping -> rate)
let plexDateRanges = {}; // Date ranges from manifest (mapping -> {min, max})
let plexSongCounts = {}; // Song counts from manifest (mapping -> count)
let plexTrackIndex = new Map(); // ratingKey -> [{ track, game, scannedKey? }] across all mappings
let plexPlaylists = []; // [{ ratingKey, title, leafCount, smart }] audio playlists on the server
const plexPlaylistSizes = {}; // playlist ratingKey -> number of playable items

// Function to detect iOS devices
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}

// Load Plex config from file
async function loadPlexConfig() {
    try {
        const response = await fetch('/plex-config.json');
        if (response.ok) {
            plexConfig = await response.json();
            console.log('Plex config loaded');
        }
    } catch (e) {
        console.error('Failed to load plex-config.json:', e);
    }
}

// Load Plex mappings from root directory
async function loadPlexMappings() {
    // First, try to load the manifest to see which mappings are available
    let availableLangs = [];
    try {
        const manifestResponse = await fetch('/plex-manifest.json');
        if (manifestResponse.ok) {
            const manifest = await manifestResponse.json();
            // New format: games is an array of objects
            const games = manifest.games || [];
            availableLangs = games.map(g => g.mapping);
            // Build lookup objects for compatibility
            plexGames = {};
            plexMatchRates = {};
            plexDateRanges = {};
            plexSongCounts = {};
            games.forEach(g => {
                plexGames[g.mapping] = g.name;
                plexMatchRates[g.mapping] = g.matchRate;
                if (g.minDate && g.maxDate) {
                    plexDateRanges[g.mapping] = { min: g.minDate, max: g.maxDate };
                }
                if (g.songCount) {
                    plexSongCounts[g.mapping] = g.songCount;
                }
            });
            console.log('Loaded manifest:', availableLangs);
            console.log('Loaded games:', plexGames);
            console.log('Loaded match rates:', plexMatchRates);
            console.log('Loaded date ranges:', plexDateRanges);
            console.log('Loaded song counts:', plexSongCounts);
        }
    } catch (e) {
        console.log('No manifest found, skipping mapping load');
    }

    // Only load mappings listed in the manifest
    for (const lang of availableLangs) {
        try {
            const url = `/plex-mapping-${lang}.json`;
            console.log(`Fetching mapping: ${url}`);
            const response = await fetch(url);
            if (response.ok) {
                const mapping = await response.json();
                plexMappingCache[lang] = mapping;
                const trackCount = Object.values(mapping).filter(v => v !== null).length;
                console.log(`Loaded Plex mapping for ${lang}: ${trackCount} tracks`);
            } else {
                console.error(`Failed to fetch mapping for ${lang}: HTTP ${response.status}`);
            }
        } catch (e) {
            console.error(`Failed to load mapping for ${lang}:`, e);
        }
    }
    buildPlexTrackIndex();
    pruneSelectedGames();
    updateStartButtonMode();
    if (document.getElementById('gameEditions_div')?.style.display !== 'none') {
        // Re-render if the panel happens to be open
        updateGameEditionsList();
    }
    updatePlexMappingStatus();
}

// Plex helper functions
function getPlexSettings() {
    return {
        serverUrl: plexConfig.serverUrl || '',
        token: plexConfig.token || ''
    };
}

function getPlexMapping(lang) {
    return plexMappingCache[lang] || {};
}

function lookupPlexTrack(cardId, lang) {
    const mapping = getPlexMapping(lang);
    // Normalize card ID by removing leading zeros (00257 -> 257)
    const normalizedId = String(parseInt(cardId, 10));
    return mapping[normalizedId] || null;
}

// Index every mapped track by ratingKey, in manifest order, so a lookup
// finds all editions containing a song.
function buildPlexTrackIndex() {
    plexTrackIndex = new Map();
    const add = (key, entry) => {
        if (!plexTrackIndex.has(key)) plexTrackIndex.set(key, []);
        plexTrackIndex.get(key).push(entry);
    };
    for (const game of Object.keys(plexMappingCache)) {
        for (const track of Object.values(plexMappingCache[game])) {
            if (!track || !track.ratingKey) continue;
            add(track.ratingKey, { track, game });
            // Old ratingKey on printed card, new ratingKey in mapping (track replaced in Plex)
            for (const altKey of track.alternativeKeys || []) {
                add(altKey, { track, game, scannedKey: altKey });
            }
        }
    }
}

function isSameSongInfo(a, b) {
    return a.artist === b.artist && a.title === b.title && a.year === b.year;
}

// Look up a song in all edition mappings. Editions are the source of truth;
// if they disagree, the first one wins and the others are reported as conflicts.
function lookupPlexTrackByRatingKey(ratingKey) {
    const entries = plexTrackIndex.get(ratingKey);
    if (!entries) return null;
    const direct = entries.filter(e => !e.scannedKey);
    const candidates = direct.length > 0 ? direct : entries;
    const first = candidates[0];
    const conflicts = candidates.filter(e => !isSameSongInfo(e.track, first.track));
    if (first.scannedKey) {
        console.log(`Found via alternativeKeys: ${ratingKey} -> ${first.track.ratingKey}`);
    }
    if (conflicts.length > 0) {
        console.warn(`Conflicting song info for ratingKey ${ratingKey}:`, candidates);
    }
    return { ...first, conflicts };
}

function isPlexConfigured() {
    const settings = getPlexSettings();
    return settings.serverUrl && settings.token;
}

function hasPlexMapping(lang) {
    const mapping = getPlexMapping(lang);
    return Object.keys(mapping).length > 0;
}

// Plex library random playback (Plex Mode without any edition selected)
let plexMusicSections = null; // [{ key, totalSize }], counted once and cached

function plexUrl(path) {
    const separator = path.includes('?') ? '&' : '?';
    return `${plexConfig.serverUrl.replace(/\/$/, '')}${path}${separator}X-Plex-Token=${plexConfig.token}`;
}

async function fetchPlexJson(path) {
    const response = await fetch(plexUrl(path), {
        headers: { 'Accept': 'application/json' }
    });
    if (!response.ok) {
        throw new Error(`Plex request failed: HTTP ${response.status}`);
    }
    return response.json();
}

// Find all music libraries and their track counts. A container size of 0
// returns only totalSize, so no track list is transferred.
async function fetchPlexMusicSections() {
    const data = await fetchPlexJson('/library/sections');
    const musicSections = (data.MediaContainer.Directory || []).filter(d => d.type === 'artist');
    const sections = [];
    for (const section of musicSections) {
        const countData = await fetchPlexJson(
            `/library/sections/${section.key}/all?type=10&X-Plex-Container-Start=0&X-Plex-Container-Size=0`);
        const totalSize = countData.MediaContainer.totalSize || 0;
        if (totalSize > 0) {
            sections.push({ key: section.key, totalSize });
        }
    }
    console.log('Plex music sections:', sections);
    return sections;
}

// Pick a random track across all music libraries by fetching a single
// track at a random offset.
async function fetchRandomLibraryTrack() {
    if (!plexMusicSections) {
        plexMusicSections = await fetchPlexMusicSections();
    }
    const total = plexMusicSections.reduce((sum, s) => sum + s.totalSize, 0);
    if (total === 0) return null;

    let offset = Math.floor(Math.random() * total);
    const section = plexMusicSections.find(s => {
        if (offset < s.totalSize) return true;
        offset -= s.totalSize;
        return false;
    });

    const data = await fetchPlexJson(
        `/library/sections/${section.key}/all?type=10&X-Plex-Container-Start=${offset}&X-Plex-Container-Size=1&includeGuids=1`);
    const item = data.MediaContainer.Metadata?.[0];
    if (!item) {
        // Library shrank since it was counted; recount on the next request
        plexMusicSections = null;
        return null;
    }
    // List responses don't include field locks, so load the full track
    return fetchPlexTrack(item.ratingKey);
}

// Convert Plex track metadata (from /library/metadata with includeGuids=1)
// to mapping-style track info
function plexItemToTrack(item) {
    const mbidGuid = (item.Guid || []).find(g => g.id.startsWith('mbid://'));
    return {
        ratingKey: String(item.ratingKey),
        title: item.title,
        artist: item.originalTitle || item.grandparentTitle,
        album: item.parentTitle,
        // Tracks rarely carry their own year; fall back to the album year.
        // Unreliable unless locked, so otherwise only used if MusicBrainz has nothing.
        year: item.year || item.parentYear,
        // A locked track year was verified by SongSeeker (or set by hand) and is trusted
        yearVerified: !!item.year && (item.Field || []).some(f => f.name === 'year' && f.locked),
        librarySectionID: item.librarySectionID,
        mbid: mbidGuid ? mbidGuid.id.slice('mbid://'.length) : undefined
    };
}

let plexYearWritesEnabled = true; // Turned off after a failed automatic write, e.g. token without edit rights

// Store a year on the Plex track and lock it, so Plex keeps it and later
// lookups can trust it. Only the track is changed, not its album.
// Returns true on success.
async function writePlexYear(ratingKey, librarySectionID, year) {
    try {
        const response = await fetch(plexUrl(
            `/library/sections/${librarySectionID}/all?type=10&id=${encodeURIComponent(ratingKey)}&year.value=${year}&year.locked=1`),
            { method: 'PUT' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        console.log(`Saved year ${year} to Plex track ${ratingKey}`);
        return true;
    } catch (e) {
        console.error(`Saving year to Plex track ${ratingKey} failed:`, e);
        return false;
    }
}

// Automatic write of a verified year, subject to the "Save verified years to Plex" setting
async function saveYearToPlex(ratingKey, librarySectionID, year) {
    if (!plexYearWritesEnabled || !document.getElementById('saveYearsToPlex').checked) return;
    if (!await writePlexYear(ratingKey, librarySectionID, year)) {
        plexYearWritesEnabled = false;
        console.error('Not saving years to Plex again this session');
    }
}

// Edition years are the source of truth; copy them to Plex where Plex differs
async function syncEditionYearToPlex(track) {
    if (!track.year) return;
    try {
        const plexTrack = await fetchPlexTrack(track.ratingKey);
        if (plexTrack && !(plexTrack.yearVerified && plexTrack.year === track.year)) {
            await saveYearToPlex(plexTrack.ratingKey, plexTrack.librarySectionID, track.year);
        }
    } catch (e) {
        console.error('Failed to check Plex year:', e);
    }
}

async function fetchPlexTrack(ratingKey) {
    const data = await fetchPlexJson(`/library/metadata/${encodeURIComponent(ratingKey)}?includeGuids=1`);
    const item = data.MediaContainer.Metadata?.[0];
    return item && item.type === 'track' ? plexItemToTrack(item) : null;
}

async function loadPlexPlaylists() {
    if (!isPlexConfigured()) return;
    try {
        const data = await fetchPlexJson('/playlists?playlistType=audio');
        plexPlaylists = (data.MediaContainer.Metadata || []).map(p => ({
            ratingKey: String(p.ratingKey),
            title: p.title,
            leafCount: p.leafCount || 0,
            smart: !!p.smart
        }));
        console.log('Loaded Plex playlists:', plexPlaylists.length);
    } catch (e) {
        console.error('Failed to load Plex playlists:', e);
        return;
    }
    pruneSelectedPlaylists();
    if (document.getElementById('gameEditions_div')?.style.display !== 'none') {
        updatePlexPlaylistsList();
    }
}

// leafCount can include items that are no longer playable, so count the
// items the playlist actually returns.
async function fetchPlaylistSize(playlistKey) {
    if (!(playlistKey in plexPlaylistSizes)) {
        const data = await fetchPlexJson(
            `/playlists/${playlistKey}/items?X-Plex-Container-Start=0&X-Plex-Container-Size=0`);
        plexPlaylistSizes[playlistKey] = data.MediaContainer.totalSize || 0;
    }
    return plexPlaylistSizes[playlistKey];
}

async function fetchPlaylistTrack(playlistKey, offset) {
    const data = await fetchPlexJson(
        `/playlists/${playlistKey}/items?X-Plex-Container-Start=${offset}&X-Plex-Container-Size=1&includeGuids=1`);
    const item = data.MediaContainer.Metadata?.[0];
    if (!item) {
        // Playlist changed since it was counted; recount on the next request
        delete plexPlaylistSizes[playlistKey];
        return null;
    }
    // List responses don't include field locks, so load the full track
    return fetchPlexTrack(item.ratingKey);
}

async function testPlexConnection() {
    try {
        const url = `${plexConfig.serverUrl.replace(/\/$/, '')}/?X-Plex-Token=${plexConfig.token}`;
        const response = await fetch(url, {
            headers: { 'Accept': 'application/json' }
        });
        return response.ok;
    } catch (e) {
        console.error('Plex connection test failed:', e);
        return false;
    }
}

document.addEventListener('DOMContentLoaded', function () {

    const video = document.getElementById('qr-video');
    const resultContainer = document.getElementById("qr-reader-results");

    // If the user is on an iOS device, uncheck and disable the autoplay checkbox
    if (isIOS()) {
        var autoplayCheckbox = document.getElementById('autoplay');
        autoplayCheckbox.checked = false;
        autoplayCheckbox.disabled = true;
    }

    qrScanner = new QrScanner(video, result => {
        console.log('decoded qr code:', result);
        if (result.data !== lastDecodedText) {
            lastDecodedText = result.data; // Update the last decoded text
            handleScannedLink(result.data);
        }
    }, {
        highlightScanRegion: true,
        highlightCodeOutline: true,
    }
    );

    // Set up player manager state change callback
    playerManager.onStateChange(handlePlayerStateChange);
});

// Function to determine the type of link and act accordingly
async function handleScannedLink(decodedText) {
    // Stop any current playback and reset button state
    if (playbackTimer) {
        clearTimeout(playbackTimer);
        playbackTimer = null;
    }
    // Clear auto-show timer and reset reveal state for the new song
    if (autoShowSonginfoTimer) {
        clearTimeout(autoShowSonginfoTimer);
        autoShowSonginfoTimer = null;
    }
    resetSongInfoForNewSong();

    playerManager.stop();
    setButtonState('loading');

    let songInfo = null;  // See displayTrack
    let plexDebugInfo = "";
    let hitsterData = null;
    let customGameKey = null;  // Set when a plex:XXXXX card was scanned

    if (isPlexRatingKey(decodedText)) {
        // Direct rating key from custom game card (plex:12345)
        const ratingKey = parsePlexRatingKey(decodedText);
        customGameKey = ratingKey;
        console.log("Custom game card, rating key:", ratingKey);

        if (!plexConfig.serverUrl) {
            plexDebugInfo = "No server URL in config";
        } else if (!plexConfig.token) {
            plexDebugInfo = "No token in config";
        } else {
            // Look up track info from loaded mappings first, then fall back to Plex itself
            const result = lookupPlexTrackByRatingKey(ratingKey);
            if (result) {
                songInfo = { track: result.track, edition: result.game, conflicts: result.conflicts, scannedKey: result.scannedKey };
                plexDebugInfo = `Found: ${result.track.artist} - ${result.track.title}`;
                console.log(`Found in mapping (${result.game}):`, result.track.artist, "-", result.track.title);
            } else {
                let plexTrack = null;
                try {
                    plexTrack = await fetchPlexTrack(ratingKey);
                } catch (e) {
                    console.error('Failed to fetch track from Plex:', e);
                }
                if (plexTrack) {
                    songInfo = { track: plexTrack, edition: null };
                    plexDebugInfo = `Found in Plex: ${plexTrack.artist} - ${plexTrack.title}`;
                    console.log('Rating key not in any mapping, using Plex:', plexTrack.artist, "-", plexTrack.title);
                } else {
                    plexDebugInfo = `Rating key ${ratingKey} not found in mappings or Plex`;
                    console.log('Rating key not found in any mapping or in Plex');
                }
            }
        }
    } else if (isHitsterLink(decodedText)) {
        hitsterData = parseHitsterUrl(decodedText);
        if (hitsterData) {
            console.log("Hitster data:", hitsterData.id, hitsterData.lang);

            // Check Plex configuration
            const plexConfigured = isPlexConfigured();
            const hasMapping = hasPlexMapping(hitsterData.lang);

            console.log(`Plex check: configured=${plexConfigured}, hasMapping=${hasMapping}`);

            if (!plexConfig.serverUrl) {
                plexDebugInfo = `No server URL in config`;
            } else if (!plexConfig.token) {
                plexDebugInfo = `No token in config`;
            } else if (!hasMapping) {
                plexDebugInfo = `No mapping for lang=${hitsterData.lang}`;
            } else {
                const normalizedCardId = String(parseInt(hitsterData.id, 10));
                const plexTrackInfo = lookupPlexTrack(hitsterData.id, hitsterData.lang);
                if (plexTrackInfo) {
                    songInfo = { track: plexTrackInfo, edition: hitsterData.lang };
                    console.log(`Found in Plex: ${plexTrackInfo.artist} - ${plexTrackInfo.title}`);
                    plexDebugInfo = `Found: ${plexTrackInfo.artist} - ${plexTrackInfo.title}`;
                } else {
                    plexDebugInfo = `Card #${normalizedCardId} not in mapping (lang=${hitsterData.lang})`;
                    console.log('Card not found in Plex mapping');
                }
            }
        } else {
            console.log("Invalid Hitster URL:", decodedText);
            plexDebugInfo = "Invalid Hitster URL";
        }
    } else {
        plexDebugInfo = "Unknown link format";
    }

    // Hide scanner UI
    qrScanner.stop();
    document.getElementById('qr-reader').style.display = 'none';
    document.getElementById('cancelScanButton').style.display = 'none';
    lastDecodedText = "";

    // Handle Plex playback
    if (songInfo) {
        const plexSettings = getPlexSettings();
        playerManager.initPlexPlayer(plexSettings.serverUrl, plexSettings.token);
        displayTrack(songInfo);

        currentStartTime = 0;
        await playerManager.cue({ trackInfo: songInfo.track });
    } else if (hitsterData) {
        // Card was recognized but not matched in Plex
        const normalizedCardId = String(parseInt(hitsterData.id, 10));
        showSongError(`Card #${normalizedCardId} not available`);
    } else if (customGameKey) {
        // Custom game card was scanned but not found in any mapping or in Plex
        showSongError(`Card ${customGameKey} not available`);
    } else {
        showSongError('Unknown QR code format');
    }
}

function isPlexRatingKey(input) {
    // Match "plex:12345" format from custom game cards
    return /^plex:\d+$/.test(input);
}

function parsePlexRatingKey(input) {
    const match = input.match(/^plex:(\d+)$/);
    return match ? match[1] : null;
}

function isHitsterLink(url) {
    // Regular expression to match with or without "http://" or "https://"
    const regex = /^(?:http:\/\/|https:\/\/)?(www\.hitstergame|app\.hitsternordics)\.com\/.+/;
    return regex.test(url);
}

// Example implementation for parseHitsterUrl
function parseHitsterUrl(url) {
    const regex = /^(?:http:\/\/|https:\/\/)?www\.hitstergame\.com\/(.+?)\/(\d+)$/;
    const match = url.match(regex);
    if (match) {
        // Hitster URL is in the format: https://www.hitstergame.com/{lang}/{id}
        // lang can be things like "en", "de", "pt", etc., but also "de/aaaa0007"
        const processedLang = match[1].replace(/\//g, "-");
        return { lang: processedLang, id: match[2] };
    }
    const regex_nordics = /^(?:http:\/\/|https:\/\/)?app.hitster(nordics).com\/resources\/songs\/(\d+)$/;
    const match_nordics = url.match(regex_nordics);
    if (match_nordics) {
        // Hitster URL can also be in the format: https://app.hitsternordics.com/resources/songs/{id}
        return { lang: match_nordics[1], id: match_nordics[2] };
    }
    return null;
}

// Unified state change handler for Plex
function handlePlayerStateChange(event) {
    const state = event.data;
    const PlayerState = playerManager.PlayerState;

    if (state === PlayerState.CUED) {
        setButtonState('ready');

        // Wait for duration to be available, then update progress bar
        setTimeout(() => {
            updateProgressBar();
            updateProgressBarVisibility();
        }, 500);

        // Handle autoplay
        if (isIOS()) {
            playerManager.play();
            startAutoShowTimer();
        } else if (document.getElementById('autoplay').checked) {
            setButtonState('playing');
            if (document.getElementById('randomplayback').checked) {
                playSongAtRandomStartTime();
            } else {
                playerManager.play();
            }
            startAutoShowTimer();
        }
    } else if (state === PlayerState.PLAYING) {
        setButtonState('playing');
        startProgressBarUpdate();
    } else if (state === PlayerState.PAUSED) {
        setButtonState('ready');
        stopProgressBarUpdate();
    } else if (state === PlayerState.ENDED) {
        setButtonState('ended');
        stopProgressBarUpdate();
    } else if (state === PlayerState.BUFFERING) {
        // Keep playing state during buffering, just visual feedback handled by CSS
        setButtonState('playing');
    }
}

// Helper function to format duration from seconds to a more readable format
function formatDuration(duration) {
    var minutes = Math.floor(duration / 60);
    var seconds = Math.floor(duration % 60);
    return minutes + ":" + (seconds < 10 ? '0' : '') + seconds;
}

// Progress bar functions
function updateProgressBar() {
    const progressBar = document.getElementById('progress-bar');
    const currentTimeEl = document.getElementById('current-time');
    const totalTimeEl = document.getElementById('total-time');

    const currentTime = playerManager.getCurrentTime();
    const duration = playerManager.getDuration();

    if (duration > 0) {
        const percentage = (currentTime / duration) * 100;
        progressBar.value = percentage;
        progressBar.style.background = `linear-gradient(to right, var(--accent) 0%, var(--accent) ${percentage}%, rgba(255, 255, 255, 0.2) ${percentage}%)`;
        currentTimeEl.textContent = formatDuration(currentTime);
        totalTimeEl.textContent = formatDuration(duration);
    }
}

function startProgressBarUpdate() {
    stopProgressBarUpdate();
    progressBarInterval = setInterval(updateProgressBar, 250);
    updateSeekButtonsState(true);
}

function stopProgressBarUpdate() {
    if (progressBarInterval) {
        clearInterval(progressBarInterval);
        progressBarInterval = null;
    }
    updateSeekButtonsState(false);
}

function updateSeekButtonsState(enabled) {
    document.getElementById('seek-back').disabled = !enabled;
    document.getElementById('seek-forward').disabled = !enabled;
}

// Seek button handlers
function seekRelative(seconds) {
    const currentTime = playerManager.getCurrentTime();
    const duration = playerManager.getDuration();
    const newTime = Math.max(0, Math.min(duration, currentTime + seconds));
    playerManager.seekTo(newTime);
    updateProgressBar();
}

// Add event listeners to Play and Stop buttons
document.getElementById('startstop-song').addEventListener('click', function() {
    const isPlaying = this.classList.contains('playing');
    const isEnded = this.classList.contains('ended');

    if (isPlaying) {
        // Pause playback
        playerManager.pause();
        setButtonState('ready');
    } else {
        // Start or resume playback (handles both 'ready' and 'ended' states)
        setButtonState('playing');
        if (isEnded) {
            // Replay from beginning
            playerManager.seekTo(0);
        }
        if (document.getElementById('randomplayback').checked) {
            playSongAtRandomStartTime();
        } else {
            playerManager.play();
        }
        startAutoShowTimer();
    }
});

function playSongAtRandomStartTime() {
    playbackDuration = parseInt(document.getElementById('playback-duration').value, 10) || 30;

    playerManager.playAtRandomStartTime(playbackDuration, currentStartTime, () => {
        setButtonState('ended');
        stopProgressBarUpdate();
    });
}

// Seek button event listeners
document.getElementById('seek-back').addEventListener('click', function() {
    seekRelative(-30);
});

document.getElementById('seek-forward').addEventListener('click', function() {
    seekRelative(30);
});

// Progress bar seek event listener
document.getElementById('progress-bar').addEventListener('input', function() {
    const duration = playerManager.getDuration();
    if (duration > 0) {
        const seekTime = (this.value / 100) * duration;
        playerManager.seekTo(seekTime);
        updateProgressBar();
    }
});

// Assuming you have an element with the ID 'qr-reader' for the QR scanner
document.getElementById('qr-reader').style.display = 'none'; // Initially hide the QR Scanner

// Initially disable the play button until a song is scanned
setButtonState('disabled');

document.getElementById('startScanButton').addEventListener('click', function() {
    if (gameMode === 'plex') {
        playRandomSong();
        return;
    }
    resetSongInfoForNewSong();
    document.getElementById('cancelScanButton').style.display = 'block';
    document.getElementById('qr-reader').style.display = 'block'; // Show the scanner
    qrScanner.start().catch(err => {
        console.error('Unable to start QR Scanner', err);
        qrResult.textContent = "QR Scanner failed to start.";
    });

    qrScanner.start().then(() => {
        qrScanner.setInversionMode('both'); // we want to scan also for Hitster QR codes which use inverted colors
    });
});

function getSelectedTrackPool() {
    const pool = [];
    for (const lang of selectedGames) {
        const mapping = plexMappingCache[lang];
        if (!mapping) continue;
        for (const track of Object.values(mapping)) {
            if (track && track.ratingKey) {
                pool.push({ track, lang });
            }
        }
    }
    return pool;
}

async function playRandomSong() {
    if (playbackTimer) {
        clearTimeout(playbackTimer);
        playbackTimer = null;
    }
    if (autoShowSonginfoTimer) {
        clearTimeout(autoShowSonginfoTimer);
        autoShowSonginfoTimer = null;
    }
    resetSongInfoForNewSong();

    playerManager.stop();

    if (!isPlexConfigured()) {
        showSongError('Plex not configured');
        return;
    }

    setButtonState('loading');
    let songInfo = null;
    try {
        songInfo = await pickRandomSong();
    } catch (e) {
        console.error('Failed to pick a random song:', e);
    }
    if (!songInfo) {
        showSongError(selectedGames.size > 0 || selectedPlaylists.size > 0
            ? 'No songs in selected editions or playlists'
            : 'Could not get a song from Plex');
        return;
    }
    const track = songInfo.track;
    console.log(`Random song from ${songInfo.edition || 'Plex'}: ${track.artist} - ${track.title}`);

    const plexSettings = getPlexSettings();
    playerManager.initPlexPlayer(plexSettings.serverUrl, plexSettings.token);
    displayTrack(songInfo);

    currentStartTime = 0;
    await playerManager.cue({ trackInfo: track });
}

// Pick a random song from the selected editions and playlists, weighted by
// their size, or from the whole library when nothing is selected.
// Returns { track, edition, conflicts } (see displayTrack) or null.
async function pickRandomSong() {
    if (selectedGames.size === 0 && selectedPlaylists.size === 0) {
        return songInfoForPlexTrack(await fetchRandomLibraryTrack());
    }

    const editionPool = getSelectedTrackPool();
    const playlists = await Promise.all(Array.from(selectedPlaylists, async key => ({
        key,
        size: await fetchPlaylistSize(key)
    })));
    const total = playlists.reduce((sum, p) => sum + p.size, editionPool.length);
    if (total === 0) return null;

    let index = Math.floor(Math.random() * total);
    if (index < editionPool.length) {
        const pick = editionPool[index];
        return { track: pick.track, edition: pick.lang, conflicts: [] };
    }
    index -= editionPool.length;
    const playlist = playlists.find(p => {
        if (index < p.size) return true;
        index -= p.size;
        return false;
    });
    return songInfoForPlexTrack(await fetchPlaylistTrack(playlist.key, index));
}

// Song info for a track fetched from Plex: edition data wins if the song is in any edition
function songInfoForPlexTrack(plexTrack) {
    if (!plexTrack) return null;
    const mapped = lookupPlexTrackByRatingKey(plexTrack.ratingKey);
    if (mapped) {
        return { track: mapped.track, edition: mapped.game, conflicts: mapped.conflicts };
    }
    return { track: plexTrack, edition: null, conflicts: [] };
}

let currentSongId = 0; // Incremented per song so late year lookups don't overwrite a newer song
let editableYearTrack = null; // Plex track whose year can be edited, null for edition songs
const manuallySetYears = new Set(); // ratingKeys edited this session; pending lookups must not overwrite them

/**
 * Show song info for a new song.
 * @param {object} songInfo
 *   track      - Track info (ratingKey, artist, title, year, mbid)
 *   edition    - Mapping ID the info comes from, or null when it comes from Plex
 *   conflicts  - Other editions with different info for the same song
 *   scannedKey - Rating key on the scanned card, if it differs from the track's
 */
function displayTrack({ track, edition = null, conflicts = [], scannedKey = null }) {
    const songId = ++currentSongId;
    // Edition years come from git and would be overwritten on the next release
    setEditableYearTrack(edition ? null : track);

    document.getElementById('song-ratingkey').textContent = scannedKey && scannedKey !== track.ratingKey
        ? `${track.ratingKey} (card: ${scannedKey})`
        : track.ratingKey;
    document.getElementById('song-artist').textContent = track.artist;
    document.getElementById('song-title').textContent = track.title;
    document.getElementById('song-title').style.color = '';

    const sourceEl = document.getElementById('song-source');
    sourceEl.replaceChildren(createSourceBadge(edition ? 'edition' : 'plex'),
        ' ' + (edition ? (plexGames[edition] || edition) : 'Music library'));

    document.getElementById('song-warning').textContent = conflicts.map(c =>
        `Differs in ${plexGames[c.game] || c.game}: ${c.track.artist} - ${c.track.title} (${c.track.year})`
    ).join('\n');

    if (edition) {
        setSongYear(track.year || '', '');
        syncEditionYearToPlex(track);
        return;
    }

    if (track.yearVerified) {
        setSongYear(track.year, '(Plex, verified)');
        return;
    }

    setSongYear('…', '(looking up)');
    lookupReleaseYear(track, () => songId === currentSongId).then(year => {
        if (manuallySetYears.has(track.ratingKey)) return;
        if (year) {
            saveYearToPlex(track.ratingKey, track.librarySectionID, year);
        }
        if (songId !== currentSongId) return;
        if (year) {
            setSongYear(year, '(MusicBrainz)');
        } else if (track.year) {
            // undefined: lookup failed (e.g. rate limited), null: MusicBrainz has no match
            setSongYear(track.year, year === undefined
                ? '(Plex, unverified: MusicBrainz unavailable)'
                : '(Plex, unverified)');
        } else {
            setSongYear('unknown', '');
        }
    });
}

function setSongYear(year, note) {
    document.getElementById('song-year').textContent = year;
    document.getElementById('song-year-note').textContent = note;
}

function setEditableYearTrack(track) {
    editableYearTrack = track;
    document.getElementById('editYearButton').hidden = !track;
    document.getElementById('yearEditor').hidden = true;
}

document.getElementById('editYearButton').addEventListener('click', function() {
    const input = document.getElementById('yearEditInput');
    input.value = parseInt(document.getElementById('song-year').textContent, 10) || '';
    this.hidden = true;
    document.getElementById('yearEditor').hidden = false;
    input.focus();
});

document.getElementById('cancelYearButton').addEventListener('click', function() {
    setEditableYearTrack(editableYearTrack);
});

document.getElementById('saveYearButton').addEventListener('click', saveEditedYear);
document.getElementById('yearEditInput').addEventListener('keydown', function(event) {
    if (event.key === 'Enter') saveEditedYear();
    if (event.key === 'Escape') setEditableYearTrack(editableYearTrack);
});

// Manually corrected year: always written to Plex (explicit user action),
// regardless of the automatic save setting
async function saveEditedYear() {
    const track = editableYearTrack;
    const year = parseInt(document.getElementById('yearEditInput').value, 10);
    if (!track || !(year >= 1000 && year <= 2100)) return;

    manuallySetYears.add(track.ratingKey);
    setEditableYearTrack(track);
    setSongYear(year, '(saving…)');
    const saved = await writePlexYear(track.ratingKey, track.librarySectionID, year);
    if (editableYearTrack !== track) return; // Another song started meanwhile
    track.year = year;
    track.yearVerified = saved;
    setSongYear(year, saved ? '(edited, saved to Plex)' : '(edited, not saved: Plex error)');
}

function createSourceBadge(type) {
    const badge = document.createElement('span');
    badge.className = `source-badge source-badge-${type}`;
    badge.textContent = type === 'edition' ? 'Edition' : 'Plex';
    return badge;
}

function showSongError(message) {
    currentSongId++;
    setEditableYearTrack(null);
    document.getElementById('song-ratingkey').textContent = '';
    document.getElementById('song-artist').textContent = '';
    document.getElementById('song-title').textContent = message;
    document.getElementById('song-title').style.color = '#cc0000';
    setSongYear('', '');
    document.getElementById('song-source').replaceChildren();
    document.getElementById('song-warning').textContent = '';
    setButtonState('disabled');
}

function updateStartButtonMode() {
    const btn = document.getElementById('startScanButton');
    btn.textContent = gameMode === 'plex' ? 'Play Random Song' : 'Start Scan';
}

function setGameMode(mode) {
    gameMode = mode === 'plex' ? 'plex' : 'hitster';
    document.querySelectorAll('.mode-toggle-option').forEach(btn => {
        btn.setAttribute('aria-pressed', String(btn.dataset.mode === gameMode));
    });
    // Switches the color theme and the mode-specific (.plex-only/.hitster-only) elements
    document.documentElement.dataset.mode = gameMode;
    updateStartButtonMode();
    updateEditionsButtonLabel();
    updateGameEditionsList();
}

document.querySelectorAll('.mode-toggle-option').forEach(btn => {
    btn.addEventListener('click', function() {
        if (this.dataset.mode === gameMode) return;
        setGameMode(this.dataset.mode);
        document.cookie = "gameMode=" + gameMode + ";max-age=2592000"; //30 Tage
        listCookies();
    });
});

document.getElementById('debugButton').addEventListener('click', function() {
    handleScannedLink("https://www.hitstergame.com/de-aaaa0012/237");
});

// Track whether song info should always be shown
let songinfoAlwaysVisible = false;

const SONG_INFO_ROWS = ['ratingkeyrow', 'artistrow', 'titlerow', 'yearrow', 'sourcerow'];

function setSongInfoRowsDisplay(display) {
    SONG_INFO_ROWS.forEach(id => {
        document.getElementById(id).style.display = display;
    });
}

function showSongInfo() {
    setSongInfoRowsDisplay('block');
}

function hideSongInfo() {
    if (!songinfoAlwaysVisible) {
        setSongInfoRowsDisplay('none');
    }
}

// Reset reveal state so each new song starts with info hidden,
// regardless of whether it was revealed for the previous song.
function resetSongInfoForNewSong() {
    songinfoAlwaysVisible = false;
    setSongInfoRowsDisplay('none');
    document.getElementById('toggleSonginfoButton').textContent = 'Reveal Song Info';
    updateAutoShowCheckboxState();
}

function updateProgressBarVisibility() {
    const showProgressBar = document.getElementById('showProgressBar').checked;
    const btn = document.getElementById('startstop-song');
    const hasSong = !btn.disabled || btn.classList.contains('loading');

    if (showProgressBar && hasSong) {
        document.getElementById('progressrow').style.display = 'flex';
        updateProgressBar();
    } else {
        document.getElementById('progressrow').style.display = 'none';
    }
}

function updateAutoShowCheckboxState() {
    var autoShowCheckbox = document.getElementById('autoShowSonginfo');
    autoShowCheckbox.disabled = songinfoAlwaysVisible;
}

function startAutoShowTimer() {
    if (document.getElementById('autoShowSonginfo').checked && !songinfoAlwaysVisible) {
        if (autoShowSonginfoTimer) {
            clearTimeout(autoShowSonginfoTimer);
        }
        autoShowSonginfoTimer = setTimeout(function() {
            showSongInfo();
        }, 5000);
    }
}

document.getElementById('toggleSonginfoButton').addEventListener('click', function() {
    songinfoAlwaysVisible = !songinfoAlwaysVisible;
    if (songinfoAlwaysVisible) {
        showSongInfo();
        this.textContent = 'Hide Song Info';
    } else {
        hideSongInfo();
        this.textContent = 'Reveal Song Info';
    }
    updateAutoShowCheckboxState();
});

document.getElementById('cancelScanButton').addEventListener('click', function() {
    qrScanner.stop(); // Stop scanning after a result is found
    document.getElementById('qr-reader').style.display = 'none'; // Hide the scanner after successful scan
    document.getElementById('cancelScanButton').style.display = 'none'; // Hide the cancel-button
});

document.getElementById('toggleSettingsButton').addEventListener('click', function() {
    var settingsDiv = document.getElementById('settings_div');
    if (settingsDiv.style.display === 'none' || settingsDiv.style.display === '') {
        settingsDiv.style.display = 'block';
        this.textContent = 'Hide Settings';
    } else {
        settingsDiv.style.display = 'none';
        this.textContent = 'Show Settings';
    }
});

document.getElementById('randomplayback').addEventListener('click', function() {
    document.cookie = "RandomPlaybackChecked=" + this.checked + ";max-age=2592000"; //30 Tage
    listCookies();
});

document.getElementById('autoplay').addEventListener('click', function() {
    document.cookie = "autoplayChecked=" + this.checked + ";max-age=2592000"; //30 Tage
    listCookies();
});

document.getElementById('autoShowSonginfo').addEventListener('click', function() {
    document.cookie = "autoShowSonginfoChecked=" + this.checked + ";max-age=2592000"; //30 Tage
    listCookies();
});

document.getElementById('saveYearsToPlex').addEventListener('click', function() {
    document.cookie = "saveYearsToPlexChecked=" + this.checked + ";max-age=2592000"; //30 Tage
    listCookies();
});

document.getElementById('showProgressBar').addEventListener('click', function() {
    document.cookie = "showProgressBarChecked=" + this.checked + ";max-age=2592000"; //30 Tage
    updateProgressBarVisibility();
    listCookies();
});

document.getElementById('cookies').addEventListener('click', function() {
    var cb = document.getElementById('cookies');
    if (cb.checked == true) {
        document.getElementById('cookielist').style.display = 'block';
    }
    else {
        document.getElementById('cookielist').style.display = 'none';
    }
});

document.getElementById('toggleGameEditionsButton').addEventListener('click', function() {
    const panel = document.getElementById('gameEditions_div');
    const visible = panel.style.display && panel.style.display !== 'none';
    if (visible) {
        panel.style.display = 'none';
    } else {
        updateGameEditionsList();
        updatePlexPlaylistsList();
        panel.style.display = 'block';
    }
    updateEditionsButtonLabel();
});

function updateEditionsButtonLabel() {
    const panel = document.getElementById('gameEditions_div');
    const visible = panel.style.display && panel.style.display !== 'none';
    const content = gameMode === 'plex' ? 'Editions & Playlists' : 'Editions';
    document.getElementById('toggleGameEditionsButton').textContent = `${visible ? 'Hide' : 'Show'} ${content}`;
}

function updateGameEditionsList() {
    const listEl = document.getElementById('gameEditionsList');
    const gameEntries = Object.entries(plexGames);

    if (gameEntries.length === 0) {
        listEl.innerHTML = '<em>No game editions loaded</em>';
        return;
    }

    // Editions can be selected for random playback in Plex Mode; in Hitster Mode
    // the list only shows which editions are playable
    const selectable = gameMode === 'plex';
    listEl.replaceChildren();
    const list = document.createElement('ul');
    list.className = 'game-editions-list';
    for (const [lang, name] of gameEntries) {
        const item = document.createElement('li');
        const label = document.createElement('label');

        if (selectable) {
            const checkboxId = `gameEdition-${lang}`;
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = checkboxId;
            checkbox.dataset.lang = lang;
            checkbox.checked = selectedGames.has(lang);
            checkbox.addEventListener('change', handleGameEditionToggle);
            item.append(checkbox);
            label.htmlFor = checkboxId;
        }

        const count = plexSongCounts[lang];
        const range = plexDateRanges[lang];
        const meta = document.createElement('span');
        meta.className = 'edition-meta';
        meta.textContent = [count ? `${count} songs` : '', range ? `${range.min}-${range.max}` : '']
            .filter(Boolean).join(' · ');
        label.append(name, document.createElement('br'), meta);
        item.append(label);

        const rate = plexMatchRates[lang];
        if (rate !== undefined) {
            const rateBadge = document.createElement('span');
            rateBadge.className = rate >= 100 ? 'match-rate match-rate-complete' : 'match-rate';
            rateBadge.textContent = `${rate}%`;
            rateBadge.title = rate >= 100 ? 'Every card is playable' : `${rate}% of the cards are playable`;
            item.append(rateBadge);
        }
        list.append(item);
    }
    listEl.append(list);
}

function handleGameEditionToggle(event) {
    const lang = event.target.dataset.lang;
    if (event.target.checked) {
        selectedGames.add(lang);
    } else {
        selectedGames.delete(lang);
    }
    saveSelection('selectedGames', selectedGames);
}

function updatePlexPlaylistsList() {
    const listEl = document.getElementById('plexPlaylistsList');

    if (plexPlaylists.length === 0) {
        listEl.innerHTML = '<em>No playlists loaded</em>';
        return;
    }

    listEl.replaceChildren();
    const list = document.createElement('ul');
    list.className = 'game-editions-list';
    for (const playlist of plexPlaylists) {
        const checkboxId = `plexPlaylist-${playlist.ratingKey}`;
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = checkboxId;
        checkbox.dataset.key = playlist.ratingKey;
        checkbox.checked = selectedPlaylists.has(playlist.ratingKey);
        checkbox.addEventListener('change', handlePlaylistToggle);

        const label = document.createElement('label');
        label.htmlFor = checkboxId;
        const meta = document.createElement('span');
        meta.className = 'edition-meta';
        meta.textContent = `${playlist.leafCount} songs` + (playlist.smart ? ' · smart playlist' : '');
        label.append(playlist.title, document.createElement('br'), meta);

        const item = document.createElement('li');
        item.append(checkbox, label);
        list.append(item);
    }
    listEl.append(list);
}

function handlePlaylistToggle(event) {
    const key = event.target.dataset.key;
    if (event.target.checked) {
        selectedPlaylists.add(key);
    } else {
        selectedPlaylists.delete(key);
    }
    saveSelection('selectedPlaylists', selectedPlaylists);
}

function saveSelection(cookieName, selection) {
    const value = Array.from(selection).join(',');
    document.cookie = `${cookieName}=${encodeURIComponent(value)};max-age=2592000`;
    listCookies();
}

function loadSelection(cookieName, selection) {
    const raw = getCookieValue(cookieName);
    if (!raw) return;
    const decoded = decodeURIComponent(raw);
    if (!decoded) return;
    decoded.split(',').filter(Boolean).forEach(value => selection.add(value));
}

// Drop any selected games that no longer exist in the loaded manifest.
function pruneSelectedGames() {
    for (const lang of Array.from(selectedGames)) {
        if (!plexGames[lang]) {
            selectedGames.delete(lang);
        }
    }
}

// Drop any selected playlists that no longer exist on the server.
function pruneSelectedPlaylists() {
    const existing = new Set(plexPlaylists.map(p => p.ratingKey));
    for (const key of Array.from(selectedPlaylists)) {
        if (!existing.has(key)) {
            selectedPlaylists.delete(key);
        }
    }
}

function listCookies() {
    var result = document.cookie;
    document.getElementById("cookielist").innerHTML=result;
 }

function getCookieValue(name) {
    const regex = new RegExp(`(^| )${name}=([^;]+)`);
    const match = document.cookie.match(regex);
    if (match) {
        return match[2];
    }
}

function getCookies() {
    var isTrueSet;
    if (getCookieValue("RandomPlaybackChecked") !== undefined) {
        isTrueSet = (getCookieValue("RandomPlaybackChecked") === 'true');
        document.getElementById('randomplayback').checked = isTrueSet;
    }
    if (getCookieValue("autoplayChecked") !== undefined) {
        isTrueSet = (getCookieValue("autoplayChecked") === 'true');
        document.getElementById('autoplay').checked = isTrueSet;
    }
    if (getCookieValue("autoShowSonginfoChecked") !== undefined) {
        isTrueSet = (getCookieValue("autoShowSonginfoChecked") === 'true');
        document.getElementById('autoShowSonginfo').checked = isTrueSet;
    }
    if (getCookieValue("showProgressBarChecked") !== undefined) {
        isTrueSet = (getCookieValue("showProgressBarChecked") === 'true');
        document.getElementById('showProgressBar').checked = isTrueSet;
    }
    if (getCookieValue("saveYearsToPlexChecked") !== undefined) {
        isTrueSet = (getCookieValue("saveYearsToPlexChecked") === 'true');
        document.getElementById('saveYearsToPlex').checked = isTrueSet;
    }
    listCookies();
}

// Load Plex settings
async function loadPlexSettings() {
    await loadPlexConfig();
    await Promise.all([loadPlexMappings(), loadPlexPlaylists()]);
}

function updatePlexMappingStatus() {
    const statusEl = document.getElementById('plexMappingStatus');
    const loadedLangs = Object.keys(plexMappingCache).sort();

    if (loadedLangs.length > 0) {
        statusEl.textContent = `Loaded: ${loadedLangs.join(', ')}`;
        statusEl.className = 'success';
    } else {
        statusEl.textContent = 'No mappings loaded';
        statusEl.className = '';
    }
}

// Plex settings event listeners
document.getElementById('testPlexConnection').addEventListener('click', async function() {
    const statusEl = document.getElementById('plexConnectionStatus');

    if (!plexConfig.serverUrl || !plexConfig.token) {
        statusEl.textContent = 'Config not loaded';
        statusEl.className = 'error';
        return;
    }

    statusEl.textContent = 'Testing...';
    statusEl.className = 'loading';

    const success = await testPlexConnection();

    if (success) {
        statusEl.textContent = 'Connected!';
        statusEl.className = 'success';
    } else {
        statusEl.textContent = 'Connection failed';
        statusEl.className = 'error';
    }
});

window.addEventListener("DOMContentLoaded", function() {
    getCookies();
    loadSelection('selectedGames', selectedGames);
    loadSelection('selectedPlaylists', selectedPlaylists);
    // Without a saved mode, users who already picked editions keep random playback
    const savedMode = getCookieValue('gameMode');
    setGameMode(savedMode || (selectedGames.size > 0 ? 'plex' : 'hitster'));
    // Panel starts hidden; selections still apply in Plex Mode.
    document.getElementById('gameEditions_div').style.display = 'none';
    loadPlexSettings();
});
