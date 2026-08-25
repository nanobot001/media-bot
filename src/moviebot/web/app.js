let state = {
  activeDomain: localStorage.getItem('preferred_domain') || 'movies',
  activeTab: 'discovery',
  activeFeed: 'available_now',
  activeGenre: '',
  activeSort: 'date.desc',
  activeTimeRange: '30d',
  activeTier: '',
  activeLanguage: 'en_us',
  page: 1,
  sidebarOpen: true,
  items: [],
  historyItems: [],
  sidebarInterval: null,
  userSettings: {},
  // Search & Lightning Cache State
  searchDomain: 'movies',
  searchQuery: '',
  searchSeason: null,
  searchEpisode: null,
  searchResults: [],
  searchFilterQuality: '',
  searchCacheOnly: false,
  isSearching: false,
  // TV Ingestion & Telemetry State
  tvManifest: null,
  activeTVSeason: 1,
  selectedTVEpisodes: new Set(),
  currentDetailItem: null,
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    lucide.createIcons();
  }

  // Apply default domain configurations immediately
  applyDomainDefaults(state.activeDomain);

  // Parallel non-blocking initialization: Start feed, stats, history, and live SSE telemetry
  loadDiscoveryFeed();
  fetchDomainStats();
  loadSidebarHistory();
  initSSETelemetry();

  // Fetch persisted settings in parallel and re-align defaults if custom domain exists
  fetch('/api/settings')
    .then(res => res.ok ? res.json() : null)
    .then(json => {
      if (json && json.data?.settings) {
        state.userSettings = json.data.settings;
        if (!localStorage.getItem('preferred_domain') && state.userSettings.default_domain && state.userSettings.default_domain !== state.activeDomain) {
          state.activeDomain = state.userSettings.default_domain;
          applyDomainDefaults(state.activeDomain);
          loadDiscoveryFeed();
        }
      }
    })
    .catch(e => console.debug("Settings pre-fetch notice:", e));

  setTimeout(prefetchCommonFeeds, 1000);

  // Polling sidebar history every 10 seconds
  state.sidebarInterval = setInterval(loadSidebarHistory, 10000);
});

function applyDomainDefaults(domain) {
  const s = state.userSettings || {};
  if (domain === 'movies') {
    state.activeLanguage = s.movies_default_language || 'en_us';
    state.activeTimeRange = s.movies_default_time_range || '30d';
    state.activeSort = s.movies_default_sort || 'date.desc';
    state.activeTier = s.movies_default_tier !== undefined ? s.movies_default_tier : '';
  } else if (domain === 'tv') {
    state.activeLanguage = s.tv_default_language || 'en_us';
    state.activeTimeRange = s.tv_default_time_range || 'all';
    state.activeSort = s.tv_default_sort || 'popularity.desc';
    state.activeTier = s.tv_default_tier || 'major';
  } else if (domain === 'tv_classic' || domain === 'classic_tv') {
    state.activeLanguage = s.classic_tv_default_language || 'en_us';
    state.activeTimeRange = s.classic_tv_default_time_range || 'all';
    state.activeSort = s.classic_tv_default_sort || 'popularity.desc';
    state.activeTier = s.classic_tv_default_tier || 'major';
  }

  const langSelect = document.getElementById('language-select');
  if (langSelect) langSelect.value = state.activeLanguage;

  const timeSelect = document.getElementById('time-range-select');
  if (timeSelect) timeSelect.value = state.activeTimeRange;

  const sortSelect = document.getElementById('sort-select');
  if (sortSelect) sortSelect.value = state.activeSort;

  const tierSelect = document.getElementById('tier-select');
  if (tierSelect) tierSelect.value = state.activeTier;
}



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
  applyDomainDefaults(domain);

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
      timeSelect.value = state.activeTimeRange;
    }

    // Sort options for Classic TV (eliminated Release Date)
    if (sortSelect) {
      sortSelect.innerHTML = `
        <option value="popularity.desc" class="bg-surface-card text-white">🔥 Most Popular</option>
        <option value="rating.desc" class="bg-surface-card text-white">★ Highest Rated</option>
        <option value="votes.desc" class="bg-surface-card text-white">🗳️ Most Voted</option>
        <option value="title.asc" class="bg-surface-card text-white">🔤 Title (A-Z)</option>
      `;
      sortSelect.value = state.activeSort;
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
      tierSelect.value = state.activeTier;
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
      timeSelect.value = state.activeTimeRange;
    }

    if (sortSelect) {
      sortSelect.innerHTML = `
        <option value="popularity.desc" class="bg-surface-card text-white">🔥 Most Popular</option>
        <option value="rating.desc" class="bg-surface-card text-white">★ Highest Rated</option>
        <option value="votes.desc" class="bg-surface-card text-white">🗳️ Most Voted</option>
        <option value="date.desc" class="bg-surface-card text-white">📅 Air Date</option>
        <option value="title.asc" class="bg-surface-card text-white">🔤 Title (A-Z)</option>
      `;
      sortSelect.value = state.activeSort;
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
      tierSelect.value = state.activeTier;
    }
  } else {
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
      timeSelect.value = state.activeTimeRange;
    }

    if (sortSelect) {
      sortSelect.innerHTML = `
        <option value="date.desc" class="bg-surface-card text-white">📅 Release Date</option>
        <option value="popularity.desc" class="bg-surface-card text-white">🔥 Most Popular</option>
        <option value="rating.desc" class="bg-surface-card text-white">★ Highest Rated</option>
        <option value="votes.desc" class="bg-surface-card text-white">🗳️ Most Voted</option>
        <option value="title.asc" class="bg-surface-card text-white">🔤 Title (A-Z)</option>
      `;
      sortSelect.value = state.activeSort;
    }

    // Studio Tier Filter for Movies
    if (tierSelect) {
      if (tierSelect.parentElement) tierSelect.parentElement.classList.remove('hidden');
      tierSelect.innerHTML = `
        <option value="" class="bg-surface-card text-white">All Tiers</option>
        <option value="major" class="bg-surface-card text-white">🌟 Major Studio</option>
        <option value="indie" class="bg-surface-card text-white">🌱 Indie & Boutique</option>
      `;
      tierSelect.value = state.activeTier;
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

  // If user was on Settings or History, switch to Discovery tab; otherwise refresh feed
  if (state.activeTab !== 'discovery') {
    switchTab('discovery');
  } else {
    loadDiscoveryFeed();
  }
  loadSidebarHistory();
}

