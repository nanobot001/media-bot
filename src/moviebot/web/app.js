let state = {
  activeDomain: 'movies',
  activeTab: 'discovery',
  activeFeed: 'available_now',
  activeGenre: '',
  activeSort: 'date.desc',
  activeTimeRange: localStorage.getItem('preferred_time_range') || '30d',
  activeTier: '',
  activeLanguage: localStorage.getItem('preferred_language') || 'en_us',
  page: 1,
  sidebarOpen: true,
  items: [],
  historyItems: [],
  sidebarInterval: null
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    lucide.createIcons();
  }

  // Restore saved settings
  const timeSelect = document.getElementById('time-range-select');
  if (timeSelect) {
    timeSelect.value = state.activeTimeRange;
  }
  const langSelect = document.getElementById('language-select');
  if (langSelect) {
    langSelect.value = state.activeLanguage;
  }

  fetchDomainStats();
  loadDiscoveryFeed();
  loadSidebarHistory();
  setTimeout(prefetchCommonFeeds, 1000);

  // Polling sidebar history every 10 seconds
  state.sidebarInterval = setInterval(loadSidebarHistory, 10000);

});

// Pre-fetch all primary feeds into client memory in background
function prefetchCommonFeeds() {
  const commonUrls = [
    '/api/discover?domain=movies&feed=available_now&page=1&limit=48',
    '/api/discover?domain=movies&feed=available_now&page=1&limit=48&sort_by=date.desc',
    '/api/discover?domain=movies&feed=available_now&page=1&limit=48&tier=major',
    '/api/discover?domain=movies&feed=available_now&page=1&limit=48&tier=indie',
    '/api/discover?domain=movies&feed=trending&page=1&limit=48',
    '/api/discover?domain=movies&feed=popular&page=1&limit=48',
    '/api/discover?domain=movies&feed=new&page=1&limit=48',
    '/api/discover?domain=tv&feed=available_now&page=1&limit=48',
    '/api/discover?domain=tv&feed=trending&page=1&limit=48',
    '/api/discover?domain=tv&feed=popular&page=1&limit=48',
    '/api/discover?domain=tv_classic&feed=available_now&page=1&limit=48',
    '/api/discover?domain=tv_classic&feed=trending&page=1&limit=48',
  ];
  for (const u of commonUrls) {
    fetch(u).then(r => r.json()).then(data => {
      if (data && data.data && data.data.results) {
        clientFeedCache.set(u, { time: Date.now(), results: data.data.results });
      }
    }).catch(() => {});
  }
}

// Tier Filter Change Handler
function onTierSelect(tier) {
  state.activeTier = tier;
  state.page = 1;
  loadDiscoveryFeed(false);
}

