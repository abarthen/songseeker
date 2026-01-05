/**
 * Plex Player Module for SongSeeker
 *
 * Handles audio playback from Plex Media Server using HTML5 audio element.
 */

export class PlexPlayer {
    constructor() {
        this.serverUrl = null;
        this.token = null;
        this.audioElement = null;
        this.currentTrack = null;
        this.stateChangeCallback = null;
        this.playbackTimer = null;

        // Player states (matching YouTube player states for consistency)
        this.PlayerState = {
            UNSTARTED: -1,
            ENDED: 0,
            PLAYING: 1,
            PAUSED: 2,
            BUFFERING: 3,
            CUED: 5
        };

        this._initAudioElement();
    }

    _initAudioElement() {
        this.audioElement = document.createElement('audio');
        this.audioElement.id = 'plex-audio-player';
        this.audioElement.style.display = 'none';
        document.body.appendChild(this.audioElement);

        // Set up event listeners
        this.audioElement.addEventListener('play', () => {
            this._notifyStateChange(this.PlayerState.PLAYING);
        });

        this.audioElement.addEventListener('pause', () => {
            this._notifyStateChange(this.PlayerState.PAUSED);
        });

        this.audioElement.addEventListener('ended', () => {
            this._notifyStateChange(this.PlayerState.ENDED);
        });

        this.audioElement.addEventListener('waiting', () => {
            this._notifyStateChange(this.PlayerState.BUFFERING);
        });

        this.audioElement.addEventListener('canplay', () => {
            if (this.audioElement.paused) {
                this._notifyStateChange(this.PlayerState.CUED);
            }
        });

        this.audioElement.addEventListener('loadedmetadata', () => {
            this._notifyStateChange(this.PlayerState.CUED);
        });

        this.audioElement.addEventListener('error', (e) => {
            console.error('Plex audio error:', e);
            this._notifyStateChange(this.PlayerState.ENDED);
        });
    }

    _notifyStateChange(state) {
        if (this.stateChangeCallback) {
            this.stateChangeCallback({ data: state, target: this });
        }
    }

    /**
     * Configure the Plex server connection
     * @param {string} serverUrl - Plex server URL (e.g., http://192.168.1.100:32400)
     * @param {string} token - Plex authentication token
     */
    configure(serverUrl, token) {
        // Remove trailing slash if present
        this.serverUrl = serverUrl.replace(/\/$/, '');
        this.token = token;
    }

    /**
     * Check if the player is configured with server and token
     * @returns {boolean}
     */
    isConfigured() {
        return !!(this.serverUrl && this.token);
    }

    /**
     * Build the streaming URL for a Plex track
     * @param {string} partKey - The part key from Plex metadata
     * @returns {string} The full streaming URL
     */
    _buildStreamUrl(partKey) {
        // partKey is typically like "/library/parts/12345/1234567890/file.mp3"
        return `${this.serverUrl}${partKey}?X-Plex-Token=${this.token}`;
    }

    /**
     * Cue a track for playback (load without playing)
     * @param {object} trackInfo - Track info from mapping { ratingKey, title, artist, partKey }
     */
    async cueTrack(trackInfo) {
        if (!this.isConfigured()) {
            console.error('Plex player not configured');
            return;
        }

        this.currentTrack = trackInfo;

        // If we have a partKey, use it directly
        if (trackInfo.partKey) {
            this.audioElement.src = this._buildStreamUrl(trackInfo.partKey);
            this.audioElement.load();
            return;
        }

        // Otherwise, fetch track details to get the partKey
        try {
            const trackDetails = await this._fetchTrackDetails(trackInfo.ratingKey);
            if (trackDetails && trackDetails.partKey) {
                this.currentTrack.partKey = trackDetails.partKey;
                this.audioElement.src = this._buildStreamUrl(trackDetails.partKey);
                this.audioElement.load();
            } else {
                console.error('Could not get track streaming URL');
            }
        } catch (e) {
            console.error('Failed to fetch track details:', e);
        }
    }

