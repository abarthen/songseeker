/**
 * Player Manager for SongSeeker
 *
 * Provides a unified interface for YouTube and Plex players.
 * Handles switching between players and routing playback commands.
 */

import { PlexPlayer } from './plex-player.js';

export class PlayerManager {
    constructor() {
        this.youtubePlayer = null;
        this.plexPlayer = null;
        this.activePlayerType = 'youtube'; // 'youtube' or 'plex'
        this.stateChangeCallback = null;
        this.playbackTimer = null;

        // Shared player states
        this.PlayerState = {
            UNSTARTED: -1,
            ENDED: 0,
            PLAYING: 1,
            PAUSED: 2,
            BUFFERING: 3,
            CUED: 5
        };
    }

    /**
     * Initialize the Plex player
     * @param {string} serverUrl - Plex server URL
     * @param {string} token - Plex authentication token
     */
    initPlexPlayer(serverUrl, token) {
        if (!this.plexPlayer) {
            this.plexPlayer = new PlexPlayer();
        }
        this.plexPlayer.configure(serverUrl, token);

        // Set up state change forwarding
        this.plexPlayer.onStateChange((event) => {
            if (this.activePlayerType === 'plex' && this.stateChangeCallback) {
                this.stateChangeCallback(event);
            }
        });
    }

    /**
     * Set the YouTube player instance (created by YouTube IFrame API)
     * @param {object} ytPlayer - YouTube player instance
     */
    setYouTubePlayer(ytPlayer) {
        this.youtubePlayer = ytPlayer;
    }

    /**
     * Get the currently active player
     * @returns {object} The active player instance
     */
    getActivePlayer() {
        return this.activePlayerType === 'plex' ? this.plexPlayer : this.youtubePlayer;
    }

    /**
     * Set the active player type
     * @param {string} type - 'youtube' or 'plex'
     */
    setActivePlayerType(type) {
        // Stop current player if switching
        if (this.activePlayerType !== type) {
            this.stop();
        }
        this.activePlayerType = type;
    }

    /**
     * Check if Plex is the active player
     * @returns {boolean}
     */
    isPlexActive() {
        return this.activePlayerType === 'plex';
    }

    /**
     * Check if Plex player is configured and ready
     * @returns {boolean}
     */
    isPlexReady() {
        return this.plexPlayer && this.plexPlayer.isConfigured();
    }

    /**
     * Set the state change callback
     * @param {function} callback - Callback for player state changes
     */
    onStateChange(callback) {
        this.stateChangeCallback = callback;
    }

    /**
     * Cue content for playback
     * For YouTube: cueVideoById
     * For Plex: cueTrack
     *
     * @param {object} options - { videoId, startTime } for YouTube or { trackInfo } for Plex
     */
    async cue(options) {
        const player = this.getActivePlayer();
        if (!player) return;

        if (this.activePlayerType === 'plex') {
            await this.plexPlayer.cueTrack(options.trackInfo);
        } else {
            player.cueVideoById(options.videoId, options.startTime || 0);
        }
    }

    /**
     * Start playback
     */
    play() {
        const player = this.getActivePlayer();
        if (player) {
            player.playVideo();
        }
    }

    /**
     * Pause playback
     */
    pause() {
        const player = this.getActivePlayer();
        if (player) {
            player.pauseVideo();
        }
        this.clearPlaybackTimer();
    }

    /**
     * Stop playback
     */
    stop() {
        if (this.youtubePlayer) {
            try {
                this.youtubePlayer.pauseVideo();
            } catch (e) {
                // Player might not be ready
            }
        }
        if (this.plexPlayer) {
            this.plexPlayer.pauseVideo();
        }
        this.clearPlaybackTimer();
    }

    /**
     * Seek to a specific time
     * @param {number} seconds - Time in seconds
     * @param {boolean} allowSeekAhead - Allow seeking beyond buffered content
     */
    seekTo(seconds, allowSeekAhead = true) {
        const player = this.getActivePlayer();
        if (player) {
            player.seekTo(seconds, allowSeekAhead);
        }
    }

    /**
     * Get current playback time
     * @returns {number} Current time in seconds
     */
    getCurrentTime() {
        const player = this.getActivePlayer();
        return player ? player.getCurrentTime() : 0;
    }

    /**
     * Get total duration
     * @returns {number} Duration in seconds
     */
    getDuration() {
        const player = this.getActivePlayer();
        return player ? player.getDuration() : 0;
    }

    /**
     * Set volume
     * @param {number} volume - Volume level (0-100)
     */
    setVolume(volume) {
        const player = this.getActivePlayer();
        if (player) {
            player.setVolume(volume);
        }
    }

    /**
     * Unmute
     */
    unMute() {
        const player = this.getActivePlayer();
        if (player) {
            player.unMute();
        }
    }

    /**
     * Get video/track data
     * @returns {object} Media metadata
     */
    getVideoData() {
        const player = this.getActivePlayer();
        return player ? player.getVideoData() : {};
    }

    /**
     * Set a timer to auto-stop after duration
     * @param {number} durationMs - Duration in milliseconds
     * @param {function} onStop - Callback when timer fires
     */
    setPlaybackTimer(durationMs, onStop) {
        this.clearPlaybackTimer();
        this.playbackTimer = setTimeout(() => {
            this.pause();
            if (onStop) onStop();
        }, durationMs);
    }

    /**
     * Clear the playback timer
     */
    clearPlaybackTimer() {
        if (this.playbackTimer) {
            clearTimeout(this.playbackTimer);
            this.playbackTimer = null;
        }
    }

    /**
     * Play at a random start time (for game mode)
     * @param {number} playbackDuration - How long to play in seconds
     * @param {number} currentStartTime - Custom start time from QR code
     * @param {function} onStop - Callback when playback stops
     */
    playAtRandomStartTime(playbackDuration, currentStartTime = 0, onStop) {
        const player = this.getActivePlayer();
        if (!player) return;

        const minStartPercentage = 0.10;
        const maxEndPercentage = 0.90;
        const videoDuration = this.getDuration();

        let startTime = currentStartTime;
        let endTime = playbackDuration;

        const minStartTime = Math.max(currentStartTime, videoDuration * minStartPercentage);
        const maxEndTime = videoDuration * maxEndPercentage;

        if (endTime > maxEndTime) {
            endTime = maxEndTime;
            startTime = Math.max(minStartTime, endTime - playbackDuration);
        }

        if (startTime <= minStartTime) {
            const range = maxEndTime - minStartTime - playbackDuration;
            const randomOffset = Math.random() * range;
            startTime = minStartTime + randomOffset;
            endTime = startTime + playbackDuration;
        }

        console.log('Playing random:', startTime, endTime);
        this.seekTo(startTime, true);
        this.play();

        this.setPlaybackTimer((endTime - startTime) * 1000, onStop);
    }
}

// Singleton instance
export const playerManager = new PlayerManager();