// Domain Switcher (Movies, TV Series, Classic TV)
async function switchDomain(domain) {
  state.activeDomain = domain;
  state.page = 1;

  const availBtn = document.getElementById('feed-btn-available_now');
  const trendingBtn = document.getElementById('feed-btn-trending');
  const popularBtn = document.getElementById('feed-btn-popular');
  const newBtn = document.getElementById('feed-btn-new');
  const availLabel = document.getElementById('label-available-now');
  const newLabel = document.getElementById('label-new');
  const timeSelect = document.getElementById('time-range-select');
  const sortSelect = document.getElementById('sort-select');
  const tierSelect = document.getElementById('tier-select');
  const langSelect = document.getElementById('language-select');

  if (langSelect) {
    langSelect.value = state.activeLanguage;
  }

  if (domain === 'tv_classic' || domain === 'classic_tv') {
    // Classic TV: eliminate trending and popular, update label to Classic Library
    if (trendingBtn) trendingBtn.classList.add('hidden');
    if (popularBtn) popularBtn.classList.add('hidden');
    if (newBtn) newBtn.classList.add('hidden');
    if (availLabel) availLabel.innerText = '📻 Classic Library';
    
    // Switch active feed to available_now
    state.activeFeed = 'available_now';
    document.querySelectorAll('.feed-pill').forEach(btn => btn.classList.remove('active'));
    if (availBtn) availBtn.classList.add('active');

    // Era dropdown for Classic TV
    if (timeSelect) {
      timeSelect.innerHTML = `
        <option value="all" class="bg-surface-card text-white">📻 All Classic & Concluded Eras</option>
        <option value="2020s" class="bg-surface-card text-white">🗓️ 2020s Classics (2020–2025)</option>
        <option value="2010s" class="bg-surface-card text-white">🗓️ 2010s Classics (2010–2019)</option>
        <option value="2000s" class="bg-surface-card text-white">🗓️ 2000s Classics (2000–2009)</option>
        <option value="1990s" class="bg-surface-card text-white">📼 1990s Classics (1990–1999)</option>
        <option value="1980s" class="bg-surface-card text-white">📺 1980s Classics (1980–1989)</option>
        <option value="1970s" class="bg-surface-card text-white">📻 1970s Classics (1970–1979)</option>
        <option value="1960s" class="bg-surface-card text-white">🎞️ 1960s Classics (1960–1969)</option>
        <option value="prior_50s" class="bg-surface-card text-white">📽️ 1950s & Prior</option>
      `;
      state.activeTimeRange = 'all';
      timeSelect.value = 'all';
    }


    // Sort options for Classic TV (eliminated Release Date)
    if (sortSelect) {
      sortSelect.innerHTML = `
        <option value="popularity.desc" class="bg-surface-card text-white">🔥 Most Popular</option>
        <option value="rating.desc" class="bg-surface-card text-white">★ Highest Rated</option>
        <option value="votes.desc" class="bg-surface-card text-white">🗳️ Most Voted</option>
        <option value="title.asc" class="bg-surface-card text-white">🔤 Title (A-Z)</option>
      `;
      state.activeSort = 'popularity.desc';
      sortSelect.value = 'popularity.desc';
    }

    // Network Scope for Classic TV
    if (tierSelect) {
      if (tierSelect.parentElement) tierSelect.parentElement.classList.remove('hidden');
      tierSelect.innerHTML = `
        <option value="major" class="bg-surface-card text-white">🌟 Major Networks & Streamers</option>
        <option value="broadcast" class="bg-surface-card text-white">📡 US Broadcast (NBC, CBS, ABC, FOX)</option>
        <option value="premium" class="bg-surface-card text-white">💎 Premium Cable (HBO, Showtime, FX, AMC)</option>
        <option value="streamers" class="bg-surface-card text-white">🍿 Major Streamers (Netflix, Prime, Max, Apple)</option>
        <option value="" class="bg-surface-card text-white">🌐 All Networks & Archives</option>
      `;
      state.activeTier = 'major';
      tierSelect.value = 'major';
    }
  } else if (domain === 'tv') {
    // Restore and adapt platform filter for TV
    if (tierSelect && tierSelect.parentElement) {
      tierSelect.parentElement.classList.remove('hidden');
    }

    // TV Series: eliminate crowded pills, clean single pill
    if (trendingBtn) trendingBtn.classList.add('hidden');
    if (popularBtn) popularBtn.classList.add('hidden');
    if (newBtn) newBtn.classList.add('hidden');
    if (availLabel) availLabel.innerText = '⚡ TV Series';
    
    // Switch active feed to available_now
    state.activeFeed = 'available_now';
    document.querySelectorAll('.feed-pill').forEach(btn => btn.classList.remove('active'));
    if (availBtn) availBtn.classList.add('active');

    if (timeSelect) {
      timeSelect.innerHTML = `
        <option value="all" class="bg-surface-card text-white">⏱️ All Active Series</option>
        <option value="30d" class="bg-surface-card text-white">⏱️ Past 30 Days (Airings)</option>
        <option value="60d" class="bg-surface-card text-white">⏱️ Past 60 Days (Airings)</option>
        <option value="90d" class="bg-surface-card text-white">⏱️ Past 90 Days (Airings)</option>
        <option value="6m" class="bg-surface-card text-white">⏱️ Past 6 Months (Airings)</option>
        <option value="1y" class="bg-surface-card text-white">⏱️ Past 1 Year (Airings)</option>
      `;
      state.activeTimeRange = 'all';
      timeSelect.value = 'all';
    }

    if (sortSelect) {
      sortSelect.innerHTML = `
        <option value="popularity.desc" class="bg-surface-card text-white">🔥 Most Popular</option>
        <option value="rating.desc" class="bg-surface-card text-white">★ Highest Rated</option>
        <option value="votes.desc" class="bg-surface-card text-white">🗳️ Most Voted</option>
        <option value="date.desc" class="bg-surface-card text-white">📅 Air Date</option>
        <option value="title.asc" class="bg-surface-card text-white">🔤 Title (A-Z)</option>
      `;
      state.activeSort = 'popularity.desc';
      sortSelect.value = 'popularity.desc';
    }

    // Platform / Network Filter for Modern TV
    if (tierSelect) {
      tierSelect.innerHTML = `
        <option value="major" class="bg-surface-card text-white">🌟 Major Networks & Streamers</option>
        <option value="streamers" class="bg-surface-card text-white">🍿 Major Streamers (Netflix, Apple, Prime, Disney+)</option>
        <option value="broadcast" class="bg-surface-card text-white">📡 US Broadcast (NBC, CBS, ABC, FOX)</option>
        <option value="premium" class="bg-surface-card text-white">💎 Premium Cable (HBO, FX, AMC, Showtime)</option>
        <option value="" class="bg-surface-card text-white">🌐 All Networks & International</option>
      `;
      state.activeTier = 'major';
      tierSelect.value = 'major';
    }
  }
 else {
    // Movies: show standard feeds, release dates, and timeframes
    if (trendingBtn) trendingBtn.classList.remove('hidden');
    if (popularBtn) popularBtn.classList.remove('hidden');
    if (newBtn) newBtn.classList.remove('hidden');
    if (availLabel) availLabel.innerText = '⚡ Available Now';
    if (newLabel) newLabel.innerText = 'In Theaters';

    if (timeSelect) {
      timeSelect.innerHTML = `
        <option value="30d" class="bg-surface-card text-white">⏱️ Past 30 Days</option>
        <option value="60d" class="bg-surface-card text-white">⏱️ Past 60 Days</option>
        <option value="90d" class="bg-surface-card text-white">⏱️ Past 90 Days</option>
        <option value="6m" class="bg-surface-card text-white">⏱️ Past 6 Months</option>
        <option value="1y" class="bg-surface-card text-white">⏱️ Past 1 Year</option>
        <option value="all" class="bg-surface-card text-white">⏱️ All Time</option>
      `;
      state.activeTimeRange = '30d';
      timeSelect.value = '30d';
    }

    if (sortSelect) {
      sortSelect.innerHTML = `
        <option value="date.desc" class="bg-surface-card text-white">📅 Release Date</option>
        <option value="popularity.desc" class="bg-surface-card text-white">🔥 Most Popular</option>
        <option value="rating.desc" class="bg-surface-card text-white">★ Highest Rated</option>
        <option value="votes.desc" class="bg-surface-card text-white">🗳️ Most Voted</option>
        <option value="title.asc" class="bg-surface-card text-white">🔤 Title (A-Z)</option>
      `;
      state.activeSort = 'date.desc';
      sortSelect.value = 'date.desc';
    }

    // Studio Tier Filter for Movies
    if (tierSelect) {
      if (tierSelect.parentElement) tierSelect.parentElement.classList.remove('hidden');
      tierSelect.innerHTML = `
        <option value="" class="bg-surface-card text-white">All Tiers</option>
        <option value="major" class="bg-surface-card text-white">🌟 Major Studio</option>
        <option value="indie" class="bg-surface-card text-white">🌱 Indie & Boutique</option>
      `;
      state.activeTier = '';
      tierSelect.value = '';
    }
  }

  // Update Genre Dropdown per Domain
  const genreSelect = document.getElementById('genre-select');
  if (genreSelect) {
    if (domain === 'tv' || domain === 'tv_classic' || domain === 'classic_tv') {
      genreSelect.innerHTML = `
        <option value="" class="bg-surface-card text-white">All Genres</option>
        <option value="kids" class="bg-surface-card text-white">👶 Kids & Family</option>
        <option value="animation" class="bg-surface-card text-white">🎨 Animation & Cartoons</option>
        <option value="action" class="bg-surface-card text-white">Action & Adventure</option>
        <option value="comedy" class="bg-surface-card text-white">Comedy</option>
        <option value="crime" class="bg-surface-card text-white">Crime</option>
        <option value="documentary" class="bg-surface-card text-white">Documentary</option>
        <option value="drama" class="bg-surface-card text-white">Drama</option>
        <option value="mystery" class="bg-surface-card text-white">Mystery</option>
        <option value="sci-fi" class="bg-surface-card text-white">Sci-Fi & Fantasy</option>
        <option value="reality" class="bg-surface-card text-white">Reality TV</option>
      `;
    } else {
      genreSelect.innerHTML = `
        <option value="" class="bg-surface-card text-white">All Genres</option>
        <option value="family" class="bg-surface-card text-white">👶 Kids & Family</option>
        <option value="animation" class="bg-surface-card text-white">🎨 Animation</option>
        <option value="action" class="bg-surface-card text-white">Action</option>
        <option value="adventure" class="bg-surface-card text-white">Adventure</option>
        <option value="comedy" class="bg-surface-card text-white">Comedy</option>
        <option value="crime" class="bg-surface-card text-white">Crime</option>
        <option value="drama" class="bg-surface-card text-white">Drama</option>
        <option value="horror" class="bg-surface-card text-white">Horror</option>
        <option value="mystery" class="bg-surface-card text-white">Mystery</option>
        <option value="sci-fi" class="bg-surface-card text-white">Sci-Fi & Fantasy</option>
        <option value="thriller" class="bg-surface-card text-white">Thriller</option>
      `;
    }
    genreSelect.value = state.activeGenre;
  }




  // Update UI Domain buttons
  document.querySelectorAll('.domain-btn').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-domain-${domain}`);
  if (activeBtn) activeBtn.classList.add('active');

  // Refresh current view
  if (state.activeTab === 'discovery') {
    loadDiscoveryFeed();
  } else if (state.activeTab === 'history') {
    loadHistoryTable(domain);
  }
  loadSidebarHistory();
}



// Tab Switcher
function switchTab(tab) {
  state.activeTab = tab;

  const viewDiscovery = document.getElementById('view-discovery');
  const viewHistory = document.getElementById('view-history');
  const tabBtnDiscovery = document.getElementById('tab-btn-discovery');
  const tabBtnHistory = document.getElementById('tab-btn-history');

  if (tab === 'discovery') {
    viewDiscovery.classList.remove('hidden');
    viewHistory.classList.add('hidden');
    tabBtnDiscovery.classList.add('active', 'text-cyan-400');
    tabBtnDiscovery.classList.remove('text-slate-400');
    tabBtnHistory.classList.remove('active', 'text-cyan-400');
    tabBtnHistory.classList.add('text-slate-400');
  } else {
    viewDiscovery.classList.add('hidden');
    viewHistory.classList.remove('hidden');
    tabBtnHistory.classList.add('active', 'text-cyan-400');
    tabBtnHistory.classList.remove('text-slate-400');
    tabBtnDiscovery.classList.remove('active', 'text-cyan-400');
    tabBtnDiscovery.classList.add('text-slate-400');
    loadHistoryTable(state.activeDomain);
  }
}

// Feed Switcher (Available Now, Trending, Popular, Top Rated, New)
function switchFeed(feed) {
  state.activeFeed = feed;
  state.page = 1;
  document.querySelectorAll('.feed-pill').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`feed-btn-${feed}`);
  if (activeBtn) activeBtn.classList.add('active');
  loadDiscoveryFeed();
}

function onLanguageSelect(lang) {
  state.activeLanguage = lang;
  state.page = 1;
  localStorage.setItem('preferred_language', lang);
  loadDiscoveryFeed();
}


function onGenreSelect(genre) {
  state.activeGenre = genre;
  state.page = 1;
  loadDiscoveryFeed();
}

function onSortSelect(sort) {
  state.activeSort = sort;
  state.page = 1;
  loadDiscoveryFeed();
}

function onTimeRangeSelect(range) {
  state.activeTimeRange = range;
  state.page = 1;
  localStorage.setItem('preferred_time_range', range);
  loadDiscoveryFeed();
}

// Load More handler
async function loadMoreReleases() {
  const btn = document.getElementById('btn-load-more');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<div class="w-3.5 h-3.5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin"></div><span>Loading more...</span>';
  }
  state.page += 2;
  await loadDiscoveryFeed(true);
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="chevrons-down" class="w-4 h-4 text-cyan-400"></i><span>Load More Releases</span>';
    if (window.lucide) lucide.createIcons();
  }
}

// Fetch Domain Overview Stats
async function fetchDomainStats() {
  try {
    const res = await fetch('/api/domains');
    if (!res.ok) return;
    const data = await res.json();
    const domains = data.domains || {};

    if (domains.movies) {
      document.getElementById('badge-movies-count').innerText = `${domains.movies.item_count} items`;
    }
    if (domains.tv) {
      document.getElementById('badge-tv-count').innerText = `${domains.tv.show_count} shows`;
    }
    if (domains.tv_classic) {
      document.getElementById('badge-tv_classic-count').innerText = `${domains.tv_classic.show_count} shows`;
    }
  } catch (err) {
    console.error("Failed to fetch domain stats:", err);
  }
}

// Client-Side High-Speed SWR Cache
const clientFeedCache = new Map();

// Fetch and Render Discovery Feed
async function loadDiscoveryFeed(append = false) {
  const grid = document.getElementById('poster-grid');
  const loading = document.getElementById('grid-loading');
  const empty = document.getElementById('grid-empty');
  const loadMore = document.getElementById('load-more-container');

  let url = `/api/discover?domain=${state.activeDomain}&feed=${state.activeFeed}&page=${state.page}&limit=48`;
  if (state.activeLanguage) {
    url += `&language=${encodeURIComponent(state.activeLanguage)}`;
  }
  if (state.activeGenre) {
    url += `&genre=${encodeURIComponent(state.activeGenre)}`;
  }
  if (state.activeSort) {
    url += `&sort_by=${encodeURIComponent(state.activeSort)}`;
  }
  if (state.activeTimeRange) {
    url += `&time_range=${encodeURIComponent(state.activeTimeRange)}`;
  }
  if (state.activeTier) {
    url += `&tier=${encodeURIComponent(state.activeTier)}`;
  }


  // Instant SWR Render from Client Memory
  if (!append && clientFeedCache.has(url)) {
    const cachedEntry = clientFeedCache.get(url);
    if (Date.now() - cachedEntry.time < 300000) { // 5-minute client freshness
      state.items = cachedEntry.results;
      loading.classList.add('hidden');
      empty.classList.add('hidden');
      renderPosterGrid(state.items);
      if (loadMore) {
        if (state.items.length > 0) loadMore.classList.remove('hidden');
        else loadMore.classList.add('hidden');
      }
      // Silently revalidate in background without resetting UI
      fetch(url).then(r => r.json()).then(data => {
        const fresh = (data && data.data && data.data.results) ? data.data.results : [];
        if (fresh.length > 0) {
          clientFeedCache.set(url, { time: Date.now(), results: fresh });
        }
      }).catch(() => {});
      return;
    }
  }

  if (!append) {
    state.page = 1;
    empty.classList.add('hidden');
    if (grid.children.length === 0) {
      grid.innerHTML = '';
      loading.classList.remove('hidden');
    } else {
      grid.classList.add('opacity-40', 'pointer-events-none', 'transition-opacity', 'duration-150');
    }
    if (loadMore) loadMore.classList.add('hidden');
  }

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
    const data = await res.json();

    const newResults = (data && data.data && data.data.results) ? data.data.results : [];

    if (!append && newResults.length === 0) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      if (loadMore) loadMore.classList.add('hidden');
      return;
    }

    if (append) {
      // Deduplicate by tmdb_id
      const existingIds = new Set(state.items.map(i => i.tmdb_id));
      for (const item of newResults) {
        if (!existingIds.has(item.tmdb_id)) {
          state.items.push(item);
        }
      }
    } else {
      state.items = newResults;
      clientFeedCache.set(url, { time: Date.now(), results: newResults });
    }

    renderPosterGrid(state.items);

    if (loadMore) {
      if (newResults.length > 0) {
        loadMore.classList.remove('hidden');
      } else {
        loadMore.classList.add('hidden');
      }
    }
  } catch (err) {
    console.error("Discovery error:", err);
    if (!append && state.items.length === 0) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
    }
  } finally {
    loading.classList.add('hidden');
    grid.classList.remove('opacity-40', 'pointer-events-none');
  }
}



// Render Poster Card Grid
function renderPosterGrid(items) {
  const grid = document.getElementById('poster-grid');
  grid.innerHTML = '';

  items.forEach(item => {
    const card = document.createElement('div');
    const isMajor = item.tier === 'major';
    
    // Ambient Border Glow: Major is brighter luminous indigo; Indie is darker muted slate
    const borderStyle = isMajor
      ? 'border-indigo-500/45 hover:border-indigo-400 shadow-md shadow-indigo-950/40 bg-surface-card'
      : 'border-slate-800 hover:border-slate-700 shadow-sm bg-slate-900/70';

    card.className = `poster-card relative group rounded-2xl border ${borderStyle} overflow-hidden cursor-pointer flex flex-col transition-all duration-200`;
    card.onclick = () => openModal(item);

    const posterUrl = item.poster_url || (item.poster_path ? `https://image.tmdb.org/t/p/w500${item.poster_path}` : 'https://via.placeholder.com/300x450?text=No+Artwork');
    const rating = item.vote_average ? item.vote_average.toFixed(1) : (item.rating || 'N/A');
    const year = item.year || (item.release_date ? item.release_date.substring(0, 4) : '');
    const inLibrary = item.owned || item.in_library || false;
    const firstGenre = Array.isArray(item.genres) ? (item.genres[0] || '') : (item.genres ? item.genres.split(',')[0] : (item.network || ''));

    card.innerHTML = `
      <div class="relative aspect-[2/3] w-full overflow-hidden bg-slate-900">
        <img src="${posterUrl}" alt="${item.title}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy">
        
        <!-- Top Badges Overlay -->
        <div class="absolute top-2.5 inset-x-2.5 flex items-center justify-between pointer-events-none">
          <span class="px-2 py-0.5 rounded-md bg-black/70 backdrop-blur-md text-amber-400 text-xs font-extrabold flex items-center gap-1 border border-white/10 shadow-md">
            <i data-lucide="star" class="w-3 h-3 fill-amber-400"></i> ${rating}
          </span>

          <div class="flex items-center gap-1.5 pointer-events-auto">
            ${item.available_now && !inLibrary ? `
              <span class="lightning-badge p-1 rounded-full cursor-help flex items-center justify-center" title="⚡ High-Quality Digital Release (Non-CAM)">
                <i data-lucide="zap" class="w-3.5 h-3.5"></i>
              </span>
            ` : ''}

            ${inLibrary ? `
              <span class="px-2 py-0.5 rounded-md bg-emerald-950/80 backdrop-blur-md text-emerald-400 border border-emerald-700 text-[10px] font-bold shadow-md">
                IN PLEX
              </span>
            ` : ''}
          </div>
        </div>

        <!-- Hover Overlay Gradient -->
        <div class="absolute inset-0 bg-gradient-to-t from-surface-base via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200"></div>
      </div>

      <!-- Card Details Footer (Clean Typography) -->
      <div class="p-3 flex flex-col justify-between flex-1">
        <h4 class="font-bold text-xs text-white line-clamp-1 group-hover:text-cyan-400 transition-colors">${item.title}</h4>
        <div class="flex items-center justify-between mt-1 text-[11px] text-slate-400">
          <span>${year}</span>
          <span class="capitalize text-slate-500 truncate max-w-[90px]">${firstGenre}</span>
        </div>
      </div>
    `;

    grid.appendChild(card);
  });

  if (window.lucide) {
    lucide.createIcons();
  }
}



