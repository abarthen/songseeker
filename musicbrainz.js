/**
 * MusicBrainz Year Lookup for SongSeeker
 *
 * Resolves the original release year of songs that are not covered by an
 * edition mapping, where the Plex year is unreliable (usually the album year
 * of a compilation or remaster). Mirrors the matching rules of
 * tools/plex_mapper/validate_years.py.
 *
 * Two sources are combined and the earlier year wins:
 * 1. The recording behind the Plex track's MusicBrainz track ID (exact match)
 * 2. An artist + title search, taking the earliest matching recording
 */

const MUSICBRAINZ_API = 'https://musicbrainz.org/ws/2/recording';
const REQUEST_SPACING_MS = 1100; // MusicBrainz allows about 1 request per second
const MAX_RETRIES = 3;
const RETRY_BASE_DELAY_MS = 2000; // Doubled per retry when rate limited
const CACHE_KEY = 'musicbrainzYearCache';

let lastRequestTime = 0;
let requestQueue = Promise.resolve();

// ratingKey -> year (null when MusicBrainz has no match)
const yearCache = loadCache();

function loadCache() {
    try {
        return JSON.parse(localStorage.getItem(CACHE_KEY)) || {};
    } catch (e) {
        return {};
    }
}

function saveCache() {
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(yearCache));
    } catch (e) {
        // Storage unavailable or full; lookups still work, just uncached
    }
}

/**
 * Run a recording search, queued so requests stay within the rate limit.
 * @returns {Array|null} Recordings, or null when skipped because the song is no longer current
 */
function searchRecordings(query, isCurrent) {
    const run = async () => {
        // Don't spend the rate limit on a song that was already skipped
        if (!isCurrent()) return null;
        const wait = lastRequestTime + REQUEST_SPACING_MS - Date.now();
        if (wait > 0) {
            await new Promise(resolve => setTimeout(resolve, wait));
        }
        if (!isCurrent()) return null;
        lastRequestTime = Date.now();

        const url = `${MUSICBRAINZ_API}?query=${encodeURIComponent(query)}&fmt=json&limit=100`;
        for (let attempt = 0; ; attempt++) {
            const response = await fetch(url, {
                headers: { 'Accept': 'application/json' }
            });
            lastRequestTime = Date.now();
            // 503 means rate limited; back off and retry
            if (response.status === 503 && attempt < MAX_RETRIES - 1 && isCurrent()) {
                await new Promise(resolve => setTimeout(resolve, RETRY_BASE_DELAY_MS * 2 ** attempt));
                continue;
            }
            if (!response.ok) {
                throw new Error(`MusicBrainz request failed: HTTP ${response.status}`);
            }
            const data = await response.json();
            return data.recordings || [];
        }
    };
    const result = requestQueue.then(run);
    requestQueue = result.catch(() => {});
    return result;
}

function escapeLucene(text) {
    return text.replace(/[+\-&|!(){}[\]^"~*?:\\/]/g, '\\$&');
}

// Same normalization as normalize_for_comparison() in tools/plex_mapper/plex_api.py,
// plus typographic quotes (MusicBrainz titles often use ’)
function normalize(text) {
    if (!text) return '';
    return text.toLowerCase()
        .replace(/ & /g, ' and ').replace(/&/g, ' and ')
        .replace(/[\s\-_'’‘`´".,:;!?“”]+/g, '')
        .replace(/[äáàâ]/g, 'a')
        .replace(/[öóòô]/g, 'o')
        .replace(/[üúùû]/g, 'u')
        .replace(/[éèê]/g, 'e')
        .replace(/ñ/g, 'n')
        .replace(/ß/g, 'ss')
        .replace(/æ/g, 'ae')
        .replace(/œ/g, 'oe');
}

function releaseYear(recording) {
    const date = recording && recording['first-release-date'];
    return date && date.length >= 4 ? parseInt(date.slice(0, 4), 10) : null;
}

function artistCredit(recording) {
    return (recording['artist-credit'] || [])
        .map(credit => (credit.name || '') + (credit.joinphrase || ''))
        .join('');
}

function titleMatches(wanted, found) {
    if (!wanted || !found) return false;
    if (wanted === found) return true;
    // Allow "Satisfaction" to match "(I Can't Get No) Satisfaction", but not
    // "Reborn" to match "Queen of Hearts Reborn"
    if (!wanted.includes(found) && !found.includes(wanted)) return false;
    return Math.min(wanted.length, found.length) / Math.max(wanted.length, found.length) >= 0.5;
}

function artistMatches(wanted, found) {
    if (!wanted || !found) return false;
    return wanted.includes(found) || found.includes(wanted);
}

// Earliest release year among recordings matching artist and title
function earliestMatchingYear(artist, title, recordings) {
    const artistNorm = normalize(artist);
    const titleNorm = normalize(title);
    const years = recordings
        .filter(r => titleMatches(titleNorm, normalize(r.title)) &&
                     artistMatches(artistNorm, normalize(artistCredit(r))))
        .map(releaseYear)
        .filter(Boolean);
    return years.length > 0 ? Math.min(...years) : null;
}

// Strip version suffixes like "(2007 Remaster)" or "(feat. X)"
function cleanTitle(title) {
    return title
        .replace(/\s*[([][^)\]]*(remaster|version|edit|mix|feat\.?|ft\.|live|mono|stereo|single)[^)\]]*[)\]]/gi, '')
        .replace(/\s+(feat\.?|ft\.)\s.*$/i, '')
        .trim();
}

