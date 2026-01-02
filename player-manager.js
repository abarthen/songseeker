/**
 * Player Manager for SongSeeker
 *
 * Provides a unified interface for Plex audio playback.
 */

import { PlexPlayer } from './plex-player.js';

export class PlayerManager {
    constructor() {
        this.plexPlayer = null;
        this.stateChangeCallback = null;
        this.playbackTimer = null;

        // Player states
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
            if (this.stateChangeCallback) {
                this.stateChangeCallback(event);
            }
        });
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
     * @param {object} options - { trackInfo } for Plex track
     */
    async cue(options) {
        if (!this.plexPlayer) return;
        await this.plexPlayer.cueTrack(options.trackInfo);
    }

    /**
     * Start playback
     */
    play() {
        if (this.plexPlayer) {
            this.plexPlayer.playVideo();
        }
    }

    /**
     * Pause playback
     */
    pause() {
        if (this.plexPlayer) {
            this.plexPlayer.pauseVideo();
        }
        this.clearPlaybackTimer();
    }

    /**
     * Stop playback
     */
    stop() {
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
        if (this.plexPlayer) {
            this.plexPlayer.seekTo(seconds, allowSeekAhead);
        }
    }

    /**
     * Get current playback time
     * @returns {number} Current time in seconds
     */
    getCurrentTime() {
        return this.plexPlayer ? this.plexPlayer.getCurrentTime() : 0;
    }

    /**
     * Get total duration
     * @returns {number} Duration in seconds
     */
    getDuration() {
        return this.plexPlayer ? this.plexPlayer.getDuration() : 0;
    }

    /**
     * Set volume
     * @param {number} volume - Volume level (0-100)
     */
    setVolume(volume) {
        if (this.plexPlayer) {
            this.plexPlayer.setVolume(volume);
        }
    }

    /**
     * Unmute
     */
    unMute() {
        if (this.plexPlayer) {
            this.plexPlayer.unMute();
        }
    }

    /**
     * Get track data
     * @returns {object} Media metadata
     */
    getVideoData() {
        return this.plexPlayer ? this.plexPlayer.getVideoData() : {};
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
        if (!this.plexPlayer) return;

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
