import QrScanner from "https://unpkg.com/qr-scanner/qr-scanner.min.js";
import { playerManager } from "./player-manager.js";

let playbackTimer; // hold the timer reference
let playbackDuration = 30; // Default playback duration
let qrScanner;
let lastDecodedText = ""; // Store the last decoded text
let currentStartTime = 0;

// Plex integration
let plexMappingCache = {}; // In-memory cache for Plex mappings
let plexConfig = { serverUrl: '', token: '' }; // Loaded from plex-config.json
let plexGames = {}; // Game names from manifest (mapping -> name)
let plexMatchRates = {}; // Match rates from manifest (mapping -> rate)
let plexDateRanges = {}; // Date ranges from manifest (mapping -> {min, max})
let plexSongCounts = {}; // Song counts from manifest (mapping -> count)

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

function lookupPlexTrackByRatingKey(ratingKey) {
    // Search all loaded mappings for a track with this ratingKey
    for (const lang of Object.keys(plexMappingCache)) {
        const mapping = plexMappingCache[lang];
        // Check if ratingKey exists as a key in the mapping (custom games use ratingKey as key)
        if (mapping[ratingKey] && mapping[ratingKey].ratingKey === ratingKey) {
            return { track: mapping[ratingKey], game: lang };
        }
        // Also check all tracks for matching ratingKey (standard Hitster mappings)
        for (const key of Object.keys(mapping)) {
            if (mapping[key] && mapping[key].ratingKey === ratingKey) {
                return { track: mapping[key], game: lang };
            }
        }
        // Check alternativeKeys for tracks that were replaced in Plex
        // (old ratingKey on printed card, new ratingKey in mapping)
        for (const key of Object.keys(mapping)) {
            const track = mapping[key];
            if (track && track.alternativeKeys && track.alternativeKeys.includes(ratingKey)) {
                console.log(`Found via alternativeKeys: ${ratingKey} -> ${track.ratingKey}`);
                return { track: track, game: lang };
            }
        }
    }
    return null;
}

function isPlexConfigured() {
    const settings = getPlexSettings();
    return settings.serverUrl && settings.token;
}