// Tab Switcher
function switchTab(tab) {
  state.activeTab = tab;

  const viewDiscovery = document.getElementById('view-discovery');
  const viewHistory = document.getElementById('view-history');
  const viewSettings = document.getElementById('view-settings');
  const tabBtnDiscovery = document.getElementById('tab-btn-discovery');
  const tabBtnHistory = document.getElementById('tab-btn-history');
  const tabBtnSettings = document.getElementById('tab-btn-settings');

  // Reset all view containers
  [viewDiscovery, viewHistory, viewSettings].forEach(v => {
    if (v) v.classList.add('hidden');
  });
  // Reset all tab button styles
  [tabBtnDiscovery, tabBtnHistory, tabBtnSettings].forEach(b => {
    if (b) {
      b.classList.remove('active', 'text-cyan-400');
      b.classList.add('text-slate-400');
    }
  });

  if (tab === 'discovery') {
    if (viewDiscovery) viewDiscovery.classList.remove('hidden');
    if (tabBtnDiscovery) {
      tabBtnDiscovery.classList.add('active', 'text-cyan-400');
      tabBtnDiscovery.classList.remove('text-slate-400');
    }
    loadDiscoveryFeed();
  } else if (tab === 'history') {
    if (viewHistory) viewHistory.classList.remove('hidden');
    if (tabBtnHistory) {
      tabBtnHistory.classList.add('active', 'text-cyan-400');
      tabBtnHistory.classList.remove('text-slate-400');
    }
    loadHistoryTable(state.activeDomain);
  } else if (tab === 'settings') {
    if (viewSettings) viewSettings.classList.remove('hidden');
    if (tabBtnSettings) {
      tabBtnSettings.classList.add('active', 'text-cyan-400');
      tabBtnSettings.classList.remove('text-slate-400');
    }
    loadUserSettings();
  }

  if (window.lucide) {
    lucide.createIcons();
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
      const el = document.getElementById('badge-movies-count');
      if (el) el.innerText = `${domains.movies.item_count} items`;
    }
    if (domains.tv) {
      const el = document.getElementById('badge-tv-count');
      if (el) el.innerText = `${domains.tv.show_count} shows`;
    }
    if (domains.tv_classic) {
      const el = document.getElementById('badge-tv_classic-count');
      if (el) el.innerText = `${domains.tv_classic.show_count} shows`;
    }
  } catch (err) {
    console.error("Failed to fetch domain stats:", err);
  }
}

// Client-Side High-Speed SWR Cache
const clientFeedCache = new Map();

// Render Shimmering Skeleton Placeholder Cards
function renderSkeletonGrid(grid, count = 21) {
  if (!grid) return;
  grid.innerHTML = '';
  grid.classList.remove('opacity-40', 'pointer-events-none');
  for (let i = 0; i < count; i++) {
    const card = document.createElement('div');
    card.className = 'aspect-[2/3] rounded-2xl bg-surface-card/60 border border-surface-border overflow-hidden relative shadow-lg';
    card.innerHTML = `
      <div class="w-full h-full skeleton-shimmer"></div>
      <div class="absolute bottom-0 left-0 right-0 p-3 space-y-2 bg-gradient-to-t from-surface-base/90 via-surface-base/60 to-transparent">
        <div class="h-3.5 bg-slate-700/60 rounded-md w-3/4 skeleton-shimmer"></div>
        <div class="h-2.5 bg-slate-700/40 rounded-md w-1/2 skeleton-shimmer"></div>
      </div>
    `;
    grid.appendChild(card);
  }
}