// Open Centered Detail Modal with Live Rich Metadata
async function openModal(item) {
  const modal = document.getElementById('media-modal');
  const backdrop = document.getElementById('modal-backdrop');
  const poster = document.getElementById('modal-poster');
  const title = document.getElementById('modal-title');
  const tagline = document.getElementById('modal-tagline');
  const rating = document.getElementById('modal-rating');
  const year = document.getElementById('modal-year');
  const runtime = document.getElementById('modal-runtime');
  const status = document.getElementById('modal-status');
  const libBadge = document.getElementById('modal-library-badge');
  const genres = document.getElementById('modal-genres');
  const synopsis = document.getElementById('modal-synopsis');
  const crewNames = document.getElementById('modal-crew-names');
  const studioNames = document.getElementById('modal-studio-names');
  const castList = document.getElementById('modal-cast-list');
  const trailerBtn = document.getElementById('modal-trailer-btn');
  const imdbLink = document.getElementById('modal-imdb-link');
  const tmdbLink = document.getElementById('modal-tmdb-link');
  const extraInfo = document.getElementById('modal-extra-info');
  const searchBtn = document.getElementById('modal-search-btn');

  // Surface Defaults
  const posterUrl = item.poster_url || (item.poster_path ? `https://image.tmdb.org/t/p/w500${item.poster_path}` : 'https://via.placeholder.com/300x450?text=No+Poster');
  const backdropUrl = item.backdrop_url || (item.backdrop_path ? `https://image.tmdb.org/t/p/original${item.backdrop_path}` : posterUrl);

  backdrop.src = backdropUrl;
  poster.src = posterUrl;
  title.innerText = item.title;
  if (tagline) {
    tagline.innerText = '';
    tagline.classList.add('hidden');
  }
  rating.innerHTML = `<i data-lucide="star" class="w-3.5 h-3.5 fill-amber-300"></i> ${item.vote_average ? item.vote_average.toFixed(1) : (item.rating || 'N/A')}`;
  year.innerText = item.year || (item.release_date ? item.release_date.substring(0, 4) : 'Unknown');

  if (runtime) runtime.innerHTML = '<i data-lucide="clock" class="w-3 h-3 text-cyan-400"></i> <span>--</span>';
  if (status) status.innerText = 'Loading info...';
  if (crewNames) crewNames.innerText = 'Fetching credits...';
  if (studioNames) studioNames.innerText = 'Fetching studios...';
  if (castList) castList.innerHTML = '<div class="text-slate-500 text-xs py-2 col-span-3">Loading starring cast...</div>';
  if (trailerBtn) trailerBtn.classList.add('hidden');
  if (imdbLink) imdbLink.classList.add('hidden');
  if (tmdbLink) tmdbLink.href = item.tmdb_id ? (state.activeDomain === 'movies' ? `https://www.themoviedb.org/movie/${item.tmdb_id}` : `https://www.themoviedb.org/tv/${item.tmdb_id}`) : '#';

  const inLibrary = item.owned || item.in_library || false;
  if (inLibrary) {
    libBadge.classList.remove('hidden');
    libBadge.className = 'px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-bold';
    libBadge.innerHTML = '<i data-lucide="check-circle" class="w-3.5 h-3.5 inline mr-1"></i> OWNED IN PLEX';
  } else if (item.available_now) {
    libBadge.classList.remove('hidden');
    libBadge.className = 'px-2.5 py-1 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-xs font-bold flex items-center gap-1';
    libBadge.innerHTML = '<i data-lucide="zap" class="w-3.5 h-3.5 text-cyan-300 fill-cyan-300 inline"></i> AVAILABLE FOR INSTANT DOWNLOAD';
  } else {
    libBadge.classList.remove('hidden');
    libBadge.className = 'px-2.5 py-1 rounded-lg bg-slate-800 text-slate-400 border border-slate-700 text-xs font-medium flex items-center gap-1';
    libBadge.innerHTML = '<i data-lucide="clock" class="w-3.5 h-3.5 inline"></i> THEATRICAL / UPCOMING';
  }

  // Genres
  genres.innerHTML = '';
  const genreList = Array.isArray(item.genres) ? item.genres : (item.genres ? item.genres.split(',') : []);
  genreList.forEach(g => {
    const genreStr = typeof g === 'string' ? g.trim() : (g.name || '');
    if (genreStr) {
      const pill = document.createElement('span');
      pill.className = 'px-2.5 py-0.5 rounded-md bg-cyan-950/70 border border-cyan-500/30 text-cyan-300 text-xs font-semibold shadow-sm';
      pill.innerText = genreStr;
      genres.appendChild(pill);
    }
  });

  synopsis.innerText = item.overview || item.synopsis || 'No synopsis available for this title.';
  extraInfo.innerText = item.network ? `Network: ${item.network}` : '';

  searchBtn.onclick = () => {
    alert(`Initiating release search for "${item.title}"... (Search & Lightning Cache modal wired in Block 5-2)`);
  };

  modal.classList.remove('hidden');
  setTimeout(() => {
    modal.classList.add('open');
  }, 10);

  if (window.lucide) {
    lucide.createIcons();
  }

  // Fetch Full Rich Deep Metadata
  if (item.tmdb_id) {
    try {
      const res = await fetch(`/api/details?domain=${state.activeDomain}&tmdb_id=${item.tmdb_id}`);
      if (res.ok) {
        const payload = await res.json();
        const d = payload.details || {};

        // Tagline
        if (d.tagline && tagline) {
          tagline.innerText = `"${d.tagline}"`;
          tagline.classList.remove('hidden');
        }

        // Runtime / Season count
        if (runtime) {
          if (d.runtime_formatted) {
            runtime.innerHTML = `<i data-lucide="clock" class="w-3 h-3 text-cyan-400"></i> <span>${d.runtime_formatted}</span>`;
          } else if (d.number_of_seasons) {
            runtime.innerHTML = `<i data-lucide="tv" class="w-3 h-3 text-cyan-400"></i> <span>${d.number_of_seasons} Season${d.number_of_seasons > 1 ? 's' : ''} (${d.number_of_episodes || 0} eps)</span>`;
          }
        }

        // Status
        if (status && d.status) {
          status.innerText = d.status;
        }

        // Modal Tier Badge (Direct from unified backend classifier)
        const modalTierBadge = document.getElementById('modal-tier-badge');
        if (modalTierBadge) {
          const tierVal = d.tier || item.tier || 'indie';
          if (tierVal === 'major') {
            modalTierBadge.innerText = '🌟 Major Studio';
            modalTierBadge.className = 'px-2.5 py-1 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 text-xs font-bold shadow-sm';
            modalTierBadge.classList.remove('hidden');
          } else {
            modalTierBadge.innerText = '🌱 Indie & Boutique';
            modalTierBadge.className = 'px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-xs font-bold shadow-sm';
            modalTierBadge.classList.remove('hidden');
          }
        }



        // Certification & Theatrical Box

        const theatricalBox = document.getElementById('modal-theatrical-box');
        const theatricalPill = document.getElementById('modal-theatrical-status-pill');
        const theatricalDesc = document.getElementById('modal-theatrical-desc');
        const certBadge = document.getElementById('modal-cert');

        if (d.certification && certBadge) {
          certBadge.innerText = d.certification;
          certBadge.classList.remove('hidden');
        } else if (certBadge) {
          certBadge.classList.add('hidden');
        }

        if (theatricalBox && theatricalPill && theatricalDesc) {
          const tDateStr = d.us_theatrical_date || d.release_date || item.release_date;
          if (tDateStr) {
            const relDate = new Date(tDateStr + 'T00:00:00');
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            const diffTime = relDate - today;
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

            const options = { year: 'numeric', month: 'long', day: 'numeric' };
            const formattedDate = isNaN(relDate.getTime()) ? tDateStr : relDate.toLocaleDateString('en-US', options);

            if (state.activeDomain === 'movies') {
              if (diffDays > 0) {
                // Upcoming
                theatricalPill.innerText = `Upcoming in ${diffDays} day${diffDays > 1 ? 's' : ''}`;
                theatricalPill.className = 'text-[10px] px-2 py-0.5 rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold';
                theatricalDesc.innerHTML = `<span class="text-white font-semibold">${formattedDate}</span> · Theatrical premiere scheduled. No high-quality digital releases available yet.`;
                if (!inLibrary && libBadge) {
                  libBadge.className = 'px-2.5 py-1 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-bold flex items-center gap-1 shadow-sm';
                  libBadge.innerHTML = '<i data-lucide="clock" class="w-3.5 h-3.5 inline"></i> UPCOMING THEATRICAL';
                }
              } else {
                const daysAgo = Math.abs(diffDays);
                if (daysAgo < 60) {
                  theatricalPill.innerText = `In Theaters (${daysAgo} day${daysAgo > 1 ? 's' : ''} ago)`;
                  theatricalPill.className = 'text-[10px] px-2 py-0.5 rounded-md bg-red-500/20 text-red-300 border border-red-500/30 font-bold';
                  theatricalDesc.innerHTML = `<span class="text-white font-semibold">${formattedDate}</span> · Currently in theatrical exclusivity window. Only low-quality CAM/Telesync copies exist in the wild (filtered out by MediaBot).`;
                  if (!inLibrary && libBadge) {
                    libBadge.className = 'px-2.5 py-1 rounded-lg bg-red-500/20 text-red-300 border border-red-500/30 text-xs font-bold flex items-center gap-1 shadow-sm';
                    libBadge.innerHTML = '<i data-lucide="film" class="w-3.5 h-3.5 inline"></i> IN THEATERS (CAM ONLY)';
                  }
                } else {
                  theatricalPill.innerText = `Past Theatrical Window (${daysAgo} days ago)`;
                  theatricalPill.className = 'text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold';
                  theatricalDesc.innerHTML = `<span class="text-white font-semibold">${formattedDate}</span> · Full studio theatrical run concluded. High-quality 4K/1080p Digital & WEB-DL releases are available.`;
                  if (!inLibrary && libBadge) {
                    libBadge.className = 'px-2.5 py-1 rounded-lg bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-xs font-bold flex items-center gap-1 shadow-sm';
                    libBadge.innerHTML = '<i data-lucide="zap" class="w-3.5 h-3.5 text-cyan-300 fill-cyan-300 inline"></i> AVAILABLE FOR INSTANT DOWNLOAD';
                  }
                }
              }
              theatricalBox.classList.remove('hidden');
            } else {
              // TV Shows
              const firstAir = d.first_air_date || item.first_air_date || tDateStr;
              theatricalPill.innerText = d.status || 'Broadcast';
              theatricalPill.className = 'text-[10px] px-2 py-0.5 rounded-md bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-bold';
              theatricalDesc.innerHTML = `Series premiered on <span class="text-white font-semibold">${firstAir}</span>${d.networks && d.networks.length > 0 ? ` on ${d.networks.join(', ')}` : ''}. Total: ${d.number_of_seasons || 1} Seasons, ${d.number_of_episodes || 0} Episodes.`;
              theatricalBox.classList.remove('hidden');
            }

          } else {
            theatricalBox.classList.add('hidden');
          }
        }

        // Financials (Budget & Box Office)
        const finGrid = document.getElementById('modal-financial-grid');
        const revEl = document.getElementById('modal-revenue');
        const budEl = document.getElementById('modal-budget');
        const roiEl = document.getElementById('modal-roi');

        if (finGrid) {
          if (state.activeDomain === 'movies' && (d.revenue_formatted || d.budget_formatted)) {
            if (revEl) revEl.innerText = d.revenue_formatted || 'Not Disclosed';
            if (budEl) budEl.innerText = d.budget_formatted || 'Not Disclosed';
            if (roiEl) {
              if (d.revenue && d.budget && d.budget > 0) {
                const mult = (d.revenue / d.budget).toFixed(1);
                roiEl.innerText = `${mult}x Return`;
                roiEl.className = mult >= 2.5 ? 'text-sm font-black text-emerald-400 mt-0.5' : 'text-sm font-black text-amber-300 mt-0.5';
              } else {
                roiEl.innerText = 'N/A';
                roiEl.className = 'text-sm font-black text-slate-400 mt-0.5';
              }
            }
            finGrid.classList.remove('hidden');
            finGrid.classList.add('grid');
          } else {
            finGrid.classList.add('hidden');
            finGrid.classList.remove('grid');
          }
        }

        // Crew / Directors / Creators
        if (crewNames) {
          const crewList = (d.directors && d.directors.length > 0) ? d.directors : (d.creators && d.creators.length > 0 ? d.creators : []);
          crewNames.innerText = crewList.length > 0 ? crewList.join(', ') : 'Not listed';
        }

        // Studios / Networks
        if (studioNames) {
          const studioList = (d.production_companies && d.production_companies.length > 0) ? d.production_companies : (d.networks && d.networks.length > 0 ? d.networks : []);
          studioNames.innerText = studioList.length > 0 ? studioList.slice(0, 3).join(', ') : 'Not listed';
        }

        // Starring Cast
        if (castList) {
          castList.innerHTML = '';
          const castMembers = d.cast || [];
          if (castMembers.length === 0) {
            castList.innerHTML = '<div class="text-slate-500 text-xs py-2 col-span-3">No cast details listed.</div>';
          } else {
            castMembers.slice(0, 6).forEach(actor => {
              const actorCard = document.createElement('div');
              actorCard.className = 'flex items-center gap-2 p-1.5 rounded-lg bg-surface-border/40 border border-white/5';
              const pImg = actor.profile_url ? `<img src="${actor.profile_url}" class="w-8 h-8 rounded-full object-cover shrink-0 bg-slate-800">` : '<div class="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center shrink-0 text-slate-500 text-[10px] font-bold"><i data-lucide="user" class="w-4 h-4"></i></div>';
              actorCard.innerHTML = `
                ${pImg}
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-bold text-white truncate">${actor.name}</p>
                  <p class="text-[10px] text-slate-400 truncate">${actor.character || 'Cast'}</p>
                </div>
              `;
              castList.appendChild(actorCard);
            });
          }
        }

        // Review Quotes Section
        const revSec = document.getElementById('modal-reviews-section');
        const revList = document.getElementById('modal-reviews-list');
        if (revSec && revList) {
          const reviews = d.reviews || [];
          if (reviews.length > 0) {
            revList.innerHTML = '';
            reviews.forEach(r => {
              const quoteCard = document.createElement('div');
              quoteCard.className = 'p-2.5 rounded-xl bg-surface-border/30 border border-white/5 text-xs';
              const ratingBadge = r.rating ? `<span class="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold text-[10px] flex items-center gap-0.5"><i data-lucide="star" class="w-2.5 h-2.5 fill-amber-300"></i> ${r.rating}/10</span>` : '';
              quoteCard.innerHTML = `
                <div class="flex items-center justify-between mb-1">
                  <span class="font-bold text-cyan-300 text-[11px]">${r.author}</span>
                  ${ratingBadge}
                </div>
                <p class="text-slate-300 italic font-normal leading-relaxed">"${r.content}"</p>
              `;
              revList.appendChild(quoteCard);
            });
            revSec.classList.remove('hidden');
          } else {
            revSec.classList.add('hidden');
          }
        }

        // Trailer
        if (trailerBtn && d.trailer_url) {
          trailerBtn.href = d.trailer_url;
          trailerBtn.classList.remove('hidden');
        }

        // IMDb
        if (imdbLink && d.imdb_url) {
          imdbLink.href = d.imdb_url;
          imdbLink.classList.remove('hidden');
        }

        if (window.lucide) {
          lucide.createIcons();
        }
      }
    } catch (err) {
      console.warn("Could not fetch extended details:", err);
    }
  }
}





