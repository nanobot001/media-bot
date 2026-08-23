import { useState, useEffect, useMemo } from 'react';
import { Search, Film, Star, Clock, Sparkles, Filter, X, Award, MapPin, Tag, Play } from 'lucide-react';

export interface MovieItem {
  id: string;
  source?: string;
  rating_key?: string;
  title: string;
  normalized_title?: string;
  year?: number;
  imdb_id?: string;
  rating?: number;
  audience_rating?: number;
  content_rating?: string;
  runtime?: number;
  resolution?: string;
  bitrate_kbps?: number;
  watch_status?: string;
  watch_count?: number;
  poster_url?: string;
  synopsis?: string;
  tagline?: string;
  genres?: string | string[];
  directors?: string | string[];
  studios?: string | string[];
  writers?: string | string[];
  cast?: string | string[];
  countries?: string | string[];
  collections?: string | string[];
  labels?: string | string[];
  brand_tags?: string | string[];
  franchise_tags?: string | string[];
  universe_tags?: string | string[];
  award_tags?: string | string[];
  award_wins_json?: string;
  setting_locations?: string | string[];
  story_locations?: string | string[];
  theme_tags?: string | string[];
  tone_tags?: string | string[];
  premise_tags?: string | string[];
  character_tags?: string | string[];
  craft_tags?: string | string[];
  [key: string]: unknown;
}

function parseJsonList(val: unknown): string[] {
  if (!val) return [];
  if (Array.isArray(val)) return val.map(String);
  if (typeof val === 'string') {
    try {
      const parsed = JSON.parse(val);
      if (Array.isArray(parsed)) return parsed.map(String);
      if (typeof parsed === 'string') return [parsed];
    } catch {
      return val.split(',').map(s => s.trim()).filter(Boolean);
    }
  }
  return [];
}

interface LibraryViewProps {
  apiBaseUrl?: string;
}