// Fetch and Render Discovery Feed
async function loadDiscoveryFeed(append = false) {
  const grid = document.getElementById('poster-grid');
  const loading = document.getElementById('grid-loading');
  const empty = document.getElementById('grid-empty');
  const loadMore = document.getElementById('load-more-container');

  const s = state.userSettings || {};
  let isHideOwned = false;
  if (state.activeDomain === 'movies') isHideOwned = Boolean(s.movies_hide_owned);
  else if (state.activeDomain === 'tv') isHideOwned = Boolean(s.tv_hide_owned);
  else if (state.activeDomain === 'tv_classic' || state.activeDomain === 'classic_tv') isHideOwned = Boolean(s.classic_tv_hide_owned);

  let url = `/api/discover?domain=${state.activeDomain}&feed=${state.activeFeed}&page=${state.page}&limit=${s.page_limit || 48}`;
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
  if (isHideOwned) {
    url += `&exclude_owned=true`;
  }

  // Instant SWR Render from Client Memory
  if (!append && clientFeedCache.has(url)) {
    const cachedEntry = clientFeedCache.get(url);
    if (Date.now() - cachedEntry.time < 300000) { // 5-minute client freshness
      state.items = cachedEntry.results;
      if (loading) loading.classList.add('hidden');
      if (empty) empty.classList.add('hidden');
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
    if (empty) empty.classList.add('hidden');
    if (grid.children.length === 0) {
      renderSkeletonGrid(grid);
    } else {
      grid.classList.add('opacity-40', 'pointer-events-none', 'transition-opacity', 'duration-150');
    }
    if (loading) loading.classList.add('hidden');
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

  state.currentDetailItem = item;

  // Ingest Button wiring
  const ingestBtn = document.getElementById('modal-ingest-btn');
  const ingestBtnLabel = document.getElementById('modal-ingest-btn-label');
  if (ingestBtn) {
    if (state.activeDomain === 'movies') {
      if (ingestBtnLabel) ingestBtnLabel.innerText = '⚡ 1-Click Ingest';
      ingestBtn.onclick = () => {
        onDetailIngestClick(item);
      };
    } else {
      if (ingestBtnLabel) ingestBtnLabel.innerText = '⚡ Ingest Episodes';
      ingestBtn.onclick = () => {
        const targetId = item.tmdb_id || item.id || (state.currentDetailItem && (state.currentDetailItem.tmdb_id || state.currentDetailItem.id));
        closeModal();
        openTVEpisodePickerModal(targetId, state.activeDomain, item.title);
      };
    }
  }

  searchBtn.onclick = () => {
    closeModal();
    openSearchModal(item.title, state.activeDomain);
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

      const stages = job.pipeline_stages || [
        { id: 'search', name: 'Search', icon: 'search', status: 'completed' },
        { id: 'debrid', name: 'Debrid', icon: 'zap', status: 'completed' },
        { id: 'idm', name: 'IDM', icon: 'download', status: job.badge_color === 'blue' ? 'in_progress' : (job.badge_color === 'green' ? 'completed' : 'pending') },
        { id: 'watcher', name: 'Watcher', icon: 'box', status: job.badge_color === 'amber' ? 'in_progress' : (job.badge_color === 'green' ? 'completed' : 'pending') },
        { id: 'plex', name: 'Plex', icon: 'check-circle', status: job.badge_color === 'green' ? 'completed' : 'pending' }
      ];

      const stagesHtml = stages.map((stg, idx) => {
        let stgClass = "bg-slate-800 text-slate-500 border-slate-700";
        let stgIcon = idx + 1;
        if (stg.status === "completed") {
          stgClass = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
          stgIcon = "✓";
        } else if (stg.status === "in_progress") {
          stgClass = "bg-cyan-500/20 text-cyan-300 border-cyan-500/40 animate-pulse font-bold";
          stgIcon = "⚡";
        } else if (stg.status === "failed") {
          stgClass = "bg-rose-500/20 text-rose-300 border-rose-500/40 font-bold";
          stgIcon = "✕";
        }
        return `
          <div class="flex-1 flex flex-col items-center gap-0.5">
            <div class="w-4 h-4 rounded-full border flex items-center justify-center font-bold text-[9px] ${stgClass}">
              ${stgIcon}
            </div>
            <span class="text-[8px] text-slate-400 truncate max-w-[36px] text-center">${stg.name}</span>
          </div>
        `;
      }).join('<div class="w-1.5 h-0.5 bg-surface-border -mt-2 shrink-0"></div>');

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
        <div class="mt-1 pt-1.5 border-t border-surface-border/40 flex items-center justify-between gap-1">
          ${stagesHtml}
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

// ============================================================================
// SETTINGS CONTROLLER & DEFAULTS PERSISTENCE
// ============================================================================

// Load User Settings from Server & Populate Form
async function loadUserSettings() {
  try {

    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const json = await res.json();
    const s = json.data?.settings || {};
    const info = json.data?.system_info || {};
    state.userSettings = s;

    // CARD 1: Movies Defaults
    const setMovLang = document.getElementById('setting-movies-language');
    if (setMovLang) setMovLang.value = s.movies_default_language || 'en_us';

    const setMovTime = document.getElementById('setting-movies-time-range');
    if (setMovTime) setMovTime.value = s.movies_default_time_range || '30d';

    const setMovSort = document.getElementById('setting-movies-sort');
    if (setMovSort) setMovSort.value = s.movies_default_sort || 'date.desc';

    const setMovTier = document.getElementById('setting-movies-tier');
    if (setMovTier) setMovTier.value = s.movies_default_tier !== undefined ? s.movies_default_tier : '';

    const setMovQ = document.getElementById('setting-movies-quality');
    if (setMovQ) setMovQ.value = s.movies_quality_preset || '1080p Web-DL';

    const setMovHide = document.getElementById('setting-movies-hide-owned');
    if (setMovHide) setMovHide.checked = Boolean(s.movies_hide_owned);

    // CARD 2: TV Series Defaults
    const setTvLang = document.getElementById('setting-tv-language');
    if (setTvLang) setTvLang.value = s.tv_default_language || 'en_us';

    const setTvTime = document.getElementById('setting-tv-time-range');
    if (setTvTime) setTvTime.value = s.tv_default_time_range || 'all';

    const setTvSort = document.getElementById('setting-tv-sort');
    if (setTvSort) setTvSort.value = s.tv_default_sort || 'popularity.desc';

    const setTvTier = document.getElementById('setting-tv-tier');
    if (setTvTier) setTvTier.value = s.tv_default_tier || 'major';

    const setTvQ = document.getElementById('setting-tv-quality');
    if (setTvQ) setTvQ.value = s.tv_quality_preset || '1080p Web-DL';

    const setTvHide = document.getElementById('setting-tv-hide-owned');
    if (setTvHide) setTvHide.checked = Boolean(s.tv_hide_owned);

    // CARD 3: Classic TV Defaults
    const setClassicLang = document.getElementById('setting-classic-language');
    if (setClassicLang) setClassicLang.value = s.classic_tv_default_language || 'en_us';

    const setClassicTime = document.getElementById('setting-classic-time-range');
    if (setClassicTime) setClassicTime.value = s.classic_tv_default_time_range || 'all';

    const setClassicSort = document.getElementById('setting-classic-sort');
    if (setClassicSort) setClassicSort.value = s.classic_tv_default_sort || 'popularity.desc';

    const setClassicTier = document.getElementById('setting-classic-tier');
    if (setClassicTier) setClassicTier.value = s.classic_tv_default_tier || 'major';

    const setClassicQ = document.getElementById('setting-classic-quality');
    if (setClassicQ) setClassicQ.value = s.classic_tv_quality_preset || '1080p Remaster';

    const setClassicHide = document.getElementById('setting-classic-hide-owned');
    if (setClassicHide) setClassicHide.checked = Boolean(s.classic_tv_hide_owned);

    // CARD 4: Global & Discord Defaults
    const setDomain = document.getElementById('setting-default-domain');
    if (setDomain) setDomain.value = s.default_domain || 'movies';

    const setLimit = document.getElementById('setting-page-limit');
    if (setLimit) setLimit.value = s.page_limit || 48;

    const setMinSeed = document.getElementById('setting-min-seeders');
    if (setMinSeed) setMinSeed.value = s.min_seeders || 3;

    const setInstant = document.getElementById('setting-prefer-instant');
    if (setInstant) setInstant.checked = s.prefer_instant_cache !== false;

    const setNotifyComp = document.getElementById('setting-notify-complete');
    if (setNotifyComp) setNotifyComp.checked = s.discord_notify_complete !== false;

    const setNotifyWatch = document.getElementById('setting-notify-watchlist');
    if (setNotifyWatch) setNotifyWatch.checked = s.discord_watchlist_alerts !== false;

    const setWeekly = document.getElementById('setting-weekly-digest');
    if (setWeekly) setWeekly.checked = s.discord_weekly_digest !== false;

    const setDigestDay = document.getElementById('setting-digest-day');
    if (setDigestDay) setDigestDay.value = s.digest_day || 'Sunday';

    const setDigestTime = document.getElementById('setting-digest-time');
    if (setDigestTime) setDigestTime.value = s.digest_time || '18:00';

    // Storage Paths
    const dirs = info.output_dirs || {};
    const dirMovies = document.getElementById('status-dir-movies');
    if (dirMovies && dirs.movies) dirMovies.innerText = dirs.movies;

    const dirTv = document.getElementById('status-dir-tv');
    if (dirTv && dirs.tv) dirTv.innerText = dirs.tv;

    const dirClassic = document.getElementById('status-dir-classic');
    if (dirClassic && dirs.tv_classic) dirClassic.innerText = dirs.tv_classic;

    // Integration Health Badges
    const ints = info.integrations || {};
    const updateBadge = (id, active) => {
      const el = document.getElementById(id);
      if (el) {
        el.className = active ? 'w-2 h-2 rounded-full bg-emerald-400' : 'w-2 h-2 rounded-full bg-rose-500';
      }
    };
    updateBadge('badge-status-tmdb', ints.tmdb);
    updateBadge('badge-status-alldebrid', ints.alldebrid);
    updateBadge('badge-status-prowlarr', ints.prowlarr);
    updateBadge('badge-status-plex', ints.plex);

  } catch (err) {
    console.error("Failed to load settings:", err);
  }
}

// Save User Settings to Server
async function saveUserSettings() {
  const payload = {
    // Global
    default_domain: document.getElementById('setting-default-domain')?.value || 'movies',
    page_limit: parseInt(document.getElementById('setting-page-limit')?.value || 48, 10),
    min_seeders: parseInt(document.getElementById('setting-min-seeders')?.value || 3, 10),
    prefer_instant_cache: Boolean(document.getElementById('setting-prefer-instant')?.checked),

    // Movies
    movies_default_language: document.getElementById('setting-movies-language')?.value || 'en_us',
    movies_default_time_range: document.getElementById('setting-movies-time-range')?.value || '30d',
    movies_default_sort: document.getElementById('setting-movies-sort')?.value || 'date.desc',
    movies_default_tier: document.getElementById('setting-movies-tier')?.value || '',
    movies_quality_preset: document.getElementById('setting-movies-quality')?.value || '1080p Web-DL',
    movies_hide_owned: Boolean(document.getElementById('setting-movies-hide-owned')?.checked),

    // TV
    tv_default_language: document.getElementById('setting-tv-language')?.value || 'en_us',
    tv_default_time_range: document.getElementById('setting-tv-time-range')?.value || 'all',
    tv_default_sort: document.getElementById('setting-tv-sort')?.value || 'popularity.desc',
    tv_default_tier: document.getElementById('setting-tv-tier')?.value || 'major',
    tv_quality_preset: document.getElementById('setting-tv-quality')?.value || '1080p Web-DL',
    tv_hide_owned: Boolean(document.getElementById('setting-tv-hide-owned')?.checked),

    // Classic TV
    classic_tv_default_language: document.getElementById('setting-classic-language')?.value || 'en_us',
    classic_tv_default_time_range: document.getElementById('setting-classic-time-range')?.value || 'all',
    classic_tv_default_sort: document.getElementById('setting-classic-sort')?.value || 'popularity.desc',
    classic_tv_default_tier: document.getElementById('setting-classic-tier')?.value || 'major',
    classic_tv_quality_preset: document.getElementById('setting-classic-quality')?.value || '1080p Remaster',
    classic_tv_hide_owned: Boolean(document.getElementById('setting-classic-hide-owned')?.checked),

    // Discord & Alerts
    discord_notify_complete: Boolean(document.getElementById('setting-notify-complete')?.checked),
    discord_watchlist_alerts: Boolean(document.getElementById('setting-notify-watchlist')?.checked),
    discord_weekly_digest: Boolean(document.getElementById('setting-weekly-digest')?.checked),
    digest_day: document.getElementById('setting-digest-day')?.value || 'Sunday',
    digest_time: document.getElementById('setting-digest-time')?.value || '18:00',
  };

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const json = await res.json();
      state.userSettings = json.data || payload;
      clientFeedCache.clear();
      localStorage.setItem('preferred_domain', payload.default_domain);
      
      // Re-apply to active domain
      applyDomainDefaults(state.activeDomain);

      showToast("✨ Settings saved successfully!");
    } else {

      showToast("⚠️ Error saving settings", "error");
    }
  } catch (err) {
    console.error("Save settings error:", err);
    showToast("⚠️ Network error saving settings", "error");
  }
}

// Reset Settings to Factory Defaults
async function resetSettingsToDefaults() {
  if (confirm("Reset all settings to factory defaults?")) {
    const defaults = {
      default_domain: "movies",
      page_limit: 48,
      min_seeders: 3,
      prefer_instant_cache: true,

      movies_default_language: "en_us",
      movies_default_time_range: "30d",
      movies_default_sort: "date.desc",
      movies_default_tier: "",
      movies_quality_preset: "1080p Web-DL",
      movies_hide_owned: false,

      tv_default_language: "en_us",
      tv_default_time_range: "all",
      tv_default_sort: "popularity.desc",
      tv_default_tier: "major",
      tv_quality_preset: "1080p Web-DL",
      tv_hide_owned: false,

      classic_tv_default_language: "en_us",
      classic_tv_default_time_range: "all",
      classic_tv_default_sort: "popularity.desc",
      classic_tv_default_tier: "major",
      classic_tv_quality_preset: "1080p Remaster",
      classic_tv_hide_owned: false,

      discord_notify_complete: true,
      discord_watchlist_alerts: true,
      discord_weekly_digest: true,
      digest_day: "Sunday",
      digest_time: "18:00"
    };

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(defaults)
      });
      if (res.ok) {
        localStorage.removeItem('preferred_language');
        localStorage.removeItem('preferred_time_range');
        localStorage.removeItem('preferred_domain');
        await loadUserSettings();
        applyDomainDefaults(state.activeDomain);
        showToast("🔄 Reset to factory defaults");
      }
    } catch (err) {
      console.error("Reset error:", err);
    }
  }
}