    /**
     * Fetch track details from Plex to get the streaming part key
     * @param {string} ratingKey - The track's rating key
     * @returns {object} Track details with partKey
     */
    async _fetchTrackDetails(ratingKey) {
        const url = `${this.serverUrl}/library/metadata/${ratingKey}?X-Plex-Token=${this.token}`;

        try {
            const response = await fetch(url, {
                headers: { 'Accept': 'application/json' }
            });
            const data = await response.json();

            if (data.MediaContainer && data.MediaContainer.Metadata) {
                const track = data.MediaContainer.Metadata[0];
                if (track.Media && track.Media[0] && track.Media[0].Part && track.Media[0].Part[0]) {
                    return {
                        partKey: track.Media[0].Part[0].key,
                        duration: track.duration
                    };
                }
            }
        } catch (e) {
            console.error('Error fetching track details:', e);
        }

        return null;
    }

    /**
     * Play the cued track
     */
    playSong() {
        if (this.audioElement.src) {
            this.audioElement.play().catch(e => {
                console.error('Playback failed:', e);
            });
        }
    }

    /**
     * Pause playback
     */
    pauseSong() {
        this.audioElement.pause();
        this.clearPlaybackTimer();
    }

    /**
     * Stop playback and reset
     */
    stopSong() {
        this.audioElement.pause();
        this.audioElement.currentTime = 0;
        this.clearPlaybackTimer();
    }

    /**
     * Seek to a specific time
     * @param {number} seconds - Time in seconds
     * @param {boolean} allowSeekAhead - Allow seeking beyond buffered content
     */
    seekTo(seconds, allowSeekAhead = true) {
        this.audioElement.currentTime = seconds;
    }

    /**
     * Get the current playback time
     * @returns {number} Current time in seconds
     */
    getCurrentTime() {
        return this.audioElement.currentTime;
    }

    /**
     * Get the total duration
     * @returns {number} Duration in seconds
     */
    getDuration() {
        return this.audioElement.duration || 0;
    }

    /**
     * Set the volume
     * @param {number} volume - Volume level (0-100)
     */
    setVolume(volume) {
        this.audioElement.volume = volume / 100;
    }

    /**
     * Unmute the audio
     */
    unMute() {
        this.audioElement.muted = false;
    }

    /**
     * Mute the audio
     */
    mute() {
        this.audioElement.muted = true;
    }

    /**
     * Get track metadata
     * @returns {object} Current track info
     */
    getSongData() {
        return {
            title: this.currentTrack ? `${this.currentTrack.artist} - ${this.currentTrack.title}` : '',
            ratingKey: this.currentTrack ? this.currentTrack.ratingKey : ''
        };
    }

    /**
     * Set state change callback
     * @param {function} callback - Function to call on state changes
     */
    onStateChange(callback) {
        this.stateChangeCallback = callback;
    }

    /**
     * Set a timer to stop playback after duration
     * @param {number} duration - Duration in seconds
     */
    setPlaybackTimer(duration) {
        this.clearPlaybackTimer();
        this.playbackTimer = setTimeout(() => {
            this.pauseSong();
        }, duration * 1000);
    }

    /**
     * Clear any existing playback timer
     */
    clearPlaybackTimer() {
        if (this.playbackTimer) {
            clearTimeout(this.playbackTimer);
            this.playbackTimer = null;
        }
    }

    /**
     * Get the current player state
     * @returns {number} Current state constant
     */
    getPlayerState() {
        if (!this.audioElement.src) return this.PlayerState.UNSTARTED;
        if (this.audioElement.ended) return this.PlayerState.ENDED;
        if (this.audioElement.paused) {
            return this.audioElement.readyState >= 2 ? this.PlayerState.CUED : this.PlayerState.UNSTARTED;
        }
        if (this.audioElement.readyState < 3) return this.PlayerState.BUFFERING;
        return this.PlayerState.PLAYING;
    }
}