export function LibraryView({ apiBaseUrl = '' }: LibraryViewProps) {
  const [movies, setMovies] = useState<MovieItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Client-side search and filters
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGenre, setSelectedGenre] = useState<string>('all');
  const [selectedResolution, setSelectedResolution] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'available' | 'downloading' | 'monitored'>('all');

  // Selected movie for detail modal
  const [selectedMovie, setSelectedMovie] = useState<MovieItem | null>(null);

  useEffect(() => {
    let isMounted = true;
    async function fetchLibrary() {
      setLoading(true);
      setError(null);
      try {
        const url = `${apiBaseUrl}/api/library?limit=300`;
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error(`Failed to fetch library: ${res.status} ${res.statusText}`);
        }
        const json = await res.json();
        if (isMounted) {
          const items = json?.data?.movies || json?.data?.items || json?.items || [];
          setMovies(Array.isArray(items) ? items : []);
        }
      } catch (err: unknown) {
        if (isMounted) {
          const msg = err instanceof Error ? err.message : 'Unknown error loading library';
          setError(msg);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    fetchLibrary();
    return () => {
      isMounted = false;
    };
  }, [apiBaseUrl]);

  // Extract unique genres for filter dropdown
  const allGenres = useMemo(() => {
    const genreSet = new Set<string>();
    movies.forEach(m => {
      parseJsonList(m.genres).forEach(g => genreSet.add(g));
    });
    return Array.from(genreSet).sort();
  }, [movies]);

  // Extract unique resolutions
  const allResolutions = useMemo(() => {
    const resSet = new Set<string>();
    movies.forEach(m => {
      if (m.resolution) resSet.add(m.resolution.toUpperCase());
    });
    return Array.from(resSet).sort();
  }, [movies]);

  // Filtered movies
  const filteredMovies = useMemo(() => {
    return movies.filter(movie => {
      // Text search in title, synopsis, director, cast
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const titleMatch = (movie.title || '').toLowerCase().includes(q);
        const synopsisMatch = (movie.synopsis || '').toLowerCase().includes(q);
        const directorMatch = parseJsonList(movie.directors).some(d => d.toLowerCase().includes(q));
        const castMatch = parseJsonList(movie.cast).some(c => c.toLowerCase().includes(q));
        if (!titleMatch && !synopsisMatch && !directorMatch && !castMatch) {
          return false;
        }
      }

      // Genre filter
      if (selectedGenre !== 'all') {
        const genres = parseJsonList(movie.genres).map(g => g.toLowerCase());
        if (!genres.includes(selectedGenre.toLowerCase())) {
          return false;
        }
      }

      // Resolution filter
      if (selectedResolution !== 'all') {
        const res = (movie.resolution || '').toUpperCase();
        if (res !== selectedResolution) {
          return false;
        }
      }

      // Status filter
      if (statusFilter !== 'all') {
        const isWatched = (movie.watch_status || '').toLowerCase() === 'watched';
        if (statusFilter === 'available' && !isWatched && !movie.resolution) return false;
        if (statusFilter === 'monitored' && (isWatched || movie.resolution)) return false;
      }

      return true;
    });
  }, [movies, searchQuery, selectedGenre, selectedResolution, statusFilter]);

  return (
    <div className="library-view flex flex-col gap-4">
      {/* Controls / Filter Bar */}
      <div className="glass-panel filter-bar flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="search-input-wrapper flex items-center gap-2 flex-1" style={{ width: '100%' }}>
          <Search size={18} style={{ color: 'var(--text-secondary)' }} />
          <input
            type="text"
            className="search-input"
            placeholder="Search by title, director, cast, or plot keywords..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className="clear-button" onClick={() => setSearchQuery('')} title="Clear">
              <X size={16} />
            </button>
          )}
        </div>

        <div className="filters-group flex items-center gap-2 flex-wrap" style={{ width: '100%', justifyContent: 'flex-end' }}>
          <div className="select-wrapper flex items-center gap-1">
            <Filter size={16} style={{ color: 'var(--text-secondary)' }} />
            <select
              className="filter-select"
              value={selectedGenre}
              onChange={e => setSelectedGenre(e.target.value)}
              title="Filter by Genre"
            >
              <option value="all">All Genres ({movies.length})</option>
              {allGenres.map(g => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          <div className="select-wrapper">
            <select
              className="filter-select"
              value={selectedResolution}
              onChange={e => setSelectedResolution(e.target.value)}
              title="Filter by Resolution"
            >
              <option value="all">All Qualities</option>
              {allResolutions.map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>

          <div className="segmented-status flex gap-1">
            <button
              className={`status-btn ${statusFilter === 'all' ? 'active' : ''}`}
              onClick={() => setStatusFilter('all')}
            >
              All
            </button>
            <button
              className={`status-btn ${statusFilter === 'available' ? 'active' : ''}`}
              onClick={() => setStatusFilter('available')}
            >
              Available
            </button>
          </div>
        </div>
      </div>

      {/* Library Stats / Count */}
      <div className="flex items-center justify-between" style={{ padding: '0 0.5rem' }}>
        <p style={{ margin: 0, fontSize: '0.875rem' }}>
          Showing <strong>{filteredMovies.length}</strong> of {movies.length} movies
        </p>
      </div>

      {/* Loading & Error States */}
      {loading && (
        <div className="glass-panel text-center" style={{ padding: '3rem 1rem' }}>
          <Film size={36} className="animate-pulse" style={{ margin: '0 auto 1rem', color: 'var(--primary)' }} />
          <h3>Loading your library...</h3>
          <p>Connecting to media mirror database</p>
        </div>
      )}

      {error && (
        <div className="glass-panel" style={{ borderColor: 'rgba(239, 68, 68, 0.4)', background: 'rgba(239, 68, 68, 0.05)' }}>
          <h3 style={{ color: 'var(--danger)' }}>Failed to load library</h3>
          <p>{error}</p>
          <button className="nav-button active" onClick={() => window.location.reload()}>Retry</button>
        </div>
      )}

      {/* Movie Grid */}
      {!loading && !error && filteredMovies.length === 0 && (
        <div className="glass-panel text-center" style={{ padding: '3rem 1rem' }}>
          <Film size={36} style={{ margin: '0 auto 1rem', opacity: 0.5 }} />
          <h3>No matching movies found</h3>
          <p>Try adjusting your search query or filter options</p>
        </div>
      )}

      {!loading && !error && filteredMovies.length > 0 && (
        <div className="movie-grid">
          {filteredMovies.map(movie => (
            <MovieCard
              key={movie.id || `${movie.title}-${movie.year}`}
              movie={movie}
              onClick={() => setSelectedMovie(movie)}
            />
          ))}
        </div>
      )}

      {/* Movie Detail Modal */}
      {selectedMovie && (
        <MovieDetailModal
          movie={selectedMovie}
          onClose={() => setSelectedMovie(null)}
        />
      )}
    </div>
  );
}

function MovieCard({ movie, onClick }: { movie: MovieItem; onClick: () => void }) {
  const [imageFailed, setImageFailed] = useState(false);
  const genres = parseJsonList(movie.genres).slice(0, 2);
  const isAvailable = (movie.watch_status || '').toLowerCase() === 'watched' || Boolean(movie.resolution);

  return (
    <div className="movie-card glass-panel flex flex-col" onClick={onClick}>
      <div className="poster-container">
        {movie.poster_url && !imageFailed ? (
          <img
            src={movie.poster_url}
            alt={movie.title}
            className="poster-img"
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <div className="poster-placeholder flex flex-col items-center justify-center">
            <Film size={40} style={{ opacity: 0.3, marginBottom: '0.5rem' }} />
            <span style={{ fontSize: '0.75rem', opacity: 0.6, padding: '0 0.5rem', textAlign: 'center' }}>
              {movie.title}
            </span>
          </div>
        )}

        {/* Quality Badge */}
        {movie.resolution && (
          <span className="badge badge-default poster-badge-top-left">
            {movie.resolution.toUpperCase()}
          </span>
        )}

        {/* Availability Badge */}
        <span className={`badge ${isAvailable ? 'badge-success' : 'badge-default'} poster-badge-top-right`}>
          {isAvailable ? 'AVAILABLE' : 'MONITORED'}
        </span>
      </div>

      <div className="movie-card-body flex flex-col flex-1 justify-between" style={{ marginTop: '0.75rem' }}>
        <div>
          <h4 className="movie-title" title={movie.title}>{movie.title}</h4>
          <div className="flex items-center gap-2" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            <span>{movie.year || 'N/A'}</span>
            {movie.content_rating && (
              <>
                <span>•</span>
                <span className="content-rating-tag">{movie.content_rating}</span>
              </>
            )}
            {movie.rating ? (
              <>
                <span>•</span>
                <span className="flex items-center gap-1" style={{ color: '#fbbf24' }}>
                  <Star size={12} fill="#fbbf24" />
                  {movie.rating.toFixed(1)}
                </span>
              </>
            ) : null}
          </div>
        </div>

        {genres.length > 0 && (
          <div className="flex gap-1 flex-wrap" style={{ marginTop: '0.5rem' }}>
            {genres.map(g => (
              <span key={g} className="badge badge-default" style={{ fontSize: '0.65rem' }}>
                {g}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MovieDetailModal({ movie, onClose }: { movie: MovieItem; onClose: () => void }) {
  const genres = parseJsonList(movie.genres);
  const directors = parseJsonList(movie.directors);
  const cast = parseJsonList(movie.cast).slice(0, 6);
  const themes = parseJsonList(movie.theme_tags);
  const tones = parseJsonList(movie.tone_tags);
  const locations = parseJsonList(movie.story_locations || movie.setting_locations);
  const franchises = parseJsonList(movie.franchise_tags || movie.brand_tags);
  const awards = parseJsonList(movie.award_tags);

  return (
    <div className="modal-overlay flex items-center justify-center" onClick={onClose}>
      <div className="modal-content glass-panel" onClick={e => e.stopPropagation()}>
        <button className="modal-close-btn" onClick={onClose} title="Close">
          <X size={20} />
        </button>

        <div className="modal-layout flex flex-col md:flex-row gap-6">
          {/* Left: Poster */}
          <div className="modal-poster-col" style={{ width: '220px', flexShrink: 0 }}>
            {movie.poster_url ? (
              <img
                src={movie.poster_url}
                alt={movie.title}
                className="poster-img"
                style={{ width: '100%', borderRadius: 'var(--radius-md)', boxShadow: '0 8px 30px rgba(0,0,0,0.5)' }}
              />
            ) : (
              <div className="poster-placeholder flex flex-col items-center justify-center" style={{ height: '330px' }}>
                <Film size={48} style={{ opacity: 0.3 }} />
              </div>
            )}

            <div className="flex flex-col gap-2" style={{ marginTop: '1rem' }}>
              {movie.rating_key && (
                <button
                  className="nav-button active flex items-center justify-center gap-2"
                  style={{ width: '100%', background: 'linear-gradient(135deg, #e5a00d, #f59e0b)', color: '#000', fontWeight: 600 }}
                  onClick={() => alert(`Opening Plex player for rating key ${movie.rating_key}...`)}
                >
                  <Play size={16} fill="#000" />
                  Watch in Plex
                </button>
              )}
            </div>
          </div>

          {/* Right: Rich Metadata */}
          <div className="modal-details-col flex-1 flex flex-col gap-4">
            <div>
              <h2 style={{ fontSize: '1.75rem', marginBottom: '0.25rem' }}>{movie.title}</h2>
              {movie.tagline && (
                <p style={{ fontStyle: 'italic', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.95rem' }}>
                  "{movie.tagline}"
                </p>
              )}
              <div className="flex items-center gap-3 flex-wrap" style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                <span>{movie.year}</span>
                {movie.content_rating && <span className="content-rating-tag">{movie.content_rating}</span>}
                {movie.runtime && (
                  <span className="flex items-center gap-1">
                    <Clock size={14} />
                    {Math.floor(movie.runtime / 60)}h {movie.runtime % 60}m
                  </span>
                )}
                {movie.resolution && (
                  <span className="badge badge-info">{movie.resolution.toUpperCase()}</span>
                )}
                {movie.rating && (
                  <span className="flex items-center gap-1" style={{ color: '#fbbf24', fontWeight: 600 }}>
                    <Star size={14} fill="#fbbf24" />
                    {movie.rating.toFixed(1)} / 10
                  </span>
                )}
              </div>
            </div>

            {/* Genres */}
            {genres.length > 0 && (
              <div className="flex gap-2 flex-wrap">
                {genres.map(g => (
                  <span key={g} className="badge badge-default" style={{ padding: '0.35rem 0.75rem' }}>
                    {g}
                  </span>
                ))}
              </div>
            )}

            {/* Synopsis */}
            {movie.synopsis && (
              <div>
                <h4 style={{ fontSize: '0.95rem', color: 'var(--text-primary)', marginBottom: '0.35rem' }}>Synopsis</h4>
                <p style={{ fontSize: '0.9rem', lineHeight: '1.6', color: 'var(--text-secondary)' }}>
                  {movie.synopsis}
                </p>
              </div>
            )}

            {/* Directors & Cast */}
            <div className="grid grid-cols-2 gap-4" style={{ marginTop: '0.5rem' }}>
              {directors.length > 0 && (
                <div>
                  <h5 style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Director</h5>
                  <p style={{ color: 'var(--text-primary)', fontSize: '0.9rem', marginTop: '0.2rem' }}>
                    {directors.join(', ')}
                  </p>
                </div>
              )}

              {cast.length > 0 && (
                <div>
                  <h5 style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Cast</h5>
                  <p style={{ color: 'var(--text-primary)', fontSize: '0.9rem', marginTop: '0.2rem' }}>
                    {cast.join(', ')}
                  </p>
                </div>
              )}
            </div>

            {/* Hybrid Intelligence Enrichment Section */}
            {(themes.length > 0 || tones.length > 0 || locations.length > 0 || awards.length > 0 || franchises.length > 0) && (
              <div className="glass" style={{ padding: '1rem', borderRadius: 'var(--radius-sm)', marginTop: '0.5rem' }}>
                <h4 className="flex items-center gap-2" style={{ fontSize: '0.9rem', color: 'var(--primary-hover)', marginBottom: '0.5rem' }}>
                  <Sparkles size={16} />
                  Intelligence & Hard Facts
                </h4>
                
                <div className="flex flex-col gap-2" style={{ fontSize: '0.85rem' }}>
                  {franchises.length > 0 && (
                    <div className="flex items-center gap-2">
                      <Tag size={14} style={{ color: 'var(--text-secondary)' }} />
                      <strong style={{ color: 'var(--text-secondary)' }}>Franchise:</strong>
                      <span>{franchises.join(', ')}</span>
                    </div>
                  )}

                  {awards.length > 0 && (
                    <div className="flex items-center gap-2">
                      <Award size={14} style={{ color: '#fbbf24' }} />
                      <strong style={{ color: 'var(--text-secondary)' }}>Awards:</strong>
                      <span>{awards.join(', ')}</span>
                    </div>
                  )}

                  {locations.length > 0 && (
                    <div className="flex items-center gap-2">
                      <MapPin size={14} style={{ color: 'var(--text-secondary)' }} />
                      <strong style={{ color: 'var(--text-secondary)' }}>Setting:</strong>
                      <span>{locations.join(', ')}</span>
                    </div>
                  )}

                  {themes.length > 0 && (
                    <div className="flex items-center gap-2 flex-wrap">
                      <strong style={{ color: 'var(--text-secondary)' }}>Themes:</strong>
                      {themes.map(t => (
                        <span key={t} className="badge badge-default" style={{ fontSize: '0.7rem' }}>{t}</span>
                      ))}
                    </div>
                  )}

                  {tones.length > 0 && (
                    <div className="flex items-center gap-2 flex-wrap">
                      <strong style={{ color: 'var(--text-secondary)' }}>Tone:</strong>
                      {tones.map(t => (
                        <span key={t} className="badge badge-default" style={{ fontSize: '0.7rem' }}>{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