// Visual Toast Feedback Notification
function showToast(message, type = "success") {
  const existing = document.getElementById('toast-notification');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.id = 'toast-notification';
  const bgColor = type === 'error' ? 'bg-rose-950 border-rose-800 text-rose-200 shadow-rose-950/50' : 'bg-cyan-950 border-cyan-800 text-cyan-200 shadow-cyan-950/50';
  toast.className = `fixed bottom-6 right-6 z-50 px-5 py-3 rounded-xl border ${bgColor} shadow-2xl text-xs font-bold flex items-center gap-2 transition-all duration-300 transform translate-y-4 opacity-0`;
  toast.innerHTML = `<i data-lucide="${type === 'error' ? 'alert-circle' : 'check-circle'}" class="w-4 h-4"></i> <span>${message}</span>`;
  
  document.body.appendChild(toast);
  if (window.lucide) lucide.createIcons();

  setTimeout(() => {
    toast.classList.remove('translate-y-4', 'opacity-0');
  }, 50);

  setTimeout(() => {
    toast.classList.add('translate-y-4', 'opacity-0');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}


/* ==========================================================================
   BLOCK 5-2: SEARCH & ⚡ LIGHTNING CACHE MODAL CONTROLLER
   ========================================================================== */

function openSearchModal(initialQuery = '', domain = null, season = null, episode = null) {
  const modal = document.getElementById('search-modal');
  const input = document.getElementById('search-input');
  const clearBtn = document.getElementById('search-clear-btn');
  const seasonInput = document.getElementById('search-season');
  const episodeInput = document.getElementById('search-episode');

  if (!modal) return;

  // Set Search Domain
  state.searchDomain = domain || state.activeDomain || 'movies';
  updateSearchDomainUI(state.searchDomain);

  // Set Initial Inputs
  if (input) {
    input.value = initialQuery || '';
    if (clearBtn) {
      if (initialQuery) clearBtn.classList.remove('hidden');
      else clearBtn.classList.add('hidden');
    }
  }

  if (seasonInput) seasonInput.value = season !== null && season !== undefined ? season : '';
  if (episodeInput) episodeInput.value = episode !== null && episode !== undefined ? episode : '';

  // Open Modal
  modal.classList.remove('hidden');
  setTimeout(() => {
    modal.classList.add('open');
    if (input) input.focus();
  }, 10);

  if (window.lucide) lucide.createIcons();

  // Execute immediate search if initial query provided
  if (initialQuery && initialQuery.trim()) {
    executeSearch();
  } else {
    resetSearchUI();
  }
}

function closeSearchModal() {
  const modal = document.getElementById('search-modal');
  if (!modal) return;
  modal.classList.remove('open');
  setTimeout(() => {
    modal.classList.add('hidden');
  }, 250);
}

function clearSearchInput() {
  const input = document.getElementById('search-input');
  const clearBtn = document.getElementById('search-clear-btn');
  if (input) {
    input.value = '';
    input.focus();
  }
  if (clearBtn) clearBtn.classList.add('hidden');
  resetSearchUI();
}

function resetSearchUI() {
  state.searchResults = [];
  const container = document.getElementById('search-results-container');
  const loading = document.getElementById('search-loading');
  const empty = document.getElementById('search-empty');
  const initial = document.getElementById('search-initial');
  const countLabel = document.getElementById('search-count-label');
  const cachedBadge = document.getElementById('search-cached-count-badge');
  const plexBadge = document.getElementById('search-plex-badge');

  if (container) container.innerHTML = '';
  if (loading) loading.classList.add('hidden');
  if (empty) empty.classList.add('hidden');
  if (initial) initial.classList.remove('hidden');
  if (countLabel) countLabel.innerText = 'Enter a query to search';
  if (cachedBadge) cachedBadge.classList.add('hidden');
  if (plexBadge) plexBadge.classList.add('hidden');
}

function switchSearchDomain(domain) {
  state.searchDomain = domain;
  updateSearchDomainUI(domain);

  const input = document.getElementById('search-input');
  if (input && input.value.trim()) {
    executeSearch();
  }
}

function updateSearchDomainUI(domain) {
  const domains = ['movies', 'tv', 'tv_classic'];
  domains.forEach(d => {
    const btn = document.getElementById(`search-domain-${d}`);
    if (btn) {
      if (d === domain) {
        btn.className = 'search-domain-pill px-3 py-1 rounded-md font-semibold text-cyan-400 bg-cyan-950/80 border border-cyan-500/30 transition shadow-sm';
      } else {
        btn.className = 'search-domain-pill px-3 py-1 rounded-md font-semibold text-slate-400 hover:text-white transition';
      }
    }
  });

  const tvInputs = document.getElementById('search-tv-inputs');
  if (tvInputs) {
    if (domain === 'tv' || domain === 'tv_classic' || domain === 'classic_tv') {
      tvInputs.classList.remove('hidden');
    } else {
      tvInputs.classList.add('hidden');
    }
  }
}

function toggleSearchCacheOnly() {
  state.searchCacheOnly = !state.searchCacheOnly;
  const btn = document.getElementById('search-toggle-cached-only');
  if (btn) {
    if (state.searchCacheOnly) {
      btn.className = 'px-3 py-1.5 rounded-lg border border-emerald-500/50 bg-emerald-950/70 text-emerald-300 shadow-md shadow-emerald-950/40 flex items-center gap-1.5 transition font-bold';
    } else {
      btn.className = 'px-3 py-1.5 rounded-lg border border-surface-border bg-surface-hover text-slate-400 hover:text-white flex items-center gap-1.5 transition font-semibold';
    }
  }
  filterSearchResults();
}

async function executeSearch() {
  const input = document.getElementById('search-input');
  const clearBtn = document.getElementById('search-clear-btn');
  const loading = document.getElementById('search-loading');
  const empty = document.getElementById('search-empty');
  const initial = document.getElementById('search-initial');
  const container = document.getElementById('search-results-container');
  const seasonInput = document.getElementById('search-season');
  const episodeInput = document.getElementById('search-episode');

  const query = input ? input.value.trim() : '';
  if (!query) {
    resetSearchUI();
    return;
  }

  if (clearBtn) clearBtn.classList.remove('hidden');
  if (initial) initial.classList.add('hidden');
  if (empty) empty.classList.add('hidden');
  if (container) container.innerHTML = '';
  if (loading) loading.classList.remove('hidden');

  let url = `/api/search?query=${encodeURIComponent(query)}&domain=${encodeURIComponent(state.searchDomain)}`;
  if (seasonInput && seasonInput.value) {
    url += `&season=${encodeURIComponent(seasonInput.value.trim())}`;
  }
  if (episodeInput && episodeInput.value) {
    url += `&episode=${encodeURIComponent(episodeInput.value.trim())}`;
  }

  try {
    const res = await fetch(url);
    if (loading) loading.classList.add('hidden');

    if (!res.ok) {
      throw new Error(`Search request failed with HTTP ${res.status}`);
    }

    const payload = await res.json();
    state.searchResults = payload.results || [];

    // Update Stats Bar
    const countLabel = document.getElementById('search-count-label');
    const cachedBadge = document.getElementById('search-cached-count-badge');
    const plexBadge = document.getElementById('search-plex-badge');

    if (countLabel) {
      countLabel.innerText = `Found ${payload.count || state.searchResults.length} releases for "${query}"`;
    }

    if (cachedBadge) {
      cachedBadge.innerText = `⚡ ${payload.cached_count || 0} Instant Cached`;
      cachedBadge.classList.remove('hidden');
    }

    if (plexBadge) {
      if (payload.library_status?.in_library) {
        plexBadge.classList.remove('hidden');
      } else {
        plexBadge.classList.add('hidden');
      }
    }

    filterSearchResults();

  } catch (err) {
    console.error("Search execution failed:", err);
    if (loading) loading.classList.add('hidden');
    if (empty) {
      empty.classList.remove('hidden');
      empty.querySelector('p').innerText = 'Search failed or timed out';
    }
    showToast("Indexer search failed. Please try again.", "error");
  }
}

function filterSearchResults() {
  const qualitySelect = document.getElementById('search-quality-filter');
  const qualityFilter = qualitySelect ? qualitySelect.value : '';

  let filtered = [...state.searchResults];

  if (state.searchCacheOnly) {
    filtered = filtered.filter(item => item.cached === true);
  }

  if (qualityFilter) {
    filtered = filtered.filter(item => (item.resolution || '').toLowerCase() === qualityFilter.toLowerCase());
  }

  renderSearchResults(filtered);
}

function renderSearchResults(results) {
  const container = document.getElementById('search-results-container');
  const empty = document.getElementById('search-empty');
  const initial = document.getElementById('search-initial');

  if (!container) return;
  if (initial) initial.classList.add('hidden');

  if (!results || results.length === 0) {
    container.innerHTML = '';
    if (empty) empty.classList.remove('hidden');
    return;
  }

  if (empty) empty.classList.add('hidden');
  container.innerHTML = '';

  results.forEach(item => {
    const card = document.createElement('div');
    const isCached = item.cached === true;
    
    card.className = `release-row ${isCached ? 'cached-row bg-surface-card/90' : 'bg-surface-card/60'} border border-surface-border rounded-xl p-3.5 sm:p-4 flex flex-col md:flex-row md:items-center justify-between gap-3.5 shadow-lg`;

    // ⚡ Lightning badge vs Uncached badge
    const badgeHtml = isCached 
      ? `<span class="lightning-cache-tag px-2.5 py-1 rounded-lg text-xs font-extrabold flex items-center gap-1.5 shrink-0 shadow-md">
           <i data-lucide="zap" class="w-3.5 h-3.5 fill-emerald-400 text-emerald-400"></i>
           <span>⚡ Lightning (Instant Cache)</span>
         </span>`
      : `<span class="uncached-tag px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 shrink-0">
           <i data-lucide="clock" class="w-3.5 h-3.5 text-amber-400"></i>
           <span>⏳ Uncached (P2P)</span>
         </span>`;

    // Metadata Spec Pills
    const qualityPill = item.quality_label 
      ? `<span class="px-2 py-0.5 rounded-md bg-blue-950/70 text-blue-300 border border-blue-500/30 text-[11px] font-bold">${escapeHtml(item.quality_label)}</span>`
      : (item.resolution && item.resolution !== 'Unknown' ? `<span class="px-2 py-0.5 rounded-md bg-blue-950/70 text-blue-300 border border-blue-500/30 text-[11px] font-bold">${escapeHtml(item.resolution)}</span>` : '');

    const hdrPill = item.hdr 
      ? `<span class="px-2 py-0.5 rounded-md bg-amber-950/70 text-amber-300 border border-amber-500/30 text-[11px] font-bold">${escapeHtml(item.hdr)}</span>` 
      : '';

    const audioPill = item.audio 
      ? `<span class="px-2 py-0.5 rounded-md bg-purple-950/70 text-purple-300 border border-purple-500/30 text-[11px] font-semibold flex items-center gap-1"><i data-lucide="volume-2" class="w-3 h-3 text-purple-400"></i><span>${escapeHtml(item.audio)}</span></span>` 
      : '';

    const codecPill = item.codec 
      ? `<span class="px-2 py-0.5 rounded-md bg-slate-800 text-slate-300 border border-slate-700 text-[11px] font-medium">${escapeHtml(item.codec)}</span>` 
      : '';

    const groupPill = item.release_group 
      ? `<span class="px-2 py-0.5 rounded-md bg-slate-900/90 text-cyan-400 border border-cyan-500/20 text-[11px] font-mono font-bold">-${escapeHtml(item.release_group)}</span>` 
      : '';

    // Seeders Badge Color
    const seeders = item.seeders || 0;
    const seedersClass = seeders >= 25 
      ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/30' 
      : (seeders >= 5 ? 'bg-blue-950/80 text-blue-300 border-blue-500/30' : 'bg-amber-950/80 text-amber-300 border-amber-500/30');

    card.innerHTML = `
      <div class="flex-1 flex flex-col gap-2 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          ${badgeHtml}
          ${qualityPill}
          ${hdrPill}
          ${audioPill}
          ${codecPill}
          ${groupPill}
        </div>
        <div class="font-bold text-slate-100 text-xs sm:text-sm tracking-tight break-all leading-snug">
          ${escapeHtml(item.title)}
        </div>
      </div>

      <div class="flex items-center justify-between md:justify-end gap-3 sm:gap-4 shrink-0 pt-2 md:pt-0 border-t md:border-t-0 border-surface-border/60">
        <div class="flex items-center gap-2 text-xs">
          <span class="font-black text-slate-200">${item.formatted_size || '0 MB'}</span>
          <span class="px-2 py-0.5 rounded-md border text-[11px] font-bold flex items-center gap-1 ${seedersClass}">
            <i data-lucide="users" class="w-3 h-3"></i>
            <span>${seeders} seeds</span>
          </span>
          <span class="text-[10px] uppercase font-bold text-slate-400 bg-surface-base/90 px-2 py-0.5 rounded border border-surface-border">
            ${escapeHtml(item.indexer || 'Tracker')}
          </span>
        </div>

        <button onclick="onSearchReleaseClick('${item.reference_id}', '${escapeJs(item.title)}', ${isCached})" class="px-4 py-2 rounded-xl ${isCached ? 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-600 hover:from-emerald-400 hover:to-cyan-500 text-white font-extrabold shadow-lg shadow-emerald-500/20' : 'bg-surface-hover hover:bg-slate-700 text-slate-200 border border-surface-border font-bold'} text-xs flex items-center gap-1.5 transition active:scale-95 shrink-0">
          <i data-lucide="${isCached ? 'zap' : 'download'}" class="w-3.5 h-3.5 ${isCached ? 'fill-white' : ''}"></i>
          <span>${isCached ? '⚡ 1-Click Grab' : 'Enqueue'}</span>
        </button>
      </div>
    `;

    container.appendChild(card);
  });

  if (window.lucide) lucide.createIcons();
}

async function onDetailIngestClick(item) {
  const target = item || state.currentDetailItem;
  if (!target) return;
  showToast(`⚡ Resolving 1-click grab for "${target.title}"...`, 'info');
  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: target.title,
        domain: state.activeDomain,
        tmdb_id: target.tmdb_id
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`⚡ Successfully queued in IDM: ${target.title}`, 'success');
      closeModal();
      setTimeout(loadSidebarHistory, 1500);
    } else {
      showIngestDiagnosticModal(target, data.error);
    }
  } catch (err) {
    console.error("1-click detail ingest error:", err);
    showToast("Failed to queue download.", "error");
  }
}