function hasPlexMapping(lang) {
    const mapping = getPlexMapping(lang);
    return Object.keys(mapping).length > 0;
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
    playerManager.stop();
    document.getElementById('startstop-song').innerHTML = "Play";
    document.getElementById('startstop-song').style.background = "";
    document.getElementById('startstop-song').classList.remove('playing');

    let plexTrackInfo = null;
    let plexDebugInfo = "";
    let hitsterData = null;

    if (isPlexRatingKey(decodedText)) {
        // Direct rating key from custom game card (plex:12345)
        const ratingKey = parsePlexRatingKey(decodedText);
        console.log("Custom game card, rating key:", ratingKey);

        if (!plexConfig.serverUrl) {
            plexDebugInfo = "No server URL in config";
        } else if (!plexConfig.token) {
            plexDebugInfo = "No token in config";
        } else {
            // Look up track info from loaded mappings (includes partKey)
            const result = lookupPlexTrackByRatingKey(ratingKey);
            if (result) {
                plexTrackInfo = result.track;
                plexDebugInfo = `Found: ${plexTrackInfo.artist} - ${plexTrackInfo.title}`;
                console.log(`Found in mapping (${result.game}):`, plexTrackInfo.artist, "-", plexTrackInfo.title);
            } else {
                plexDebugInfo = `Rating key ${ratingKey} not found in any loaded mapping`;
                console.log('Rating key not found in any mapping. Is the custom game mapping loaded?');
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
                plexTrackInfo = lookupPlexTrack(hitsterData.id, hitsterData.lang);
                if (plexTrackInfo) {
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
    if (plexTrackInfo) {
        const plexSettings = getPlexSettings();
        playerManager.initPlexPlayer(plexSettings.serverUrl, plexSettings.token);

        document.getElementById('song-ratingkey').textContent = plexTrackInfo.ratingKey;
        document.getElementById('song-artist').textContent = plexTrackInfo.artist;
        document.getElementById('song-title').textContent = plexTrackInfo.title;
        document.getElementById('song-title').style.color = '';
        document.getElementById('song-year').textContent = plexTrackInfo.year || '';

        currentStartTime = 0;
        await playerManager.cue({ trackInfo: plexTrackInfo });
    } else if (hitsterData) {
        // Card was recognized but not matched in Plex
        const normalizedCardId = String(parseInt(hitsterData.id, 10));
        document.getElementById('song-ratingkey').textContent = '';
        document.getElementById('song-artist').textContent = '';
        document.getElementById('song-title').textContent = `Card #${normalizedCardId} not available`;
        document.getElementById('song-title').style.color = '#cc0000';
        document.getElementById('song-year').textContent = '';
        document.getElementById('song-duration').textContent = '';
        document.getElementById('startstop-song').disabled = true;
        document.getElementById('startstop-song').style.background = '';
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
        document.getElementById('startstop-song').disabled = false;
        document.getElementById('startstop-song').style.background = "green";

        // Wait for duration to be available
        setTimeout(() => {
            const duration = playerManager.getDuration();
            if (duration) {
                document.getElementById('song-duration').textContent = formatDuration(duration);
            }
        }, 500);

        // Handle autoplay
        if (isIOS()) {
            playerManager.play();
        } else if (document.getElementById('autoplay').checked) {
            document.getElementById('startstop-song').innerHTML = "Stop";
            document.getElementById('startstop-song').classList.add('playing');
            if (document.getElementById('randomplayback').checked) {
                playSongAtRandomStartTime();
            } else {
                playerManager.play();
            }
        }
    } else if (state === PlayerState.PLAYING) {
        document.getElementById('startstop-song').style.background = "red";
        document.getElementById('startstop-song').innerHTML = "Stop";
        document.getElementById('startstop-song').classList.add('playing');
    } else if (state === PlayerState.PAUSED || state === PlayerState.ENDED) {
        document.getElementById('startstop-song').innerHTML = "Play";
        document.getElementById('startstop-song').style.background = "green";
        document.getElementById('startstop-song').classList.remove('playing');
    } else if (state === PlayerState.BUFFERING) {
        document.getElementById('startstop-song').style.background = "orange";
    }
}

// Helper function to format duration from seconds to a more readable format
function formatDuration(duration) {
    var minutes = Math.floor(duration / 60);
    var seconds = Math.floor(duration % 60);
    return minutes + ":" + (seconds < 10 ? '0' : '') + seconds;
}

// Add event listeners to Play and Stop buttons
document.getElementById('startstop-song').addEventListener('click', function() {
    if (this.innerHTML == "Play") {
        this.innerHTML = "Stop";
        this.classList.add('playing');
        if (document.getElementById('randomplayback').checked == true) {
            playSongAtRandomStartTime();
        } else {
            playerManager.play();
        }
    } else {
        this.innerHTML = "Play";
        this.classList.remove('playing');
        playerManager.pause();
    }
});

function playSongAtRandomStartTime() {
    playbackDuration = parseInt(document.getElementById('playback-duration').value, 10) || 30;

    playerManager.playAtRandomStartTime(playbackDuration, currentStartTime, () => {
        document.getElementById('startstop-song').innerHTML = "Play";
        document.getElementById('startstop-song').classList.remove('playing');
    });
}

// Assuming you have an element with the ID 'qr-reader' for the QR scanner
document.getElementById('qr-reader').style.display = 'none'; // Initially hide the QR Scanner

// Initially disable the play button until a song is scanned
document.getElementById('startstop-song').disabled = true;

document.getElementById('startScanButton').addEventListener('click', function() {
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

document.getElementById('debugButton').addEventListener('click', function() {
    handleScannedLink("https://www.hitstergame.com/de-aaaa0012/237");
});

document.getElementById('songinfo').addEventListener('click', function() {
    var cb = document.getElementById('songinfo');
    var ratingKeyRow = document.getElementById('ratingkeyrow');
    var artistRow = document.getElementById('artistrow');
    var titleRow = document.getElementById('titlerow');
    var yearRow = document.getElementById('yearrow');
    var durationRow = document.getElementById('durationrow');
    if(cb.checked == true){
        ratingKeyRow.style.display = 'block';
        artistRow.style.display = 'block';
        titleRow.style.display = 'block';
        yearRow.style.display = 'block';
        durationRow.style.display = 'block';
    } else {
        ratingKeyRow.style.display = 'none';
        artistRow.style.display = 'none';
        titleRow.style.display = 'none';
        yearRow.style.display = 'none';
        durationRow.style.display = 'none';
    }
});

document.getElementById('cancelScanButton').addEventListener('click', function() {
    qrScanner.stop(); // Stop scanning after a result is found
    document.getElementById('qr-reader').style.display = 'none'; // Hide the scanner after successful scan
    document.getElementById('cancelScanButton').style.display = 'none'; // Hide the cancel-button
});

document.getElementById('cb_settings').addEventListener('click', function() {
    var cb = document.getElementById('cb_settings');
    if (cb.checked == true) {
        document.getElementById('settings_div').style.display = 'block';
    }
    else {
        document.getElementById('settings_div').style.display = 'none';
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

document.getElementById('cookies').addEventListener('click', function() {
    var cb = document.getElementById('cookies');
    if (cb.checked == true) {
        document.getElementById('cookielist').style.display = 'block';
    }
    else {
        document.getElementById('cookielist').style.display = 'none';
    }
});

document.getElementById('showGameEditions').addEventListener('click', function() {
    var cb = document.getElementById('showGameEditions');
    var listEl = document.getElementById('gameEditionsList');
    if (cb.checked == true) {
        updateGameEditionsList();
        listEl.style.display = 'block';
    } else {
        listEl.style.display = 'none';
    }
});

function updateGameEditionsList() {
    const listEl = document.getElementById('gameEditionsList');
    const gameEntries = Object.entries(plexGames);

    if (gameEntries.length === 0) {
        listEl.innerHTML = '<em>No game editions loaded</em>';
        return;
    }

    // Build a simple list of game names with song counts, date ranges, and match rates
    const listHtml = '<ul style="margin: 0.5rem 0; padding-left: 1.5rem; text-align: left;">' +
        gameEntries.map(([lang, name]) => {
            const count = plexSongCounts[lang];
            const countStr = count ? ` ${count} songs` : '';
            const range = plexDateRanges[lang];
            const rangeStr = range ? ` (${range.min}-${range.max})` : '';
            const rate = plexMatchRates[lang];
            const rateStr = rate !== undefined ? ` ${rate}%` : '';
            return `<li>${name}${countStr}${rangeStr}${rateStr}</li>`;
        }).join('') +
        '</ul>';
    listEl.innerHTML = listHtml;
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
    if (getCookieValue("RandomPlaybackChecked") != "") {
        isTrueSet = (getCookieValue("RandomPlaybackChecked") === 'true');
        document.getElementById('randomplayback').checked = isTrueSet;
    }
    if (getCookieValue("autoplayChecked") != "") {
        isTrueSet = (getCookieValue("autoplayChecked") === 'true');
        document.getElementById('autoplay').checked = isTrueSet;
    }
    listCookies();
}

// Load Plex settings
async function loadPlexSettings() {
    await loadPlexConfig();
    await loadPlexMappings();
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
    loadPlexSettings();
});
