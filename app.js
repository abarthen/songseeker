import QrScanner from "https://unpkg.com/qr-scanner/qr-scanner.min.js";
import { playerManager } from "./player-manager.js";

let player; // Define player globally (YouTube player)
let playbackTimer; // hold the timer reference
let playbackDuration = 30; // Default playback duration
let qrScanner;
let csvCache = {};
let lastDecodedText = ""; // Store the last decoded text
let currentStartTime = 0;

// Plex integration
let plexMappingCache = {}; // In-memory cache for Plex mappings

// Function to detect iOS devices
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}

// Plex helper functions
function getPlexSettings() {
    return {
        usePlex: localStorage.getItem('usePlex') === 'true',
        serverUrl: localStorage.getItem('plexServerUrl') || '',
        token: localStorage.getItem('plexToken') || ''
    };
}

function savePlexSettings(settings) {
    localStorage.setItem('usePlex', settings.usePlex);
    localStorage.setItem('plexServerUrl', settings.serverUrl);
    localStorage.setItem('plexToken', settings.token);
}

function getPlexMapping(lang) {
    const key = `plexMapping-${lang}`;
    if (!plexMappingCache[lang]) {
        const stored = localStorage.getItem(key);
        if (stored) {
            try {
                plexMappingCache[lang] = JSON.parse(stored);
            } catch (e) {
                console.error('Failed to parse Plex mapping:', e);
                plexMappingCache[lang] = {};
            }
        } else {
            plexMappingCache[lang] = {};
        }
    }
    return plexMappingCache[lang];
}

function savePlexMapping(lang, mapping) {
    const key = `plexMapping-${lang}`;
    plexMappingCache[lang] = mapping;
    localStorage.setItem(key, JSON.stringify(mapping));
}

function lookupPlexTrack(cardId, lang) {
    const mapping = getPlexMapping(lang);
    return mapping[cardId] || null;
}

function isPlexConfigured() {
    const settings = getPlexSettings();
    return settings.usePlex && settings.serverUrl && settings.token;
}

function hasPlexMapping(lang) {
    const mapping = getPlexMapping(lang);
    return Object.keys(mapping).length > 0;
}

async function testPlexConnection(serverUrl, token) {
    try {
        const url = `${serverUrl.replace(/\/$/, '')}/?X-Plex-Token=${token}`;
        const response = await fetch(url, {
            headers: { 'Accept': 'application/json' }
        });
        return response.ok;
    } catch (e) {
        console.error('Plex connection test failed:', e);
        return false;
    }
}

function updatePlaybackSourceDisplay(source) {
    const sourceSpan = document.getElementById('playback-source');
    const sourceDiv = document.getElementById('playbacksource');
    if (sourceSpan && sourceDiv) {
        sourceSpan.textContent = source === 'plex' ? 'Plex' : 'YouTube';
        sourceSpan.className = source;
        // Show source indicator when song info is shown
        if (document.getElementById('songinfo').checked) {
            sourceDiv.style.display = 'block';
        }
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
        
    }
);