function showIngestDiagnosticModal(item, errorMsg) {
  const modal = document.getElementById('ingest-diag-modal');
  const titleEl = document.getElementById('diag-modal-media-title');
  const explEl = document.getElementById('diag-modal-explanation');
  if (!modal) {
    showToast(`Ingest failed: ${errorMsg || 'No matching release found'}`, 'error');
    return;
  }

  if (titleEl) titleEl.innerText = `${item.title || 'Media Title'} ${item.year ? `(${item.year})` : ''}`;
  if (explEl) {
    explEl.innerText = errorMsg || 'This title is an upcoming theatrical release or currently in theatrical exclusivity. No high-quality digital releases or instant cached magnets currently exist on indexers.';
  }

  state.diagCurrentItem = item;
  modal.classList.remove('hidden');
  setTimeout(() => modal.classList.add('open'), 10);
  if (window.lucide) lucide.createIcons();
}

function closeIngestDiagnosticModal() {
  const modal = document.getElementById('ingest-diag-modal');
  if (modal) {
    modal.classList.remove('open');
    setTimeout(() => modal.classList.add('hidden'), 200);
  }
}

function onDiagSearchClick() {
  const item = state.diagCurrentItem;
  closeIngestDiagnosticModal();
  if (item) {
    closeModal();
    openSearchModal(item.title, state.activeDomain);
  }
}