// "Kanye West, Jamie Foxx" -> "Kanye West"
function firstArtist(artist) {
    return artist.split(/,| & | feat\.? | ft\. | x | und /i)[0].trim();
}

function searchQuery(artist, title) {
    return `artist:"${escapeLucene(artist)}" AND recording:"${escapeLucene(title)}"`;
}

// Recordings on live releases are skipped: "earliest" would otherwise often
// pick a live cover of an older song with the same title
const NO_LIVE_FILTER = 'AND NOT secondarytype:live';

/**
 * @returns {number|null|undefined} Earliest matching year, null if none,
 *          undefined if skipped because the song is no longer current
 */
async function searchEarliestYear(artist, title, filter, isCurrent) {
    const recordings = await searchRecordings(`${searchQuery(artist, title)} ${filter}`, isCurrent);
    return recordings === null ? undefined : earliestMatchingYear(artist, title, recordings);
}

/**
 * Look up the original release year of a Plex track.
 * @param {object} track - { ratingKey, artist, title, mbid } (mbid is the MusicBrainz track ID)
 * @param {function} isCurrent - Returns false once the song was skipped, to cancel pending requests
 * @returns {number|null|undefined} Year, null if MusicBrainz has no match,
 *          undefined if the lookup was cancelled or failed
 */
export async function lookupReleaseYear(track, isCurrent = () => true) {
    if (track.ratingKey in yearCache) {
        return yearCache[track.ratingKey];
    }

    const years = [];
    try {
        if (track.mbid) {
            const recordings = await searchRecordings(`tid:${track.mbid}`, isCurrent);
            if (recordings === null) return undefined;
            const year = releaseYear(recordings[0]);
            if (year) years.push(year);
        }

        if (track.artist && track.title) {
            // Search without version suffixes, so "Song (Mono)" or "Song (Live)"
            // finds the original recording
            const title = cleanTitle(track.title) || track.title;
            let artist = track.artist;
            let year = await searchEarliestYear(artist, title, NO_LIVE_FILTER, isCurrent);
            if (year === undefined) return undefined;

            // Only as fallback, as splitting breaks band names like "Simon & Garfunkel"
            if (year === null && firstArtist(track.artist) !== track.artist) {
                artist = firstArtist(track.artist);
                year = await searchEarliestYear(artist, title, NO_LIVE_FILTER, isCurrent);
                if (year === undefined) return undefined;
            }

            // Results are capped at 100, so popular songs may miss the original;
            // look explicitly for anything officially released earlier
            if (year && year > 1950) {
                const older = await searchEarliestYear(artist, title,
                    `${NO_LIVE_FILTER} AND status:official AND firstreleasedate:[1900 TO ${year - 1}]`, isCurrent);
                if (older === undefined) return undefined;
                year = older || year;
            }
            if (year) years.push(year);
        }
    } catch (e) {
        console.error('MusicBrainz lookup failed:', e);
        return undefined;
    }

    const year = years.length > 0 ? Math.min(...years) : null;
    console.log(`MusicBrainz year for ${track.artist} - ${track.title}: ${year ?? 'not found'}`);
    yearCache[track.ratingKey] = year;
    saveCache();
    return year;
}