// Function to determine the type of link and act accordingly
async function handleScannedLink(decodedText) {
    let youtubeURL = "";
    let plexTrackInfo = null;
    let usePlex = false;

    if (isYoutubeLink(decodedText)) {
        youtubeURL = decodedText;
    } else if (isHitsterLink(decodedText)) {
        const hitsterData = parseHitsterUrl(decodedText);
        if (hitsterData) {
            console.log("Hitster data:", hitsterData.id, hitsterData.lang);

            // Check Plex first if configured
            if (isPlexConfigured() && hasPlexMapping(hitsterData.lang)) {
                plexTrackInfo = lookupPlexTrack(hitsterData.id, hitsterData.lang);
                if (plexTrackInfo) {
                    console.log(`Found in Plex: ${plexTrackInfo.artist} - ${plexTrackInfo.title}`);
                    usePlex = true;
                } else {
                    console.log('Card not found in Plex mapping, falling back to YouTube');
                }
            }

            // Fallback to YouTube if Plex not available
            if (!usePlex) {
                try {
                    const csvContent = await getCachedCsv(`/playlists/hitster-${hitsterData.lang}.csv`);
                    const youtubeLink = lookupYoutubeLink(hitsterData.id, csvContent);
                    if (youtubeLink) {
                        console.log(`YouTube Link from CSV: ${youtubeLink}`);
                        youtubeURL = youtubeLink;
                    }
                } catch (error) {
                    console.error("Failed to fetch CSV:", error);
                }
            }
        } else {
            console.log("Invalid Hitster URL:", decodedText);
        }
    } else if (isRockster(decodedText)) {
        try {
            const urlObj = new URL(decodedText);
            const ytCode = urlObj.searchParams.get("yt");

            if (ytCode) {
                youtubeURL = `https://www.youtube.com/watch?v=${ytCode}`;
            } else {
                console.error("Rockster link is missing the 'yt' parameter:", decodedText);
            }
        } catch (error) {
            console.error("Invalid Rockster URL:", decodedText);
        }
    }

    // Hide scanner UI
    qrScanner.stop();
    document.getElementById('qr-reader').style.display = 'none';
    document.getElementById('cancelScanButton').style.display = 'none';
    lastDecodedText = "";

    // Handle Plex playback
    if (usePlex && plexTrackInfo) {
        const plexSettings = getPlexSettings();
        playerManager.initPlexPlayer(plexSettings.serverUrl, plexSettings.token);
        playerManager.setActivePlayerType('plex');

        document.getElementById('video-id').textContent = plexTrackInfo.ratingKey;
        document.getElementById('video-title').textContent = `${plexTrackInfo.artist} - ${plexTrackInfo.title}`;
        updatePlaybackSourceDisplay('plex');

        currentStartTime = 0;
        await playerManager.cue({ trackInfo: plexTrackInfo });
        return;
    }

    // Handle YouTube playback
    if (youtubeURL) {
        const youtubeLinkData = parseYoutubeLink(youtubeURL);
        if (youtubeLinkData) {
            playerManager.setActivePlayerType('youtube');
            document.getElementById('video-id').textContent = youtubeLinkData.videoId;
            updatePlaybackSourceDisplay('youtube');

            console.log(youtubeLinkData.videoId);
            currentStartTime = youtubeLinkData.startTime || 0;
            player.cueVideoById(youtubeLinkData.videoId, currentStartTime);
        }
    }
}

    function isHitsterLink(url) {
        // Regular expression to match with or without "http://" or "https://"
        const regex = /^(?:http:\/\/|https:\/\/)?(www\.hitstergame|app\.hitsternordics)\.com\/.+/;
        return regex.test(url);
    }

    // Example implementation for isYoutubeLink
    function isYoutubeLink(url) {
        return url.startsWith("https://www.youtube.com") || url.startsWith("https://youtu.be") || url.startsWith("https://music.youtube.com/");
    }
    function isRockster(url){
        return url.startsWith("https://rockster.brettspiel.digital")
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

    // Looks up the YouTube link in the CSV content based on the ID
    function lookupYoutubeLink(id, csvContent) {
        const headers = csvContent[0]; // Get the headers from the CSV content
        const cardIndex = headers.indexOf('Card#');
        const urlIndex = headers.indexOf('URL');

        const targetId = parseInt(id, 10); // Convert the incoming ID to an integer
        const lines = csvContent.slice(1); // Exclude the first row (headers) from the lines

        if (cardIndex === -1 || urlIndex === -1) {
            throw new Error('Card# or URL column not found');
        }

        for (let row of lines) {
            const csvId = parseInt(row[cardIndex], 10);
            if (csvId === targetId) {
                return row[urlIndex].trim(); // Return the YouTube link
            }
        }
        return null; // If no matching ID is found

    }

    // Could also use external library, but for simplicity, we'll define it here
    function parseCSV(text) {
        const lines = text.split('\n');
        return lines.map(line => {
            const result = [];
            let startValueIdx = 0;
            let inQuotes = false;
            for (let i = 0; i < line.length; i++) {
                if (line[i] === '"' && line[i-1] !== '\\') {
                    inQuotes = !inQuotes;
                } else if (line[i] === ',' && !inQuotes) {
                    result.push(line.substring(startValueIdx, i).trim().replace(/^"(.*)"$/, '$1'));
                    startValueIdx = i + 1;
                }
            }
            result.push(line.substring(startValueIdx).trim().replace(/^"(.*)"$/, '$1')); // Push the last value
            return result;
        });
    }

    async function getCachedCsv(url) {
        if (!csvCache[url]) { // Check if the URL is not in the cache
            console.log(`URL not cached, fetching CSV from URL: ${url}`);
            const response = await fetch(url);
            const data = await response.text();
            csvCache[url] = parseCSV(data); // Cache the parsed CSV data using the URL as a key
        }
        return csvCache[url]; // Return the cached data for the URL
    }

    function parseYoutubeLink(url) {
        // First, ensure that the URL is decoded (handles encoded URLs)
        url = decodeURIComponent(url);
    
        const regex = /^https?:\/\/(www\.youtube\.com\/watch\?v=|youtu\.be\/|music\.youtube\.com\/watch\?v=)(.{11})(.*)/;
        const match = url.match(regex);
        if (match) {
            const queryParams = new URLSearchParams(match[3]); // Correctly capture and parse the query string part of the URL
            const videoId = match[2];
            let startTime = queryParams.get('start') || queryParams.get('t');
            const endTime = queryParams.get('end');
    
            document.getElementById('video-start').textContent = startTime;
            // Normalize and parse 't' and 'start' parameters
            startTime = normalizeTimeParameter(startTime);
            const parsedEndTime = normalizeTimeParameter(endTime);
    
            return { videoId, startTime, endTime: parsedEndTime };
        }
        return null;
    }
    
    function normalizeTimeParameter(timeValue) {
        if (!timeValue) return null; // Return null if timeValue is falsy
    
        // Handle time formats (e.g., 't=1m15s' or '75s')
        let seconds = 0;
        if (timeValue.endsWith('s')) {
            seconds = parseInt(timeValue, 10);
        } else {
            // Additional parsing can be added here for 'm', 'h' formats if needed
            seconds = parseInt(timeValue, 10);
        }
    
        return isNaN(seconds) ? null : seconds;
    }

// This function creates an <iframe> (and YouTube player) after the API code downloads.
function onYouTubeIframeAPIReady() {
    player = new YT.Player('player', {
        height: '0',
        width: '0',
        events: {
            'onReady': onPlayerReady,
            'onStateChange': onPlayerStateChange
        }
    });
    // Register YouTube player with the player manager
    playerManager.setYouTubePlayer(player);
}
window.onYouTubeIframeAPIReady = onYouTubeIframeAPIReady;

// Load the YouTube IFrame API script
const tag = document.createElement('script');
tag.src = "https://www.youtube.com/iframe_api";
const firstScriptTag = document.getElementsByTagName('script')[0];
firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

// The API will call this function when the video player is ready.
function onPlayerReady(event) {
    // Cue a video using the videoId from the QR code (example videoId used here)
    // player.cueVideoById('dQw4w9WgXcQ');
    event.target.setVolume(100);
    event.target.unMute();

    // Set up player manager state change callback for Plex
    playerManager.onStateChange(handlePlayerStateChange);
}

// Unified state change handler (works for both YouTube and Plex via player manager)
function handlePlayerStateChange(event) {
    const state = event.data;
    const PlayerState = playerManager.PlayerState;

    if (state === PlayerState.CUED) {
        document.getElementById('startstop-video').style.background = "green";

        // Get track info from Plex player
        if (playerManager.isPlexActive()) {
            const videoData = playerManager.getVideoData();
            document.getElementById('video-title').textContent = videoData.title;

            // Wait for duration to be available
            setTimeout(() => {
                const duration = playerManager.getDuration();
                if (duration) {
                    document.getElementById('video-duration').textContent = formatDuration(duration);
                }
            }, 500);
        }

        // Handle autoplay for Plex
        if (playerManager.isPlexActive()) {
            if (isIOS()) {
                playerManager.play();
            } else if (document.getElementById('autoplay').checked) {
                document.getElementById('startstop-video').innerHTML = "Stop";
                if (document.getElementById('randomplayback').checked) {
                    playVideoAtRandomStartTime();
                } else {
                    playerManager.play();
                }
            }
        }
    } else if (state === PlayerState.PLAYING) {
        document.getElementById('startstop-video').style.background = "red";
        document.getElementById('startstop-video').innerHTML = "Stop";
    } else if (state === PlayerState.PAUSED || state === PlayerState.ENDED) {
        document.getElementById('startstop-video').innerHTML = "Play";
        document.getElementById('startstop-video').style.background = "green";
    } else if (state === PlayerState.BUFFERING) {
        document.getElementById('startstop-video').style.background = "orange";
    }
}

// Display video information when it's cued
function onPlayerStateChange(event) {
    if (event.data == YT.PlayerState.CUED) {
        document.getElementById('startstop-video').style.background = "green";
        // Display title and duration
        var videoData = player.getVideoData();
        document.getElementById('video-title').textContent = videoData.title;
        var duration = player.getDuration();
        document.getElementById('video-duration').textContent = formatDuration(duration);
        // We do need this on iOS devices otherwise one would need to press play twice
        if (isIOS()) {
            player.playVideo();
        }
        // Check for Autoplay, there is not autoplay on iOS
        else if (document.getElementById('autoplay').checked == true) {
            document.getElementById('startstop-video').innerHTML = "Stop";
            if (document.getElementById('randomplayback').checked == true) {
                playVideoAtRandomStartTime();
            }
            else {
                player.playVideo();
            }
        }
    }
    else if (event.data == YT.PlayerState.PLAYING) {
        document.getElementById('startstop-video').style.background = "red";
    }
    else if (event.data == YT.PlayerState.PAUSED || event.data == YT.PlayerState.ENDED) {
        document.getElementById('startstop-video').innerHTML = "Play";
        document.getElementById('startstop-video').style.background = "green";
    }
    else if (event.data == YT.PlayerState.BUFFERING) {
        document.getElementById('startstop-video').style.background = "orange";
    }
}

// Helper function to format duration from seconds to a more readable format
function formatDuration(duration) {
    var minutes = Math.floor(duration / 60);
    var seconds = duration % 60;
    return minutes + ":" + (seconds < 10 ? '0' : '') + seconds;
}

// Add event listeners to Play and Stop buttons
document.getElementById('startstop-video').addEventListener('click', function() {
    if (this.innerHTML == "Play") {
        this.innerHTML = "Stop";
        if (document.getElementById('randomplayback').checked == true) {
            playVideoAtRandomStartTime();
        } else {
            // Use player manager for unified playback
            if (playerManager.isPlexActive()) {
                playerManager.play();
            } else {
                player.playVideo();
            }
        }
    } else {
        this.innerHTML = "Play";
        // Use player manager for unified pause
        if (playerManager.isPlexActive()) {
            playerManager.pause();
        } else {
            player.pauseVideo();
        }
    }
});

function playVideoAtRandomStartTime() {
    const minStartPercentage = 0.10;
    const maxEndPercentage = 0.90;
    playbackDuration = parseInt(document.getElementById('playback-duration').value, 10) || 30;

    // Use player manager for Plex, otherwise use YouTube player
    if (playerManager.isPlexActive()) {
        playerManager.playAtRandomStartTime(playbackDuration, currentStartTime, () => {
            document.getElementById('startstop-video').innerHTML = "Play";
        });
        return;
    }

    // YouTube playback
    let videoDuration = player.getDuration();
    let startTime = currentStartTime;
    let endTime = playbackDuration;

    // Adjust start and end time based on video duration
    const minStartTime = Math.max(currentStartTime, videoDuration * minStartPercentage);
    const maxEndTime = videoDuration * maxEndPercentage;

    // Ensure the video ends by 90% of its total duration
    if (endTime > maxEndTime) {
        endTime = maxEndTime;
        startTime = Math.max(minStartTime, endTime - playbackDuration);
    }

    // If custom start time is 0 or very close to the beginning, pick a random start time within the range
    if (startTime <= minStartTime) {
        const range = maxEndTime - minStartTime - playbackDuration;
        const randomOffset = Math.random() * range;
        startTime = minStartTime + randomOffset;
        endTime = startTime + playbackDuration;
    }

    // Cue video at calculated start time and play
    console.log("play random", startTime, endTime);
    player.seekTo(startTime, true);
    player.playVideo();

    clearTimeout(playbackTimer); // Clear any existing timer
    // Schedule video stop after the specified duration
    playbackTimer = setTimeout(() => {
        player.pauseVideo();
        document.getElementById('startstop-video').innerHTML = "Play";
    }, (endTime - startTime) * 1000); // Convert to milliseconds
}

// Assuming you have an element with the ID 'qr-reader' for the QR scanner
document.getElementById('qr-reader').style.display = 'none'; // Initially hide the QR Scanner

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
    // handleScannedLink("https://rockster.brettspiel.digital/?yt=1bP-fFxAMOI");
});