async function onSearchReleaseClick(refId, title, isCached) {
  showToast(`⚡ Queuing release to IDM: "${title.substring(0, 40)}..."`, 'info');
  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference_id: refId,
        title: title,
        domain: state.searchDomain
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`⚡ Ingestion queued in IDM: ${title.substring(0, 40)}...`, 'success');
      setTimeout(loadSidebarHistory, 1500);
    } else {
      showToast(`Download queue failed: ${data.error || 'Unknown error'}`, 'error');
    }
  } catch (err) {
    console.error("Search release grab error:", err);
    showToast("Failed to queue download.", "error");
  }
}

// ==========================================
// TV / CLASSIC TV EPISODE PICKER MODAL
// ==========================================

async function openTVEpisodePickerModal(tmdbId, domain, fallbackTitle) {
  const modal = document.getElementById('tv-ingest-modal');
  const loading = document.getElementById('tv-ingest-loading');
  const checklist = document.getElementById('tv-episodes-checklist');
  const tabs = document.getElementById('tv-season-tabs');
  const titleEl = document.getElementById('tv-ingest-title');
  const domainBadge = document.getElementById('tv-ingest-domain-badge');
  const summaryEl = document.getElementById('tv-ingest-summary');

  if (!modal) return;

  modal.classList.remove('hidden');
  setTimeout(() => modal.classList.add('open'), 10);

  if (loading) loading.classList.remove('hidden');
  if (checklist) checklist.innerHTML = '';
  if (tabs) tabs.innerHTML = '';
  if (titleEl) titleEl.innerText = fallbackTitle || 'TV Series';
  if (domainBadge) domainBadge.innerText = domain === 'tv_classic' ? 'Classic TV' : 'TV Series';
  state.selectedTVEpisodes.clear();
  updateSelectedCountLabel();

  if (!tmdbId) {
    if (loading) loading.classList.add('hidden');
    if (checklist) checklist.innerHTML = '<div class="p-8 text-center text-amber-400 text-sm">Unable to determine TMDb ID for this title. Please try searching for it directly.</div>';
    return;
  }

  try {
    const res = await fetch(`/api/tv/series-manifest?tmdb_id=${tmdbId}&domain=${domain || state.activeDomain}`);
    const data = await res.json();

    if (loading) loading.classList.add('hidden');

    if (!data.ok) {
      if (checklist) checklist.innerHTML = `<div class="p-8 text-center text-slate-400 text-sm">${escapeHtml(data.error || 'Could not load series breakdown.')}</div>`;
      return;
    }

    state.tvManifest = data;
    renderTVManifest(data);
  } catch (err) {
    console.error("TV series manifest error:", err);
    if (loading) loading.classList.add('hidden');
    if (checklist) checklist.innerHTML = '<div class="p-8 text-center text-rose-400 text-sm">Failed to connect to server for TV series manifest.</div>';
  }
}