function closeModal() {
  const modal = document.getElementById('media-modal');
  modal.classList.remove('open');
  setTimeout(() => {
    modal.classList.add('hidden');
  }, 200);
}

// Toggle Recent Ingest Sidebar
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar-activity');
  const icon = document.getElementById('sidebar-toggle-icon');
  state.sidebarOpen = !state.sidebarOpen;

  if (state.sidebarOpen) {
    sidebar.classList.remove('hidden');
    icon.setAttribute('data-lucide', 'panel-right-close');
  } else {
    sidebar.classList.add('hidden');
    icon.setAttribute('data-lucide', 'panel-right-open');
  }
  if (window.lucide) {
    lucide.createIcons();
  }
}

// Fetch and Render Sidebar Recent Ingest Activity Feed
async function loadSidebarHistory() {
  const container = document.getElementById('sidebar-feed-container');
  const countBadge = document.getElementById('sidebar-count');

  try {
    const res = await fetch(`/api/history?limit=15`);
    if (!res.ok) return;
    const data = await res.json();
    const jobs = data.jobs || [];

    countBadge.innerText = `${jobs.length} Tracked`;
    container.innerHTML = '';

    if (jobs.length === 0) {
      container.innerHTML = `
        <div class="py-12 text-center text-slate-500 text-xs">
          <i data-lucide="inbox" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
          No recent download activity
        </div>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    jobs.forEach(job => {
      const card = document.createElement('div');
      card.className = 'p-3 rounded-xl bg-surface-card border border-surface-border hover:border-slate-700 transition flex flex-col gap-1.5 shadow-sm';

      let badgeClasses = 'bg-slate-800 text-slate-300 border-slate-700';
      let iconName = 'clock';

      if (job.badge_color === 'green') {
        badgeClasses = 'bg-emerald-950/80 text-emerald-300 border-emerald-800';
        iconName = 'check-circle';
      } else if (job.badge_color === 'blue') {
        badgeClasses = 'bg-cyan-950/80 text-cyan-300 border-cyan-800 animate-pulse';
        iconName = 'download';
      } else if (job.badge_color === 'amber') {
        badgeClasses = 'bg-amber-950/80 text-amber-300 border-amber-800';
        iconName = 'cog';
      } else if (job.badge_color === 'purple') {
        badgeClasses = 'bg-purple-950/80 text-purple-300 border-purple-800';
        iconName = 'flask-conical';
      }

      card.innerHTML = `
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-bold text-white line-clamp-1">${job.selected_file_name || 'Enqueued File'}</span>
        </div>
        <div class="flex items-center justify-between text-[10px] text-slate-400">
          <span class="px-2 py-0.5 rounded-md border ${badgeClasses} font-semibold flex items-center gap-1">
            <i data-lucide="${iconName}" class="w-3 h-3"></i> ${job.status_label}
          </span>
          <span class="uppercase tracking-wider font-bold text-[9px] text-slate-500">${job.domain || 'movies'}</span>
        </div>
      `;
      container.appendChild(card);
    });

    if (window.lucide) {
      lucide.createIcons();
    }
  } catch (err) {
    console.error("Failed to load sidebar history:", err);
  }
}

// Fetch and Render Full Download History Table
async function loadHistoryTable(domain = 'all') {
  const tbody = document.getElementById('history-table-body');
  document.querySelectorAll('.history-domain-btn').forEach(btn => btn.classList.remove('active'));

  tbody.innerHTML = `
    <tr>
      <td colspan="5" class="py-12 text-center text-slate-500">
        <div class="w-6 h-6 border-2 border-cyan-500/20 border-t-cyan-500 rounded-full animate-spin mx-auto mb-2"></div>
        Loading history records...
      </td>
    </tr>
  `;

  try {
    const res = await fetch(`/api/history?domain=${domain}&limit=50`);
    const data = await res.json();
    const jobs = data.jobs || [];

    tbody.innerHTML = '';
    if (jobs.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="py-12 text-center text-slate-500">
            No historical download jobs found for domain: <strong>${domain}</strong>
          </td>
        </tr>
      `;
      return;
    }

    jobs.forEach(job => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-surface-hover/50 transition-colors';

      let badgeClasses = 'bg-slate-800 text-slate-300 border-slate-700';
      if (job.badge_color === 'green') badgeClasses = 'bg-emerald-950 text-emerald-300 border-emerald-800';
      else if (job.badge_color === 'blue') badgeClasses = 'bg-cyan-950 text-cyan-300 border-cyan-800';
      else if (job.badge_color === 'amber') badgeClasses = 'bg-amber-950 text-amber-300 border-amber-800';
      else if (job.badge_color === 'purple') badgeClasses = 'bg-purple-950 text-purple-300 border-purple-800';

      tr.innerHTML = `
        <td class="py-3 px-4 font-semibold text-white max-w-xs truncate">${job.selected_file_name || 'Enqueued File'}</td>
        <td class="py-3 px-4 uppercase font-bold text-[10px] text-slate-400">${job.domain || 'movies'}</td>
        <td class="py-3 px-4 font-mono text-[11px] text-slate-400">${job.target_dir || '-'}</td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded-md border ${badgeClasses} text-[11px] font-semibold">
            ${job.status_label}
          </span>
        </td>
        <td class="py-3 px-4 text-slate-400 whitespace-nowrap">${job.created_at || '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load history table:", err);
  }
}