document.getElementById('songinfo').addEventListener('click', function() {
    var cb = document.getElementById('songinfo');
    var videoid = document.getElementById('videoid');
    var videotitle = document.getElementById('videotitle');
    var videoduration = document.getElementById('videoduration');
    var videostart = document.getElementById('videostart');
    var playbacksource = document.getElementById('playbacksource');
    if(cb.checked == true){
        videoid.style.display = 'block';
        videotitle.style.display = 'block';
        videoduration.style.display = 'block';
        videostart.style.display = 'block';
        playbacksource.style.display = 'block';
    } else {
        videoid.style.display = 'none';
        videotitle.style.display = 'none';
        videoduration.style.display = 'none';
        videostart.style.display = 'none';
        playbacksource.style.display = 'none';
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

// Load Plex settings from localStorage
function loadPlexSettings() {
    const settings = getPlexSettings();
    document.getElementById('usePlex').checked = settings.usePlex;
    document.getElementById('plexServerUrl').value = settings.serverUrl;
    document.getElementById('plexToken').value = settings.token;

    // Update mapping status display
    updatePlexMappingStatus();
}

function updatePlexMappingStatus() {
    const statusEl = document.getElementById('plexMappingStatus');
    const langs = ['de', 'en', 'fr', 'nl', 'ca', 'pl', 'hu', 'nordics'];
    const loadedLangs = langs.filter(lang => hasPlexMapping(lang));

    if (loadedLangs.length > 0) {
        statusEl.textContent = `Loaded: ${loadedLangs.join(', ')}`;
        statusEl.className = 'success';
    } else {
        statusEl.textContent = 'No mappings loaded';
        statusEl.className = '';
    }
}

// Plex settings event listeners
document.getElementById('usePlex').addEventListener('change', function() {
    const settings = getPlexSettings();
    settings.usePlex = this.checked;
    savePlexSettings(settings);
});

document.getElementById('plexServerUrl').addEventListener('change', function() {
    const settings = getPlexSettings();
    settings.serverUrl = this.value.trim();
    savePlexSettings(settings);
});

document.getElementById('plexToken').addEventListener('change', function() {
    const settings = getPlexSettings();
    settings.token = this.value.trim();
    savePlexSettings(settings);
});

document.getElementById('plexMappingFile').addEventListener('change', async function(event) {
    const file = event.target.files[0];
    if (!file) return;

    const statusEl = document.getElementById('plexMappingStatus');
    statusEl.textContent = 'Loading...';
    statusEl.className = 'loading';

    try {
        const text = await file.text();
        const mapping = JSON.parse(text);

        // Extract language from filename (e.g., "plex-mapping-de.json" -> "de")
        const langMatch = file.name.match(/plex-mapping-(\w+)\.json/);
        const lang = langMatch ? langMatch[1] : 'de';

        savePlexMapping(lang, mapping);

        const trackCount = Object.values(mapping).filter(v => v !== null).length;
        const totalCount = Object.keys(mapping).length;
        statusEl.textContent = `Loaded ${lang}: ${trackCount}/${totalCount} tracks`;
        statusEl.className = 'success';

        updatePlexMappingStatus();
    } catch (e) {
        console.error('Failed to load Plex mapping:', e);
        statusEl.textContent = 'Error loading file';
        statusEl.className = 'error';
    }

    // Clear the file input so the same file can be loaded again
    this.value = '';
});

document.getElementById('testPlexConnection').addEventListener('click', async function() {
    const statusEl = document.getElementById('plexConnectionStatus');
    const serverUrl = document.getElementById('plexServerUrl').value.trim();
    const token = document.getElementById('plexToken').value.trim();

    if (!serverUrl || !token) {
        statusEl.textContent = 'Enter server URL and token';
        statusEl.className = 'error';
        return;
    }

    statusEl.textContent = 'Testing...';
    statusEl.className = 'loading';

    const success = await testPlexConnection(serverUrl, token);

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