function closeTVEpisodePickerModal() {
  const modal = document.getElementById('tv-ingest-modal');
  if (modal) {
    modal.classList.remove('open');
    setTimeout(() => modal.classList.add('hidden'), 200);
  }
}

function renderTVManifest(manifest) {
  const titleEl = document.getElementById('tv-ingest-title');
  const yearEl = document.getElementById('tv-ingest-year');
  const summaryEl = document.getElementById('tv-ingest-summary');
  const posterImg = document.getElementById('tv-ingest-poster-img');
  const posterWrap = document.getElementById('tv-ingest-poster-wrap');
  const tabs = document.getElementById('tv-season-tabs');

  if (titleEl) titleEl.innerText = manifest.title || 'TV Series';
  if (yearEl) yearEl.innerText = manifest.year || '';
  if (summaryEl) {
    summaryEl.innerText = `${manifest.total_owned_episodes || 0} / ${manifest.total_episodes || 0} Episodes Owned in Plex (${manifest.total_missing_episodes || 0} missing)`;
  }

  if (posterImg && manifest.poster_url) {
    posterImg.src = manifest.poster_url;
    if (posterWrap) posterWrap.classList.remove('hidden');
  }

  // Render Season Tabs
  if (tabs) {
    tabs.innerHTML = '';
    const seasons = manifest.seasons || [];
    if (seasons.length > 0) {
      state.activeTVSeason = seasons[0].season_number;
    }

    seasons.forEach((s) => {
      const btn = document.createElement('button');
      const isActive = s.season_number === state.activeTVSeason;
      const isComplete = s.missing_count === 0;
      btn.id = `tv-season-tab-${s.season_number}`;
      btn.className = `px-3 py-1.5 rounded-xl font-bold text-xs transition flex items-center gap-1.5 shrink-0 ${
        isActive
          ? 'bg-cyan-500 text-white shadow-md shadow-cyan-500/25'
          : 'bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border'
      }`;
      btn.innerHTML = `
        <span>Season ${s.season_number}</span>
        <span class="text-[10px] px-1.5 py-0.2 rounded-full ${isComplete ? 'bg-emerald-500/30 text-emerald-300' : 'bg-slate-800 text-slate-400'} font-black">${s.owned_count}/${s.episode_count}</span>
      `;
      btn.onclick = () => switchTVSeasonTab(s.season_number);
      tabs.appendChild(btn);
    });
  }

  renderActiveSeasonEpisodes();
}

function switchTVSeasonTab(seasonNum) {
  state.activeTVSeason = seasonNum;
  if (!state.tvManifest) return;

  // Update active styling on tabs
  (state.tvManifest.seasons || []).forEach((s) => {
    const tab = document.getElementById(`tv-season-tab-${s.season_number}`);
    if (tab) {
      const isActive = s.season_number === seasonNum;
      tab.className = `px-3 py-1.5 rounded-xl font-bold text-xs transition flex items-center gap-1.5 shrink-0 ${
        isActive
          ? 'bg-cyan-500 text-white shadow-md shadow-cyan-500/25'
          : 'bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border'
      }`;
    }
  });

  const packBtnLabel = document.getElementById('tv-ingest-pack-label');
  if (packBtnLabel) packBtnLabel.innerText = `⚡ Ingest Season ${seasonNum} Pack`;

  renderActiveSeasonEpisodes();
}

function renderActiveSeasonEpisodes() {
  const checklist = document.getElementById('tv-episodes-checklist');
  if (!checklist || !state.tvManifest) return;

  const currentSeason = (state.tvManifest.seasons || []).find((s) => s.season_number === state.activeTVSeason);
  checklist.innerHTML = '';

  if (!currentSeason || !currentSeason.episodes || currentSeason.episodes.length === 0) {
    checklist.innerHTML = '<div class="p-8 text-center text-slate-400 text-sm">No episodes listed for this season.</div>';
    return;
  }

  currentSeason.episodes.forEach((ep) => {
    const epKey = `${state.activeTVSeason}_${ep.episode_number}`;
    const isOwned = ep.owned || false;
    const isSelected = state.selectedTVEpisodes.has(epKey);

    const row = document.createElement('div');
    row.className = `p-3 rounded-xl border transition flex items-center justify-between gap-3 ${
      isOwned
        ? 'bg-emerald-950/20 border-emerald-500/30 text-slate-300 opacity-80'
        : isSelected
        ? 'bg-cyan-950/40 border-cyan-500/50 text-white'
        : 'bg-surface-hover/60 border-surface-border hover:border-slate-600 text-slate-200'
    }`;

    row.innerHTML = `
      <div class="flex items-center gap-3 min-w-0">
        <input type="checkbox" ${isOwned ? 'disabled checked' : isSelected ? 'checked' : ''} onchange="toggleEpisodeCheckbox(${state.activeTVSeason}, ${ep.episode_number})" class="w-4 h-4 rounded text-cyan-500 border-surface-border focus:ring-0 cursor-pointer ${isOwned ? 'opacity-50 cursor-not-allowed' : ''}">
        
        <span class="text-xs font-black px-2 py-0.5 rounded bg-surface-card border border-surface-border shrink-0 text-slate-300">
          E${String(ep.episode_number).padStart(2, '0')}
        </span>

        <div class="min-w-0">
          <p class="text-xs sm:text-sm font-bold truncate">${escapeHtml(ep.title || `Episode ${ep.episode_number}`)}</p>
          <p class="text-[11px] text-slate-400 truncate">${ep.air_date ? `Aired: ${ep.air_date}` : ''} ${ep.runtime_min ? `• ${ep.runtime_min}m` : ''}</p>
        </div>
      </div>

      <div class="shrink-0 flex items-center gap-2">
        ${
          isOwned
            ? '<span class="text-[11px] font-bold px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1"><i data-lucide="check" class="w-3 h-3"></i> In Plex</span>'
            : '<span class="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-cyan-950/60 text-cyan-300 border border-cyan-500/30">⚡ Ready</span>'
        }
      </div>
    `;

    checklist.appendChild(row);
  });

  if (window.lucide) lucide.createIcons();
  updateSelectedCountLabel();
}

function toggleEpisodeCheckbox(seasonNum, epNum) {
  const epKey = `${seasonNum}_${epNum}`;
  if (state.selectedTVEpisodes.has(epKey)) {
    state.selectedTVEpisodes.delete(epKey);
  } else {
    state.selectedTVEpisodes.add(epKey);
  }
  renderActiveSeasonEpisodes();
}

function selectAllMissingEpisodes() {
  if (!state.tvManifest) return;
  const currentSeason = (state.tvManifest.seasons || []).find((s) => s.season_number === state.activeTVSeason);
  if (!currentSeason) return;

  currentSeason.episodes.forEach((ep) => {
    if (!ep.owned) {
      state.selectedTVEpisodes.add(`${state.activeTVSeason}_${ep.episode_number}`);
    }
  });
  renderActiveSeasonEpisodes();
}

function deselectAllEpisodes() {
  if (!state.tvManifest) return;
  const currentSeason = (state.tvManifest.seasons || []).find((s) => s.season_number === state.activeTVSeason);
  if (!currentSeason) return;

  currentSeason.episodes.forEach((ep) => {
    state.selectedTVEpisodes.delete(`${state.activeTVSeason}_${ep.episode_number}`);
  });
  renderActiveSeasonEpisodes();
}

function updateSelectedCountLabel() {
  const label = document.getElementById('tv-selected-count-label');
  const btn = document.getElementById('btn-download-selected-episodes');
  const count = state.selectedTVEpisodes.size;

  if (label) label.innerText = `${count} episode${count === 1 ? '' : 's'} selected`;
  if (btn) btn.disabled = count === 0;
}

async function downloadSelectedTVEpisodes() {
  if (!state.tvManifest || state.selectedTVEpisodes.size === 0) return;

  const episodesInSeason = [];
  state.selectedTVEpisodes.forEach((epKey) => {
    const [sStr, epStr] = epKey.split('_');
    if (parseInt(sStr) === state.activeTVSeason) {
      episodesInSeason.push(parseInt(epStr));
    }
  });

  if (episodesInSeason.length === 0) {
    showToast("No episodes selected in the active season.", "warning");
    return;
  }

  showToast(`⚡ Ingesting ${episodesInSeason.length} episodes of ${state.tvManifest.title} Season ${state.activeTVSeason}...`, "info");
  closeTVEpisodePickerModal();

  try {
    const res = await fetch('/api/tv/ingest-episodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tmdb_id: state.tvManifest.tmdb_id,
        title: state.tvManifest.title,
        domain: state.tvManifest.domain || state.activeDomain,
        season: state.activeTVSeason,
        episode_numbers: episodesInSeason,
        pack_mode: false
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`⚡ Queued: ${state.tvManifest.title} S${String(state.activeTVSeason).padStart(2, '0')}`, "success");
      setTimeout(loadSidebarHistory, 1500);
    } else {
      showToast(`TV Ingest failed: ${data.error || 'Unknown error'}`, "error");
    }
  } catch (err) {
    console.error("TV episode download error:", err);
    showToast("Failed to queue TV episodes.", "error");
  }
}

async function onIngestActiveSeasonPack() {
  if (!state.tvManifest) return;
  showToast(`⚡ Ingesting Complete Season ${state.activeTVSeason} Pack for ${state.tvManifest.title}...`, "info");
  closeTVEpisodePickerModal();

  try {
    const res = await fetch('/api/tv/ingest-episodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tmdb_id: state.tvManifest.tmdb_id,
        title: state.tvManifest.title,
        domain: state.tvManifest.domain || state.activeDomain,
        season: state.activeTVSeason,
        pack_mode: true
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`⚡ Queued: ${state.tvManifest.title} Season ${state.activeTVSeason} Pack`, "success");
      setTimeout(loadSidebarHistory, 1500);
    } else {
      showToast(`TV Season Pack ingest failed: ${data.error || 'Unknown error'}`, "error");
    }
  } catch (err) {
    console.error("TV season pack download error:", err);
    showToast("Failed to queue TV season pack.", "error");
  }
}

// ==========================================
// SSE LIVE TELEMETRY STREAM
// ==========================================

function initSSETelemetry() {
  try {
    const evtSource = new EventSource('/api/stream');
    evtSource.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'telemetry') {
          updateTelemetryUI(msg.payload);
        }
      } catch (err) {}
    };
    evtSource.onerror = () => {
      const dot = document.getElementById('telemetry-status-dot');
      const text = document.getElementById('telemetry-status-text');
      if (dot) dot.className = 'w-2 h-2 rounded-full bg-amber-400';
      if (text) text.innerText = 'Reconnecting...';
    };
  } catch (err) {
    console.debug("SSE initialization notice:", err);
  }
}

function updateTelemetryUI(payload) {
  const dot = document.getElementById('telemetry-status-dot');
  const text = document.getElementById('telemetry-status-text');
  const count = document.getElementById('telemetry-active-count');
  const speedBadge = document.getElementById('telemetry-speed-badge');
  const speedVal = document.getElementById('telemetry-speed-val');

  if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
  if (text) text.innerText = payload.engine_status === 'online' ? 'Engine Online' : 'Engine Idle';

  const activeCount = payload.active_downloads || 0;
  if (count) {
    count.innerText = activeCount === 0 ? '0 active downloads' : `${activeCount} active download${activeCount > 1 ? 's' : ''}`;
  }

  if (speedBadge) {
    if (activeCount > 0) {
      speedBadge.classList.remove('hidden');
      if (speedVal) speedVal.innerText = 'IDM Downloading';
    } else {
      speedBadge.classList.add('hidden');
    }
  }
}

// Global Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    openSearchModal();
  } else if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
    e.preventDefault();
    openSearchModal();
  } else if (e.key === 'Escape') {
    const tvModal = document.getElementById('tv-ingest-modal');
    if (tvModal && tvModal.classList.contains('open')) {
      closeTVEpisodePickerModal();
      return;
    }
    const searchModal = document.getElementById('search-modal');
    if (searchModal && searchModal.classList.contains('open')) {
      closeSearchModal();
    } else {
      closeModal();
    }
  }
});

// Helper for escaping HTML text safely
function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Helper for escaping strings safely in JS strings
function escapeJs(str) {
  if (!str) return '';
  return str.replace(/'/g, "\\'").replace(/"/g, '\\"');
}





