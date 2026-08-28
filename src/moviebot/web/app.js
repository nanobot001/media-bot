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

  // Load cached settings immediately for instant frame-0 customized rendering
  try {
    const cachedStr = localStorage.getItem('cached_user_settings');
    if (cachedStr) {
      state.userSettings = JSON.parse(cachedStr);
    }
  } catch (e) {}

  const initialDomain = localStorage.getItem('preferred_domain') || (state.userSettings && state.userSettings.default_domain) || state.activeDomain;
  state.activeDomain = initialDomain;

  // Apply default domain configurations immediately with user settings
  applyDomainDefaults(state.activeDomain);

  // Single clean feed load on startup
  loadDiscoveryFeed(false);
  fetchDomainStats();
  loadSidebarHistory();
  initSSETelemetry();
  setTimeout(refreshPrewarmRuntimeStatus, 1000);
  setInterval(refreshPrewarmRuntimeStatus, 30000);

  // Fetch persisted settings quietly in background without re-triggering discovery
  fetch('/api/settings')
    .then(res => res.ok ? res.json() : null)
    .then(json => {
      if (json && json.data?.settings) {
        state.userSettings = json.data.settings;
        try {
          localStorage.setItem('cached_user_settings', JSON.stringify(state.userSettings));
        } catch (e) {}
      }
    })
    .catch(e => console.debug("Settings pre-fetch notice:", e));
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
    refreshHistorySubtabBadges();
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

function updateActiveFiltersBar() {
  const bar = document.getElementById('active-filters-bar');
  const container = document.getElementById('active-filter-chips');
  if (!bar || !container) return;

  const chips = [];

  // Genre Chip
  if (state.activeGenre) {
    chips.push({
      label: `Genre: ${state.activeGenre}`,
      onRemove: () => {
        state.activeGenre = '';
        const el = document.getElementById('genre-select');
        if (el) el.value = '';
        loadDiscoveryFeed();
      }
    });
  }

  // Tier Chip
  if (state.activeTier) {
    const tierName = state.activeTier === 'major' ? '🌟 Major Studio' : (state.activeTier === 'indie' ? '🌱 Indie' : state.activeTier);
    chips.push({
      label: `Tier: ${tierName}`,
      onRemove: () => {
        state.activeTier = '';
        const el = document.getElementById('tier-select');
        if (el) el.value = '';
        loadDiscoveryFeed();
      }
    });
  }

  // Time Range / Era Chip (if not default)
  const defaultTime = state.activeDomain === 'movies' ? '30d' : 'all';
  if (state.activeTimeRange && state.activeTimeRange !== defaultTime && state.activeTimeRange !== 'all') {
    chips.push({
      label: `Era: ${state.activeTimeRange}`,
      onRemove: () => {
        state.activeTimeRange = defaultTime;
        const el = document.getElementById('time-range-select');
        if (el) el.value = defaultTime;
        loadDiscoveryFeed();
      }
    });
  }

  // Language Chip (if not en_us)
  if (state.activeLanguage && state.activeLanguage !== 'en_us') {
    chips.push({
      label: `Lang: ${state.activeLanguage.toUpperCase()}`,
      onRemove: () => {
        state.activeLanguage = 'en_us';
        const el = document.getElementById('language-select');
        if (el) el.value = 'en_us';
        loadDiscoveryFeed();
      }
    });
  }

  if (chips.length === 0) {
    bar.classList.add('hidden');
    container.innerHTML = '';
    return;
  }

  bar.classList.remove('hidden');
  container.innerHTML = '';
  chips.forEach((c, idx) => {
    const chip = document.createElement('span');
    chip.className = 'filter-chip px-2.5 py-0.5 rounded-full text-[11px] font-semibold flex items-center gap-1 shadow-sm';
    chip.innerHTML = `<span>${escapeHtml(c.label)}</span><button id="chip-rm-${idx}" class="text-slate-400 hover:text-white font-black ml-1"><i data-lucide="x" class="w-3 h-3"></i></button>`;
    container.appendChild(chip);
    const rmBtn = chip.querySelector(`#chip-rm-${idx}`);
    if (rmBtn) rmBtn.onclick = c.onRemove;
  });

  if (window.lucide) lucide.createIcons();
}

function resetAllFilters() {
  state.activeGenre = '';
  state.activeTier = '';
  state.activeTimeRange = state.activeDomain === 'movies' ? '30d' : 'all';
  state.activeLanguage = 'en_us';

  const g = document.getElementById('genre-select');
  if (g) g.value = '';
  const t = document.getElementById('tier-select');
  if (t) t.value = '';
  const tr = document.getElementById('time-range-select');
  if (tr) tr.value = state.activeTimeRange;
  const l = document.getElementById('language-select');
  if (l) l.value = 'en_us';

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
  updateActiveFiltersBar();
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
    const browserStreamReady = item.browser_stream_ready === true;
    const externalStreamReady = item.instant_stream_status === 'external_ready';

    card.innerHTML = `
      <div class="relative aspect-[2/3] w-full overflow-hidden bg-slate-900">
        <img src="${posterUrl}" alt="${escapeHtml(item.title)}" onerror="this.onerror=null; this.parentElement.innerHTML='<div class=\\'w-full h-full flex flex-col items-center justify-center p-3 text-center bg-slate-900 border border-surface-border\\'><i data-lucide=\\'film\\' class=\\'w-8 h-8 text-slate-700 mb-2\\'></i><span class=\\'text-[10px] text-slate-400 font-bold line-clamp-2\\'>${escapeJs(item.title)}</span></div>'; if(window.lucide) lucide.createIcons();" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy">
        
        <!-- Top Badges Overlay -->
        <div class="absolute top-2.5 inset-x-2.5 flex items-center justify-between pointer-events-none">
          <span class="px-2 py-0.5 rounded-md bg-black/70 backdrop-blur-md text-amber-400 text-xs font-extrabold flex items-center gap-1 border border-white/10 shadow-md">
            <i data-lucide="star" class="w-3 h-3 fill-amber-400"></i> ${rating}
          </span>

          <div class="flex items-center gap-1.5 pointer-events-auto">
            ${inLibrary ? `
              <span class="px-2 py-0.5 rounded-md bg-emerald-950/90 backdrop-blur-md text-emerald-300 border border-emerald-500/50 text-[10px] font-black shadow-lg flex items-center gap-1">
                <i data-lucide="check" class="w-3 h-3 text-emerald-400"></i> IN PLEX
              </span>
            ` : (browserStreamReady ? `
              <span class="lightning-badge p-1 rounded-full cursor-help flex items-center justify-center shadow-lg" title="⚡ 1-Click Ingest Ready">
                <i data-lucide="zap" class="w-3.5 h-3.5 fill-emerald-400 text-emerald-400"></i>
              </span>
            ` : (externalStreamReady ? `
              <span class="p-1 rounded-full cursor-help flex items-center justify-center shadow-lg text-indigo-300" title="Cached for download; external player recommended">
                <i data-lucide="monitor-play" class="w-3.5 h-3.5"></i>
              </span>
            ` : ''))}
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
function setDetailStreamButtonState(item) {
  const button = document.getElementById('modal-stream-btn');
  const label = document.getElementById('modal-stream-btn-label');
  if (!button) return;

  const browserReady = item?.browser_stream_ready === true;
  const externalReady = item?.instant_stream_status === 'external_ready';
  const enabled = browserReady || externalReady;

  button.disabled = !enabled;
  button.setAttribute('aria-disabled', String(!enabled));
  button.title = browserReady
    ? 'Stream instantly in the browser'
    : (externalReady
      ? 'Open the verified cached release in an external player'
      : 'Searching for a verified browser-streamable release');
  button.classList.toggle('opacity-50', !enabled);
  button.classList.toggle('cursor-not-allowed', !enabled);
  button.classList.toggle('bg-gradient-to-r', enabled);
  button.classList.toggle('from-cyan-500', enabled);
  button.classList.toggle('to-blue-600', enabled);
  button.classList.toggle('hover:from-cyan-400', enabled);
  button.classList.toggle('hover:to-blue-500', enabled);
  button.classList.toggle('bg-slate-800', !enabled);
  button.classList.toggle('text-slate-500', !enabled);
  button.classList.toggle('border', !enabled);
  button.classList.toggle('border-slate-700/60', !enabled);

  if (label) {
    label.innerText = browserReady
      ? '▶️ Stream Now'
      : (externalReady ? '🚀 Open External' : '⏳ Searching for Cache');
  }
}

function setDetailPrepareStreamButtonState(item) {
  const button = document.getElementById('modal-prepare-stream-btn');
  const label = document.getElementById('modal-prepare-stream-btn-label');
  if (!button) return;

  const browserReady = item?.browser_stream_ready === true;
  const prepareStatus = String(item?.stream_prepare_status || '').toLowerCase();
  const preparing = ['queued', 'downloading', 'uploading', 'processing', 'verifying'].includes(prepareStatus);
  const failed = prepareStatus === 'failed';
  const hidden = browserReady;

  button.classList.toggle('hidden', hidden);
  button.disabled = preparing;
  button.setAttribute('aria-disabled', String(preparing));
  button.classList.toggle('opacity-60', preparing);
  button.classList.toggle('cursor-wait', preparing);
  button.title = preparing
    ? 'AllDebrid is preparing the selected browser-compatible release'
    : 'Find and cache an exact MP4, H.264, AAC/MP3 browser copy';

  if (label) {
    label.innerText = preparing
      ? '⏳ Preparing Browser Copy'
      : (failed ? '↻ Retry Browser Copy' : '☁ Cache Browser Copy');
  }
}

function renderDetailStreamCandidates(item) {
  const container = document.getElementById('modal-stream-candidates');
  if (!container) return;

  const browserCandidate = item?.browser_stream_candidate;
  const downloadCandidate = item?.download_candidate;
  if (!browserCandidate && !downloadCandidate) {
    container.innerHTML = '';
    container.classList.add('hidden');
    return;
  }

  const renderCandidate = (candidate, role) => {
    if (!candidate) return '';
    const isBrowser = role === 'browser';
    const metadata = [
      candidate.container && String(candidate.container).toUpperCase(),
      candidate.video_codec,
      candidate.audio_codec,
      candidate.channels,
      candidate.resolution,
      candidate.formatted_size
    ].filter(Boolean).map(value => escapeHtml(String(value))).join(' · ');
    const verification = isBrowser
      ? `<div class="text-[11px] text-emerald-300 mt-1">Verified ${formatESTTime(candidate.verified_at)} · ${escapeHtml(candidate.verification_source || 'actual file')}</div>`
      : '<div class="text-[11px] text-slate-400 mt-1">Provider cache available for download</div>';
    const badge = isBrowser ? 'USED BY STREAM NOW' : 'DOWNLOAD COPY';
    const badgeClass = isBrowser
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : 'bg-slate-700/60 text-slate-300 border-slate-600';
    return `
      <div class="rounded-lg border border-surface-border bg-slate-950/45 p-3 min-w-0">
        <div class="flex items-center justify-between gap-2 mb-1">
          <span class="text-[10px] uppercase tracking-wider font-black text-slate-400">${isBrowser ? 'Browser stream copy' : 'Download copy'}</span>
          <span class="text-[9px] px-1.5 py-0.5 rounded border ${badgeClass} font-black whitespace-nowrap">${badge}</span>
        </div>
        <div class="text-xs text-white font-semibold break-words">${escapeHtml(candidate.release_title || 'Unknown release')}</div>
        <div class="text-[11px] text-cyan-200/80 mt-1">${metadata || 'Media details unavailable'}</div>
        ${verification}
      </div>`;
  };

  container.innerHTML = `
    <div class="rounded-xl border border-cyan-500/20 bg-slate-900/65 p-3">
      <div class="flex items-center gap-2 mb-2">
        <i data-lucide="scan-search" class="w-4 h-4 text-cyan-300"></i>
        <span class="text-xs uppercase tracking-wider font-black text-cyan-200">Selected copies</span>
      </div>
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-2">
        ${renderCandidate(browserCandidate, 'browser')}
        ${renderCandidate(downloadCandidate, 'download')}
      </div>
    </div>`;
  container.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}

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

  // Reset modal fields
  title.innerText = item.title || 'Loading...';
  tagline.innerText = item.tagline || '';
  rating.innerText = item.vote_average ? item.vote_average.toFixed(1) : (item.rating || 'N/A');
  year.innerText = item.year || (item.release_date ? item.release_date.substring(0, 4) : '');
  runtime.innerText = item.runtime_min ? `${item.runtime_min}m` : (item.number_of_seasons ? `${item.number_of_seasons} Seasons` : '');
  status.innerText = item.status || (item.available_now ? 'Released' : 'Upcoming');
  poster.src = item.poster_url || (item.poster_path ? `https://image.tmdb.org/t/p/w500${item.poster_path}` : 'https://via.placeholder.com/300x450?text=No+Artwork');
  poster.onerror = () => { poster.src = 'https://via.placeholder.com/300x450/0f172a/94a3b8?text=Artwork+Unavailable'; };

  // Backdrop Artwork Setup
  const initialBackdrop = item.backdrop_url || (item.backdrop_path ? `https://image.tmdb.org/t/p/w1280${item.backdrop_path}` : '');
  if (backdrop) {
    if (initialBackdrop) {
      backdrop.src = initialBackdrop;
      backdrop.style.display = 'block';
    } else if (item.poster_url || item.poster_path) {
      backdrop.src = item.poster_url || `https://image.tmdb.org/t/p/w780${item.poster_path}`;
      backdrop.style.display = 'block';
    } else {
      backdrop.src = '';
      backdrop.style.display = 'none';
    }
    backdrop.onerror = () => { backdrop.style.display = 'none'; };
  }

  crewNames.innerText = 'Director / Creator: ...';
  studioNames.innerText = 'Studio: ...';
  if (castList) castList.innerHTML = '<div class="text-slate-500 text-xs py-2 col-span-3">Loading starring cast...</div>';
  if (trailerBtn) trailerBtn.classList.add('hidden');
  if (imdbLink) imdbLink.classList.add('hidden');
  if (tmdbLink) tmdbLink.href = item.tmdb_id ? (state.activeDomain === 'movies' ? `https://www.themoviedb.org/movie/${item.tmdb_id}` : `https://www.themoviedb.org/tv/${item.tmdb_id}`) : '#';

  const inLibrary = item.owned || item.in_library || false;

  if (inLibrary) {
    libBadge.classList.remove('hidden');
    libBadge.className = 'px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-bold flex items-center gap-1 shadow-md backdrop-blur-md';
    libBadge.innerHTML = '<i data-lucide="check-circle" class="w-3.5 h-3.5 text-emerald-400"></i> IN PLEX';
  } else {
    // Hidden when not in Plex (action buttons Stream / Ingest / Search are at the top)
    libBadge.classList.add('hidden');
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
  setDetailStreamButtonState(item);
  setDetailPrepareStreamButtonState(item);
  renderDetailStreamCandidates(item);

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

        // Backdrop Artwork from TMDB details
        if (d.backdrop_path && backdrop) {
          backdrop.src = `https://image.tmdb.org/t/p/w1280${d.backdrop_path}`;
          backdrop.style.display = 'block';
        }

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
                  libBadge.className = 'px-2.5 py-1 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-bold flex items-center gap-1 shadow-sm backdrop-blur-md';
                  libBadge.innerHTML = '<i data-lucide="clock" class="w-3.5 h-3.5 inline"></i> UPCOMING THEATRICAL';
                  libBadge.classList.remove('hidden');
                }
              } else {
                const daysAgo = Math.abs(diffDays);
                if (daysAgo < 60) {
                  theatricalPill.innerText = `In Theaters (${daysAgo} day${daysAgo > 1 ? 's' : ''} ago)`;
                  theatricalPill.className = 'text-[10px] px-2 py-0.5 rounded-md bg-red-500/20 text-red-300 border border-red-500/30 font-bold';
                  theatricalDesc.innerHTML = `<span class="text-white font-semibold">${formattedDate}</span> · Currently in theatrical exclusivity window. Only low-quality CAM/Telesync copies exist in the wild (filtered out by MediaBot).`;
                  if (!inLibrary && libBadge) {
                    libBadge.className = 'px-2.5 py-1 rounded-lg bg-red-500/20 text-red-300 border border-red-500/30 text-xs font-bold flex items-center gap-1 shadow-sm backdrop-blur-md';
                    libBadge.innerHTML = '<i data-lucide="film" class="w-3.5 h-3.5 inline"></i> IN THEATERS';
                    libBadge.classList.remove('hidden');
                  }
                } else {
                  theatricalPill.innerText = `Past Theatrical Window (${daysAgo} days ago)`;
                  theatricalPill.className = 'text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold';
                  theatricalDesc.innerHTML = `<span class="text-white font-semibold">${formattedDate}</span> · Full studio theatrical run concluded. High-quality 4K/1080p Digital & WEB-DL releases are available.`;
                  if (!inLibrary && libBadge) {
                    libBadge.classList.add('hidden');
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

async function refreshHistorySubtabBadges() {
  try {
    // 1. Stream count
    const rStreams = await fetch('/api/stream/history?limit=100');
    if (rStreams.ok) {
      const d = await rStreams.json();
      const count = d.count || (d.streams || []).length;
      const b = document.getElementById('badge-history-streams');
      if (b) {
        b.innerText = count;
        if (count > 0) b.classList.remove('hidden');
        else b.classList.add('hidden');
      }
    }
    // 2. Transfers count
    const rTransfers = await fetch('/api/cloud/transfers');
    if (rTransfers.ok) {
      const d = await rTransfers.json();
      const count = d.active_count || 0;
      const b = document.getElementById('badge-history-transfers');
      if (b) {
        b.innerText = count;
        if (count > 0) b.classList.remove('hidden');
        else b.classList.add('hidden');
      }
    }
  } catch (e) {}
}

// Switch between Ingest Queue, Active Cloud Transfers, Pre-Warmed Cache, and Cloud Streams History
function switchHistorySubTab(tab) {
  const ingestsView = document.getElementById('subview-history-ingests');
  const prewarmView = document.getElementById('subview-history-prewarm');
  const streamsView = document.getElementById('subview-history-streams');
  const cloudTransfersView = document.getElementById('subview-history-cloud-transfers');
  const btnIngests = document.getElementById('subtab-btn-ingests');
  const btnPrewarm = document.getElementById('subtab-btn-prewarm');
  const btnStreams = document.getElementById('subtab-btn-streams');
  const btnCloudTransfers = document.getElementById('subtab-btn-cloud-transfers');
  const heading = document.getElementById('history-view-heading');
  const subheading = document.getElementById('history-view-subheading');

  // Reset all subtabs
  if (ingestsView) ingestsView.classList.add('hidden');
  if (prewarmView) prewarmView.classList.add('hidden');
  if (streamsView) streamsView.classList.add('hidden');
  if (cloudTransfersView) cloudTransfersView.classList.add('hidden');

  if (btnIngests) btnIngests.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition text-slate-400 hover:text-white flex items-center gap-1.5';
  if (btnPrewarm) btnPrewarm.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition text-slate-400 hover:text-white flex items-center gap-1.5';
  if (btnStreams) btnStreams.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition text-slate-400 hover:text-white flex items-center gap-1.5';
  if (btnCloudTransfers) btnCloudTransfers.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition text-slate-400 hover:text-white flex items-center gap-1.5';

  if (tab === 'prewarm') {
    if (prewarmView) prewarmView.classList.remove('hidden');
    if (btnPrewarm) btnPrewarm.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition bg-emerald-600 text-white shadow-sm flex items-center gap-1.5';
    if (heading) heading.innerText = '⚡ AllDebrid Pre-Warmed Cache Inspector';
    if (subheading) subheading.innerText = 'Verified winning releases, Complete Series boxsets, and 0-second RAM availability ready for instant grab & streaming.';
    loadPrewarmTable();
  } else if (tab === 'cloud_transfers') {
    if (cloudTransfersView) cloudTransfersView.classList.remove('hidden');
    if (btnCloudTransfers) btnCloudTransfers.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition bg-amber-600 text-white shadow-sm flex items-center gap-1.5';
    if (heading) heading.innerText = '☁️ AllDebrid Cloud Transfers & Caching Queue';
    if (subheading) subheading.innerText = 'Live background torrent downloads in AllDebrid cloud with real-time download speeds and finish estimates (ETA).';
    loadCloudTransfersTable();
  } else if (tab === 'streams') {
    if (streamsView) streamsView.classList.remove('hidden');
    if (btnStreams) btnStreams.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition bg-cyan-600 text-white shadow-sm flex items-center gap-1.5';
    if (heading) heading.innerText = '▶️ Cloud Streams & Preview History';
    if (subheading) subheading.innerText = 'Resume instant-cached cloud streams, check viewing progress, or permanently download previewed media to Plex.';
    loadStreamHistoryTable();
  } else {
    if (ingestsView) ingestsView.classList.remove('hidden');
    if (btnIngests) btnIngests.className = 'px-3 py-1.5 rounded-lg text-xs font-bold transition bg-cyan-500 text-white shadow-sm flex items-center gap-1.5';
    if (heading) heading.innerText = 'Download & Ingest History';
    if (subheading) subheading.innerText = 'Cross-domain historical download queue synchronized with media-watcher & Plex.';
    loadHistoryTable('all');
  }
}

let cloudTransfersTimer = null;

// Load and Render Active & Recent Cloud Downloads with Live ETA
async function loadCloudTransfersTable() {
  const container = document.getElementById('cloud-transfers-cards-container');
  const activeBadge = document.getElementById('cloud-transfers-active-badge');
  const activeCountEl = document.getElementById('cloud-transfers-active-count');
  if (!container) return;

  try {
    const res = await fetch('/api/cloud/transfers');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const transfers = data.transfers || [];
    const activeCount = data.active_count || 0;

    if (activeCountEl) activeCountEl.innerText = `${activeCount} Active Download${activeCount === 1 ? '' : 's'}`;
    if (activeBadge) {
      if (activeCount > 0) activeBadge.classList.remove('hidden');
      else activeBadge.classList.add('hidden');
    }

    container.innerHTML = '';
    if (transfers.length === 0) {
      container.innerHTML = `
        <div class="col-span-full py-12 text-center text-slate-500 text-xs bg-surface-card/40 rounded-2xl border border-surface-border p-6">
          <i data-lucide="cloud" class="w-10 h-10 mx-auto mb-2 opacity-40 text-amber-400"></i>
          <p class="font-bold text-slate-300">No active or recent AllDebrid cloud transfers.</p>
          <p class="text-[11px] text-slate-500 mt-1">When you click "Cache AD" on any uncached title, live downloading progress, speeds, and ETA will appear here.</p>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    transfers.forEach(t => {
      const card = document.createElement('div');
      const isReady = Boolean(t.ready);
      const browserReady = Boolean(t.browser_stream_ready);
      const isBrowserPrepare = t.intent_purpose === 'browser_stream';
      const mediaTitle = t.title || t.name || 'Unknown Media';
      const mediaDomain = t.domain || 'movies';
      const mediaYear = t.year || 'null';
      const mediaSeason = t.season || 0;
      const pct = t.progress_percent || 0;

      card.className = `p-4 rounded-2xl border ${isReady ? 'bg-surface-card/90 border-emerald-500/40 shadow-lg shadow-emerald-950/20' : 'bg-gradient-to-br from-surface-card via-surface-card to-amber-950/20 border-amber-500/40 shadow-xl shadow-amber-950/30'} flex flex-col justify-between gap-3.5 transition-all`;

      if (!isReady) {
        // Animated Downloading Card with Orbital Pulse and Live ETA
        card.innerHTML = `
          <div class="flex items-start gap-3">
            <div class="w-11 h-11 rounded-2xl bg-amber-500/20 text-amber-400 border border-amber-500/40 flex items-center justify-center shrink-0 animate-pulse shadow-md">
              <i data-lucide="cloud-lightning" class="w-5 h-5 animate-bounce"></i>
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center justify-between gap-2">
                <span class="text-[10px] uppercase font-bold px-2 py-0.5 rounded-md bg-amber-950/80 text-amber-300 border border-amber-500/40">
                  ${escapeHtml(isBrowserPrepare ? 'Preparing Browser Stream' : (t.stage_label || 'Downloading from Swarm'))}
                </span>
                <span class="text-[11px] font-mono font-extrabold text-amber-300 bg-black/40 px-2 py-0.5 rounded border border-amber-500/30">
                  ⏳ ${escapeHtml(t.eta_formatted || 'Estimating...')}
                </span>
              </div>
              <h4 class="font-bold text-white text-xs sm:text-sm truncate mt-1.5" title="${escapeHtml(t.name)}">${escapeHtml(t.name)}</h4>
            </div>
          </div>

          <!-- Progress Bar & Speed Stats -->
          <div class="space-y-1.5 bg-black/30 p-2.5 rounded-xl border border-white/5">
            <div class="flex items-center justify-between text-[11px] text-slate-300 font-mono">
              <span class="font-bold text-cyan-400">${t.downloaded_formatted || '0 MB'} / ${t.size_formatted || '0 MB'}</span>
              <span class="font-black text-amber-300">${pct}%</span>
            </div>
            <div class="w-full bg-slate-800 rounded-full h-2 overflow-hidden shadow-inner">
              <div class="bg-gradient-to-r from-amber-500 via-orange-500 to-cyan-400 h-2 rounded-full transition-all duration-300" style="width: ${pct}%"></div>
            </div>
            <div class="flex items-center justify-between text-[10px] text-slate-400 pt-0.5 font-medium">
              <span class="flex items-center gap-1 text-cyan-300 font-bold"><i data-lucide="zap" class="w-3 h-3 fill-cyan-400"></i> ${t.speed_formatted || '0 KB/s'}</span>
              <span class="flex items-center gap-1 text-slate-300"><i data-lucide="users" class="w-3 h-3"></i> ${t.seeders || 0} seeders</span>
            </div>
          </div>

          <!-- Card Actions -->
          <div class="flex items-center justify-between pt-1 border-t border-surface-border/60 text-xs">
            <span class="text-[10px] text-slate-500 font-mono">ID: ${escapeHtml(String(t.id))}</span>
            <button onclick="deleteCloudTransfer('${escapeJs(String(t.id))}')" class="px-2.5 py-1 rounded-lg text-slate-400 hover:text-rose-300 hover:bg-rose-950/40 border border-transparent hover:border-rose-500/30 text-xs font-semibold transition flex items-center gap-1" title="Cancel cloud download">
              <i data-lucide="x" class="w-3.5 h-3.5"></i>
              <span>Cancel</span>
            </button>
          </div>
        `;
      } else {
        // A cloud-cached download and a verified browser stream are separate capabilities.
        card.innerHTML = `
          <div class="flex items-start gap-3">
            <div class="w-11 h-11 rounded-2xl bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 flex items-center justify-center shrink-0 shadow-md">
              <i data-lucide="zap" class="w-5 h-5 fill-emerald-400"></i>
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center justify-between gap-2">
                <span class="text-[10px] uppercase font-black px-2 py-0.5 rounded-md bg-emerald-950 text-emerald-300 border border-emerald-500/50 flex items-center gap-1">
                  <i data-lucide="check" class="w-3 h-3 text-emerald-400"></i> ${browserReady ? '▶ BROWSER STREAM READY' : '☁ READY IN ALLDEBRID'}
                </span>
                <span class="text-[10px] font-mono text-slate-400">${t.size_formatted || ''}</span>
              </div>
              <h4 class="font-bold text-white text-xs sm:text-sm truncate mt-1.5" title="${escapeHtml(t.name)}">${escapeHtml(t.name)}</h4>
            </div>
          </div>

          <!-- Ready Status Box -->
          <div class="bg-emerald-950/30 p-2.5 rounded-xl border border-emerald-500/30 flex items-center justify-between text-xs">
            <span class="text-emerald-300 font-semibold text-[11px] flex items-center gap-1">
              <i data-lucide="${browserReady ? 'play-circle' : 'cloud-check'}" class="w-3.5 h-3.5 text-emerald-400"></i>
              ${browserReady ? 'Verified MP4/H.264/AAC copy is ready for browser playback' : 'Cached for instant download; browser playback is not claimed'}
            </span>
            <span class="text-[10px] font-mono text-slate-400 font-bold">100% Downloaded</span>
          </div>

          <!-- Card Actions -->
          <div class="flex items-center justify-between pt-1 border-t border-surface-border/60 text-xs">
            <button onclick="deleteCloudTransfer('${escapeJs(String(t.id))}')" class="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 transition" title="Dismiss from cloud list">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
            <div class="flex items-center gap-2">
              ${browserReady ? `
                <button onclick="openStreamPlayer({ title: '${escapeJs(mediaTitle)}', domain: '${escapeJs(mediaDomain)}', year: ${mediaYear}, season: ${mediaSeason}, reference_id: '${escapeJs(t.reference_id || '')}' })" class="px-3 py-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-extrabold text-xs shadow-md shadow-cyan-500/20 flex items-center gap-1.5 transition active:scale-95">
                  <i data-lucide="play" class="w-3.5 h-3.5 fill-white"></i>
                  <span>▶️ Stream Now</span>
                </button>
              ` : `
                <button onclick="openSearchModal('${escapeJs(mediaTitle)}', '${escapeJs(mediaDomain)}')" class="px-3 py-1.5 rounded-xl bg-surface-hover hover:bg-slate-700 text-slate-200 border border-surface-border font-bold text-xs flex items-center gap-1 transition active:scale-95" title="Search all release formats">
                  <i data-lucide="search" class="w-3.5 h-3.5"></i>
                  <span>Search</span>
                </button>
              `}
              <button onclick="onDetailIngestClick({ title: '${escapeJs(mediaTitle)}', domain: '${escapeJs(mediaDomain)}', year: ${mediaYear}, season: ${mediaSeason} })" class="px-3 py-1.5 rounded-xl bg-surface-hover hover:bg-slate-700 text-slate-200 border border-surface-border font-bold text-xs flex items-center gap-1 transition active:scale-95" title="Download to Local Disk via IDM">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span>Grab to Plex</span>
              </button>
            </div>
          </div>
        `;
      }

      container.appendChild(card);
    });

    if (window.lucide) lucide.createIcons();

    // Auto-poll if any transfers are active
    if (cloudTransfersTimer) clearTimeout(cloudTransfersTimer);
    const transfersView = document.getElementById('subview-history-cloud-transfers');
    if (transfersView && !transfersView.classList.contains('hidden') && activeCount > 0) {
      cloudTransfersTimer = setTimeout(loadCloudTransfersTable, 3000);
    }

  } catch (err) {
    console.error("Failed to load cloud transfers:", err);
  }
}

// Load and Render Cloud Stream History
async function loadStreamHistoryTable() {
  const tbody = document.getElementById('stream-history-table-body');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="5" class="py-12 text-center text-slate-400">
        <div class="inline-block w-6 h-6 border-2 border-cyan-500/20 border-t-cyan-500 rounded-full animate-spin mb-2"></div>
        <p class="text-xs">Loading cloud streaming history...</p>
      </td>
    </tr>
  `;

  try {
    const res = await fetch('/api/stream/history?limit=50');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const streams = data.streams || [];

    tbody.innerHTML = '';
    if (streams.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="py-12 text-center text-slate-500 text-xs">
            <i data-lucide="play-circle" class="w-8 h-8 mx-auto mb-2 opacity-40"></i>
            No cloud streams yet. Click "Stream Now" on any ⚡ instant-cached title to preview instantly.
          </td>
        </tr>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    streams.forEach(st => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-surface-hover/50 transition-colors';

      let scopeLabel = '🎬 Movie';
      if (st.season > 0 && st.episode > 0) {
        scopeLabel = `📺 S${String(st.season).padStart(2, '0')}E${String(st.episode).padStart(2, '0')}`;
      } else if (st.season > 0) {
        scopeLabel = `📺 Season ${st.season}`;
      }

      const pct = Math.min(100, Math.max(0, Math.round(st.progress_percent || 0)));
      const isDone = st.completed === 1 || pct >= 90;

      const progressHtml = `
        <div class="w-48">
          <div class="flex items-center justify-between text-[10px] text-slate-400 mb-1">
            <span class="${isDone ? 'text-emerald-400 font-bold' : 'text-slate-300'}">${isDone ? '✅ Completed' : `${pct}% Watched`}</span>
            <span class="font-mono">${formatDuration(st.progress_seconds)} / ${formatDuration(st.duration_seconds)}</span>
          </div>
          <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div class="h-1.5 rounded-full ${isDone ? 'bg-emerald-400' : 'bg-gradient-to-r from-cyan-500 to-blue-500'}" style="width: ${pct}%"></div>
          </div>
        </div>
      `;

      tr.innerHTML = `
        <td class="py-3 px-4">
          <p class="font-bold text-white">${escapeHtml(st.title)}</p>
          <p class="text-[11px] text-slate-400 font-mono truncate max-w-sm">${escapeHtml(st.release_title || st.title)}</p>
        </td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded-md bg-surface-card border border-surface-border text-[11px] font-semibold text-slate-200">
            ${scopeLabel}
          </span>
        </td>
        <td class="py-3 px-4">${progressHtml}</td>
        <td class="py-3 px-4 whitespace-nowrap text-[11px] text-slate-400">${formatESTTime(st.last_streamed_at)}</td>
        <td class="py-3 px-4 text-right">
          <div class="flex items-center justify-end gap-1.5">
            <button onclick="resumeStreamSession('${escapeJs(st.id)}', '${escapeJs(st.title)}', '${st.domain}', ${st.season}, ${st.episode}, ${st.year || 'null'})" class="px-2.5 py-1 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-white font-bold text-xs shrink-0 transition active:scale-95 flex items-center gap-1" title="Resume stream in Web Player">
              <i data-lucide="play" class="w-3 h-3 fill-white"></i>
              <span>Resume</span>
            </button>
            <button onclick="downloadStreamSessionItem('${escapeJs(st.title)}', '${st.domain}', ${st.season}, ${st.year || 'null'})" class="px-2.5 py-1 rounded-lg bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border font-bold text-xs shrink-0 transition active:scale-95 flex items-center gap-1" title="Permanently Download to Local Plex Storage">
              <i data-lucide="download" class="w-3 h-3"></i>
              <span>Grab</span>
            </button>
            <button onclick="deleteStreamSession('${escapeJs(st.id)}')" class="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 transition" title="Delete from stream history">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error("Failed to load stream history:", err);
    tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-rose-400 text-xs">Failed to load stream history.</td></tr>`;
  }
}

state.prewarmDomain = 'all';
state.prewarmStatus = 'all';
state.prewarm = {
  items: [],
  page: 1,
  pageSize: 15,
  sortBy: 'cached', // 'title', 'domain', 'size', 'cached', 'updated_at'
  sortDir: 'desc'
};

function filterPrewarmDomain(domain) {
  state.prewarmDomain = domain;
  document.querySelectorAll('.prewarm-domain-btn').forEach(btn => btn.classList.remove('active'));
  if (event && event.target) event.target.classList.add('active');
  state.prewarm.page = 1;
  loadPrewarmTable();
}

function filterPrewarmStatus(status) {
  state.prewarmStatus = status;
  document.querySelectorAll('.prewarm-status-btn').forEach(btn => {
    btn.classList.remove('active', 'bg-cyan-500', 'text-white');
  });
  const activeBtn = document.getElementById(`btn-status-${status}`);
  if (activeBtn) activeBtn.classList.add('active');
  state.prewarm.page = 1;
  loadPrewarmTable();
}

function sortPrewarmTable(col) {
  if (state.prewarm.sortBy === col) {
    state.prewarm.sortDir = state.prewarm.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    state.prewarm.sortBy = col;
    state.prewarm.sortDir = (col === 'title' || col === 'domain') ? 'asc' : 'desc';
  }
  updatePrewarmSortIcons();
  renderPrewarmTablePage();
}

function updatePrewarmSortIcons() {
  ['title', 'domain', 'size', 'cached', 'updated_at'].forEach(col => {
    const el = document.getElementById(`sort-icon-${col}`);
    if (!el) return;
    if (state.prewarm.sortBy === col) {
      el.innerText = state.prewarm.sortDir === 'asc' ? '▲' : '▼';
      el.className = 'text-cyan-400 font-mono text-[11px] font-bold';
    } else {
      el.innerText = '↕';
      el.className = 'text-slate-500 font-mono text-[11px] group-hover:text-slate-300';
    }
  });
}

function changePrewarmPage(target) {
  const totalItems = state.prewarm.items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / state.prewarm.pageSize));
  if (target === 'last') {
    state.prewarm.page = totalPages;
  } else {
    const p = parseInt(target);
    state.prewarm.page = Math.max(1, Math.min(totalPages, isNaN(p) ? 1 : p));
  }
  renderPrewarmTablePage();
}

function changePrewarmPageSize(size) {
  state.prewarm.pageSize = parseInt(size) || 15;
  state.prewarm.page = 1;
  renderPrewarmTablePage();
}

function getSortedPrewarmItems() {
  const items = [...state.prewarm.items];
  const { sortBy, sortDir } = state.prewarm;
  const mult = sortDir === 'asc' ? 1 : -1;

  items.sort((a, b) => {
    if (sortBy === 'title') {
      return mult * (a.title || '').localeCompare(b.title || '');
    }
    if (sortBy === 'domain') {
      const dComp = (a.domain || '').localeCompare(b.domain || '');
      if (dComp !== 0) return mult * dComp;
      return mult * ((a.season || 0) - (b.season || 0));
    }
    if (sortBy === 'size') {
      return mult * ((a.size_bytes || 0) - (b.size_bytes || 0));
    }
    if (sortBy === 'cached') {
      const getWeight = (it) => it.instant_cached ? 3 : (it.cloud_cached ? 2 : (it.dropped ? 1 : 0));
      const wA = getWeight(a);
      const wB = getWeight(b);
      if (wA !== wB) return mult * (wA - wB);
      return (b.seeders || 0) - (a.seeders || 0);
    }
    if (sortBy === 'updated_at') {
      const tA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const tB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return mult * (tA - tB);
    }
    return 0;
  });

  return items;
}

function renderPrewarmTablePage() {
  const tbody = document.getElementById('prewarm-table-body');
  if (!tbody) return;

  const sorted = getSortedPrewarmItems();
  const total = sorted.length;
  const totalPages = Math.max(1, Math.ceil(total / state.prewarm.pageSize));

  // Clamp page
  if (state.prewarm.page > totalPages) state.prewarm.page = totalPages;
  if (state.prewarm.page < 1) state.prewarm.page = 1;

  const startIdx = (state.prewarm.page - 1) * state.prewarm.pageSize;
  const endIdx = Math.min(startIdx + state.prewarm.pageSize, total);
  const pageItems = sorted.slice(startIdx, endIdx);

  // Update Pagination Info
  const infoEl = document.getElementById('prewarm-pagination-info');
  if (infoEl) {
    if (total === 0) infoEl.innerText = 'Showing 0 records';
    else infoEl.innerText = `Showing ${startIdx + 1} - ${endIdx} of ${total} records (Page ${state.prewarm.page} of ${totalPages})`;
  }

  // Update Buttons
  const btnFirst = document.getElementById('btn-prewarm-first');
  const btnPrev = document.getElementById('btn-prewarm-prev');
  const btnNext = document.getElementById('btn-prewarm-next');
  const btnLast = document.getElementById('btn-prewarm-last');

  if (btnFirst) btnFirst.disabled = state.prewarm.page <= 1;
  if (btnPrev) btnPrev.disabled = state.prewarm.page <= 1;
  if (btnNext) btnNext.disabled = state.prewarm.page >= totalPages;
  if (btnLast) btnLast.disabled = state.prewarm.page >= totalPages;

  // Render Page Pills
  const pillsEl = document.getElementById('prewarm-page-pills');
  if (pillsEl) {
    pillsEl.innerHTML = '';
    const maxPills = 5;
    let startP = Math.max(1, state.prewarm.page - Math.floor(maxPills / 2));
    let endP = Math.min(totalPages, startP + maxPills - 1);
    if (endP - startP + 1 < maxPills) startP = Math.max(1, endP - maxPills + 1);

    for (let p = startP; p <= endP; p++) {
      const btn = document.createElement('button');
      const isAct = p === state.prewarm.page;
      btn.className = `px-2.5 py-1 rounded-lg text-xs font-bold transition border ${
        isAct ? 'bg-cyan-500 text-white border-cyan-400 shadow-sm' : 'bg-surface-card hover:bg-slate-700 text-slate-300 border-surface-border'
      }`;
      btn.innerText = p;
      btn.onclick = () => changePrewarmPage(p);
      pillsEl.appendChild(btn);
    }
  }

  tbody.innerHTML = '';
  if (total === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="py-12 text-center text-slate-500">
          No pre-warmed records match current filter. Click <strong>"Pre-warm Now"</strong> above to scan frontier!
        </td>
      </tr>
    `;
    return;
  }

  pageItems.forEach(item => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-surface-hover/50 transition-colors';

    let scopeBadge = '';
    if (item.domain === 'movies') {
      scopeBadge = '<span class="px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30 text-[10px] font-bold">🎬 Movie</span>';
    } else if (item.season === 0) {
      scopeBadge = '<span class="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 text-[10px] font-bold">📦 Complete Run</span>';
    } else {
      scopeBadge = `<span class="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-[10px] font-bold">Season ${item.season}</span>`;
    }

    let originBadge = '';
    const vo = item.vector_origin || '';
    if (vo === 'season_progression') {
      originBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-500/30 font-semibold inline-flex items-center gap-0.5 whitespace-nowrap">🪜 Season Walker</span>';
    } else if (vo === 'plex_watch_priority') {
      originBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-500/30 font-semibold inline-flex items-center gap-0.5 whitespace-nowrap">📺 Watch Priority</span>';
    } else if (vo === 'infinite_tmdb_classic') {
      originBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-500/30 font-semibold inline-flex items-center gap-0.5 whitespace-nowrap">🌐 Infinite TMDb</span>';
    } else if (vo.includes('movie')) {
      originBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-500/30 font-semibold inline-flex items-center gap-0.5 whitespace-nowrap">🎬 Movies Vault</span>';
    } else {
      originBadge = '<span class="text-[9px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/30 font-semibold inline-flex items-center gap-0.5 whitespace-nowrap">🏛️ Classic Frontier</span>';
    }

    let cacheStatusHtml = '';
    const isCloudCached = item.cloud_cached === true || item.cached === true;
    const isInstantCached = item.instant_cached === true;
    const isExternalCached = isCloudCached && !isInstantCached;
    // Derive codec from release title for browser compatibility awareness
    const rl = (item.release_title || '').toLowerCase();
    const isHEVC = rl.includes('x265') || rl.includes('hevc') || rl.includes('h265') || rl.includes('h.265') || rl.includes('10bit');
    const codecTag = isHEVC ? 'HEVC' : (rl.includes('x264') || rl.includes('h264') || rl.includes('h.264') || rl.includes('avc') ? 'H.264' : '');
    const codecBadge = codecTag
      ? (isHEVC
        ? ' <span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-950 text-amber-300 border border-amber-500/30 whitespace-nowrap">HEVC</span>'
        : ' <span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-500/30 whitespace-nowrap">H.264</span>')
      : '';

    if (isInstantCached) {
      cacheStatusHtml = `<span class="inline-flex items-center gap-1 whitespace-nowrap"><span class="px-2.5 py-1 rounded-md bg-emerald-950 text-emerald-300 border border-emerald-500/50 text-[11px] font-black inline-flex items-center gap-1 whitespace-nowrap shadow-sm"><i data-lucide="zap" class="w-3 h-3 fill-emerald-400 text-emerald-400 shrink-0"></i> ⚡ Instant Cached</span>${codecBadge}</span>`;
    } else if (isExternalCached) {
      cacheStatusHtml = `<span class="inline-flex items-center gap-1 whitespace-nowrap"><span class="px-2.5 py-1 rounded-md bg-indigo-950 text-indigo-300 border border-indigo-500/50 text-[11px] font-black inline-flex items-center gap-1 whitespace-nowrap shadow-sm"><i data-lucide="cloud" class="w-3 h-3 text-indigo-300 shrink-0"></i> ☁️ Cached for Download</span>${codecBadge}</span>`;
    } else if (item.dropped) {
      cacheStatusHtml = `<span class="inline-flex items-center gap-1 whitespace-nowrap"><span class="px-2.5 py-1 rounded-md bg-rose-950/80 text-rose-300 border border-rose-500/50 text-[11px] font-bold inline-flex items-center gap-1 whitespace-nowrap shadow-sm"><i data-lucide="alert-triangle" class="w-3 h-3 text-rose-400 shrink-0"></i> ⚠️ Dropped</span>${codecBadge}</span>`;
    } else {
      cacheStatusHtml = `<span class="inline-flex items-center gap-1 whitespace-nowrap"><span class="px-2.5 py-1 rounded-md bg-amber-950/60 text-amber-300 border border-amber-500/40 text-[11px] font-semibold inline-flex items-center gap-1 whitespace-nowrap"><i data-lucide="download-cloud" class="w-3 h-3 text-amber-400 shrink-0"></i> ⏳ P2P (${item.seeders || 0} Seeds)</span>${codecBadge}</span>`;
    }

    const verifiedTimeHtml = formatESTTime(item.updated_at);

    // Codec-aware action buttons
    let streamActionHtml = '';
    if (isInstantCached) {
      streamActionHtml = `
          <button onclick="openStreamPlayer({ title: '${escapeJs(item.title)}', year: ${item.year || 'null'}, domain: '${item.domain}', season: ${item.season || 0}, episode: 0, reference_id: '${escapeJs(item.stream_reference_id || item.reference_id)}' })" class="px-2.5 py-1 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-white font-bold text-xs shrink-0 transition active:scale-95 flex items-center gap-1 shadow-sm whitespace-nowrap" title="Stream the verified browser-compatible release">
          <i data-lucide="play" class="w-3 h-3 fill-white shrink-0"></i>
          <span>Stream</span>
        </button>
      `;
    } else if (isExternalCached) {
      streamActionHtml = `
        <button onclick="openStreamPlayer({ title: '${escapeJs(item.title)}', year: ${item.year || 'null'}, domain: '${item.domain}', season: ${item.season || 0}, episode: 0, reference_id: '${escapeJs(item.download_reference_id || item.reference_id)}' })" class="px-2.5 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs shrink-0 transition active:scale-95 flex items-center gap-1 shadow-sm whitespace-nowrap" title="Open the cached release with an external player">
          <i data-lucide="monitor-play" class="w-3 h-3 shrink-0"></i>
          <span>External</span>
        </button>
      `;
    } else {
      streamActionHtml = `
        <button onclick="cacheToCloud('', '${escapeJs(item.title)}', '${item.domain}', ${item.season || 0}, '${escapeJs(item.reference_id)}', ${item.year || 'null'})" class="px-2.5 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 font-bold text-xs shrink-0 transition active:scale-95 flex items-center gap-1 whitespace-nowrap" title="Cache this release in AllDebrid for instant downloading">
          <i data-lucide="cloud" class="w-3 h-3 shrink-0"></i>
          <span>Cache AD</span>
        </button>
      `;
    }

    tr.innerHTML = `
      <td class="py-3 px-4">
        <p class="font-bold text-white">${escapeHtml(item.title)}</p>
        <div class="flex items-center gap-1.5 mt-0.5">
          <span class="text-[10px] text-slate-400 uppercase tracking-wider">${item.domain}</span>
          <span>•</span>
          ${originBadge}
        </div>
      </td>
      <td class="py-3 px-4">${scopeBadge}</td>
      <td class="py-3 px-4 max-w-xs">
        <p class="font-medium text-slate-200 truncate text-[11px]">${escapeHtml(item.release_title)}</p>
        <p class="text-[10px] text-slate-400">${item.resolution || '1080p'} • ${item.formatted_size || 'N/A'}</p>
      </td>
      <td class="py-3 px-4">${cacheStatusHtml}</td>
      <td class="py-3 px-4 whitespace-nowrap text-[11px]">${verifiedTimeHtml}</td>
      <td class="py-3 px-4 text-right">
        <div class="flex items-center justify-end gap-1.5">
          ${streamActionHtml}
           <button onclick="onIngestPrewarmedItem('${escapeJs(item.download_reference_id || item.reference_id)}', '${escapeJs(item.title)}', '${item.domain}', ${item.season || 0})" class="px-2.5 py-1 rounded-lg ${isCloudCached ? 'bg-emerald-950/80 hover:bg-emerald-900 text-emerald-300 border border-emerald-500/40' : 'bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border'} font-bold text-xs shrink-0 transition active:scale-95 flex items-center gap-1 whitespace-nowrap" title="Download directly to Local Disk via IDM">
             <i data-lucide="${isInstantCached ? 'zap' : (isCloudCached ? 'cloud' : 'download')}" class="w-3 h-3 shrink-0"></i>
            <span>Grab</span>
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });

  if (window.lucide) lucide.createIcons();
}

async function loadPrewarmTable() {
  const tbody = document.getElementById('prewarm-table-body');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="6" class="py-12 text-center text-slate-500">
        <div class="w-6 h-6 border-2 border-emerald-500/20 border-t-emerald-500 rounded-full animate-spin mx-auto mb-2"></div>
        Loading pre-warmed AllDebrid cache records & scoreboard...
      </td>
    </tr>
  `;

  try {
    const res = await fetch(`/api/prewarm/items?domain=${state.prewarmDomain}&status=${state.prewarmStatus}&limit=1000`);
    const data = await res.json();
    state.prewarm.items = data.items || [];
    renderPrewarmRuntimeStatus(data);
    const sb = data.scoreboard || data.stats || {};

    const cachedEl = document.getElementById('prewarm-stat-cached');
    const uncachedEl = document.getElementById('prewarm-stat-uncached');
    const droppedEl = document.getElementById('prewarm-stat-dropped');
    const togoEl = document.getElementById('prewarm-stat-togo');
    const progTextEl = document.getElementById('prewarm-progress-text');
    const progBarEl = document.getElementById('prewarm-progress-bar');

    if (cachedEl) cachedEl.innerText = sb.instant_cached || 0;
    if (uncachedEl) uncachedEl.innerText = sb.p2p_only || 0;
    if (droppedEl) droppedEl.innerText = sb.dropped_count || 0;
    if (togoEl) togoEl.innerText = sb.frontier_to_go || 0;

    const catalogTotal = sb.catalog_total || 130;
    const progPct = sb.progress_percent || (catalogTotal ? Math.round(((sb.instant_cached || 0) / catalogTotal) * 100) : 0);
    if (progTextEl) progTextEl.innerText = `${sb.instant_cached || 0} / ${catalogTotal} (${progPct}%)`;
    if (progBarEl) progBarEl.style.width = `${Math.min(100, progPct)}%`;

    const goalHeadingEl = document.getElementById('prewarm-goal-label');
    if (goalHeadingEl) {
      const tierPrefix = sb.tier_level ? `Tier ${sb.tier_level} ` : '';
      if (state.prewarmDomain === 'movies') goalHeadingEl.innerText = `🎬 ${tierPrefix}Movies`;
      else if (state.prewarmDomain === 'tv') goalHeadingEl.innerText = `📺 ${tierPrefix}TV`;
      else if (state.prewarmDomain === 'tv_classic') goalHeadingEl.innerText = `🏛️ ${tierPrefix}Classic TV`;
      else goalHeadingEl.innerText = `🏆 ${tierPrefix}Master Goal`;
    }

    // Populate Vector Activity Counters
    const vb = sb.vector_breakdown || {};
    const vSeasonEl = document.getElementById('vcnt-season');
    const vClassicEl = document.getElementById('vcnt-classic');
    const vPlexEl = document.getElementById('vcnt-plex');
    const vMoviesEl = document.getElementById('vcnt-movies');

    if (vSeasonEl) vSeasonEl.innerText = vb.season_progression || 0;
    if (vClassicEl) vClassicEl.innerText = (vb.frontier_boxset || 0) + (vb.frontier_s1 || 0) + (vb.classic_frontier || 0) + (vb.frontier || 0) + (vb.infinite_tmdb_classic || 0);
    if (vPlexEl) vPlexEl.innerText = vb.plex_watch_priority || 0;
    if (vMoviesEl) vMoviesEl.innerText = (vb.movie_popular || 0) + (vb.movies_top_rated || 0) + (vb.movies_trending || 0) + (vb.movie || 0);

    // Populate Last Run Activity Summary
    const summaryEl = document.getElementById('prewarm-last-run-summary');
    if (summaryEl) {
      if (data.is_prewarming) {
        summaryEl.innerHTML = '<span class="text-cyan-400 font-bold flex items-center gap-1"><i data-lucide="refresh-cw" class="w-3 h-3 animate-spin"></i> ⚡ Scanning progressive frontier now...</span>';
      } else if (data.last_stats) {
        summaryEl.innerText = `Last Pass: ${data.last_stats.reverified_count || 0} re-verified • ${data.last_stats.cached_count || 0} cached (${data.last_stats.elapsed_seconds || 0}s)`;
      } else if (sb.last_updated) {
        summaryEl.innerHTML = `Last Verified: ${formatESTTime(sb.last_updated)}`;
      } else {
        summaryEl.innerText = 'Auto-sync interval: 6h';
      }
    }

    updatePrewarmSortIcons();
    renderPrewarmTablePage();
  } catch (err) {
    console.error("Failed to load pre-warmed cache table:", err);
  }
}

function prewarmStatusStyle(status) {
  const styles = {
    running: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    completed: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    failed: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    interrupted: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    skipped: 'bg-slate-700/60 text-slate-300 border-slate-500/30',
    scheduled: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  };
  return styles[status] || 'bg-slate-800 text-slate-400 border-surface-border';
}

function formatPrewarmLedgerTime(timeStr) {
  if (!timeStr) return 'not recorded';
  let utcStr = timeStr;
  if (!timeStr.endsWith('Z') && !timeStr.includes('+')) {
    utcStr = timeStr.replace(' ', 'T') + 'Z';
  }
  const value = new Date(utcStr);
  if (isNaN(value.getTime())) return String(timeStr);
  try {
    return `${value.toLocaleString('en-CA', {
      timeZone: 'America/Toronto',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })} ET`;
  } catch (err) {
    return value.toISOString();
  }
}

function renderPrewarmRuntimeStatus(data) {
  const active = data.active_cycle || null;
  const last = data.last_cycle || null;
  const recent = (data.recent_cycles || []).slice(0, 10);
  const nextDue = active ? 'after current cycle' : (data.next_due_at ? formatPrewarmLedgerTime(data.next_due_at) : 'not scheduled');
  const status = active?.status || last?.status || 'idle';

  const badge = document.getElementById('prewarm-status-badge');
  if (badge) {
    badge.className = `px-2 py-0.5 rounded-full text-[10px] font-bold border ${prewarmStatusStyle(status)}`;
    badge.innerText = status.charAt(0).toUpperCase() + status.slice(1);
  }

  const settingsLast = document.getElementById('prewarm-last-run-label');
  if (settingsLast) {
    if (active) settingsLast.innerText = `Running: ${active.cycle_id.slice(0, 8)} • ${active.trigger_source}`;
    else if (last) settingsLast.innerText = `Last: ${last.status} • ${formatPrewarmLedgerTime(last.finished_at || last.scheduled_at)}`;
    else settingsLast.innerText = 'Status: No recorded cycles';
  }
  const settingsNext = document.getElementById('prewarm-next-run-label');
  if (settingsNext) settingsNext.innerText = `Next: ${nextDue}`;

  const activeEl = document.getElementById('prewarm-ledger-active');
  if (activeEl) {
    activeEl.className = `px-2 py-1 rounded-md border ${prewarmStatusStyle(status)}`;
    activeEl.innerText = active ? `Running ${active.cycle_id.slice(0, 8)}` : `Idle • ${status}`;
  }
  const nextEl = document.getElementById('prewarm-ledger-next');
  if (nextEl) nextEl.innerText = `Next: ${nextDue}`;

  const history = document.getElementById('prewarm-cycle-history');
  if (history) {
    if (!recent.length) {
      history.innerHTML = '<div class="text-[11px] text-slate-500 py-2">No durable cycle history yet.</div>';
    } else {
      history.innerHTML = recent.map(cycle => {
        const counts = cycle.phase_counts || {};
        const when = cycle.finished_at || cycle.started_at || cycle.scheduled_at;
        const reason = cycle.stop_reason ? ` • ${escapeHtml(cycle.stop_reason)}` : '';
        return `
          <div class="rounded-lg bg-slate-950/35 border border-surface-border px-3 py-2 flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="px-1.5 py-0.5 rounded border text-[9px] font-black uppercase ${prewarmStatusStyle(cycle.status)}">${escapeHtml(cycle.status)}</span>
                <span class="text-[10px] text-slate-500">${escapeHtml(cycle.trigger_source || 'unknown')} • ${escapeHtml(cycle.cycle_id.slice(0, 8))}</span>
              </div>
              <p class="text-[10px] text-slate-500 mt-1 truncate">${when ? escapeHtml(formatPrewarmLedgerTime(when)) : 'No timestamp'}${reason}</p>
            </div>
            <div class="text-right shrink-0">
              <p class="text-[10px] font-bold text-slate-300">${counts.reverified_count || 0} rechecked</p>
              <p class="text-[9px] text-slate-500">${counts.cached_count || 0} direct • ${counts.cloud_cached_count || 0} cloud</p>
            </div>
          </div>`;
      }).join('');
    }
  }

  const btn = document.getElementById('btn-trigger-prewarm');
  if (btn) {
    btn.disabled = Boolean(active);
    btn.innerHTML = active
      ? '<div class="w-3.5 h-3.5 border-2 border-cyan-400/20 border-t-cyan-400 rounded-full animate-spin"></div> Running'
      : '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> <span>Pre-warm Now</span>';
    if (window.lucide) lucide.createIcons();
  }
}

async function refreshPrewarmRuntimeStatus() {
  try {
    const res = await fetch('/api/prewarm/status?limit=10');
    if (!res.ok) return;
    const data = await res.json();
    if (data.ok) renderPrewarmRuntimeStatus(data);
  } catch (err) {
    console.debug('Pre-warm runtime status unavailable:', err);
  }
}

async function onIngestPrewarmedItem(refId, title, domain, season) {
  showToast(`⚡ Ingesting "${title}" from pre-warmed cache...`, "info");
  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference_id: refId,
        domain: domain,
        title: title
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`⚡ Queued "${title}" into IDM!`, "success");
      setTimeout(loadSidebarHistory, 1500);
    } else {
      showToast(`Ingest failed: ${data.error || 'Unknown error'}`, "error");
    }
  } catch (err) {
    console.error("Prewarmed ingest error:", err);
    showToast("Failed to queue item.", "error");
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

    // CARD 5: Background Cache Pre-Warmer
    const setPrewarmEn = document.getElementById('setting-prewarm-enabled');
    if (setPrewarmEn) setPrewarmEn.checked = s.background_prewarm_enabled !== false;

    const setPrewarmInt = document.getElementById('setting-prewarm-interval');
    if (setPrewarmInt) setPrewarmInt.value = String(s.prewarm_interval_hours || 6);
    refreshPrewarmRuntimeStatus();

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

    // Background Pre-Warmer
    background_prewarm_enabled: Boolean(document.getElementById('setting-prewarm-enabled')?.checked),
    prewarm_interval_hours: parseInt(document.getElementById('setting-prewarm-interval')?.value || 6, 10),
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

async function triggerManualPrewarm() {
  const btn = document.getElementById('btn-trigger-prewarm');
  const label = document.getElementById('prewarm-last-run-label');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<div class="w-3.5 h-3.5 border-2 border-cyan-400/20 border-t-cyan-400 rounded-full animate-spin"></div> Pre-warming...';
  }
  if (label) {
    label.innerText = 'Status: Scanning indexers & AllDebrid RAM...';
  }
  showToast("⚡ Starting background cache pre-warm cycle...", "info");

  try {
    const res = await fetch('/api/prewarm/trigger', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      showToast(`✨ Pre-warm cycle ${data.cycle_id.slice(0, 8)} started.`, "success");
      await refreshPrewarmRuntimeStatus();
      setTimeout(refreshPrewarmRuntimeStatus, 1500);
    } else {
      const message = data.error?.message || data.message || 'Error';
      showToast(`Pre-warm not started: ${message}`, "error");
      await refreshPrewarmRuntimeStatus();
    }
  } catch (err) {
    console.error("Prewarm trigger error:", err);
    showToast("Failed to trigger pre-warm task.", "error");
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Pre-warm Now';
      if (window.lucide) lucide.createIcons();
    }
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
    filtered = filtered.filter(item => item.instant_cached === true);
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
    const isCloudCached = item.cloud_cached === true || item.cached === true;
    const isInstantCached = item.instant_cached === true;
    const isExternalCached = isCloudCached && !isInstantCached;
    
    card.className = `release-row ${isCloudCached ? 'cached-row bg-surface-card/90' : 'bg-surface-card/60'} border border-surface-border rounded-xl p-3.5 sm:p-4 flex flex-col md:flex-row md:items-center justify-between gap-3.5 shadow-lg`;

    // ⚡ means browser stream; ☁️ means cached for download only.
    const badgeHtml = isInstantCached
      ? `<span class="lightning-cache-tag px-2.5 py-1 rounded-lg text-xs font-extrabold flex items-center gap-1.5 shrink-0 shadow-md">
           <i data-lucide="zap" class="w-3.5 h-3.5 fill-emerald-400 text-emerald-400"></i>
           <span>⚡ Browser Stream + Cached Download</span>
         </span>`
      : isExternalCached
      ? `<span class="px-2.5 py-1 rounded-lg text-xs font-extrabold flex items-center gap-1.5 shrink-0 shadow-md bg-indigo-950 text-indigo-300 border border-indigo-500/40">
           <i data-lucide="cloud" class="w-3.5 h-3.5"></i>
           <span>☁️ Cached for Download</span>
         </span>`
      : `<span class="uncached-tag px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 shrink-0">
           <i data-lucide="clock" class="w-3.5 h-3.5 text-amber-400"></i>
           <span>⏳ Uncached (P2P)</span>
         </span>`;

    // High-Contrast Resolution & Quality Badge
    let qualityClass = 'badge-1080p';
    const resText = (item.resolution || item.quality_label || '').toLowerCase();
    if (resText.includes('2160') || resText.includes('4k') || resText.includes('uhd')) {
      qualityClass = 'badge-2160p';
    } else if (resText.includes('720')) {
      qualityClass = 'badge-720p';
    } else if (resText.includes('480') || resText.includes('576')) {
      qualityClass = 'bg-slate-800 text-slate-400 border border-slate-700';
    }

    const qualityPill = item.quality_label 
      ? `<span class="px-2 py-0.5 rounded-md text-[11px] font-extrabold ${qualityClass}">${escapeHtml(item.quality_label)}</span>`
      : (item.resolution && item.resolution !== 'Unknown' ? `<span class="px-2 py-0.5 rounded-md text-[11px] font-extrabold ${qualityClass}">${escapeHtml(item.resolution)}</span>` : '');

    const hdrPill = item.hdr 
      ? `<span class="px-2 py-0.5 rounded-md badge-hdr text-[11px] font-bold flex items-center gap-1"><i data-lucide="sun" class="w-3 h-3 text-amber-400"></i><span>${escapeHtml(item.hdr)}</span></span>` 
      : '';

    const audioPill = item.audio 
      ? `<span class="px-2 py-0.5 rounded-md badge-audio text-[11px] font-semibold flex items-center gap-1"><i data-lucide="volume-2" class="w-3 h-3 text-indigo-400"></i><span>${escapeHtml(item.audio)}</span></span>` 
      : '';

    const codecPill = item.codec 
      ? `<span class="px-2 py-0.5 rounded-md badge-codec text-[11px] font-medium">${escapeHtml(item.codec)}</span>` 
      : '';

    // TV Season / Episode pill
    let tvPill = '';
    const titleUpper = (item.title || '');
    const m_ep = titleUpper.match(/\b(S\d{1,2}E\d{1,3})\b/i);
    const m_pack = titleUpper.match(/\b(Season[\s._-]?\d{1,2}|S\d{1,2}\b(?!\s*E\d)|Complete[\s._-]?Series)\b/i);
    if (m_ep) {
      tvPill = `<span class="px-2 py-0.5 rounded-md bg-indigo-950/80 text-indigo-300 border border-indigo-500/40 text-[11px] font-bold">📺 ${m_ep[1].toUpperCase()}</span>`;
    } else if (m_pack) {
      tvPill = `<span class="px-2 py-0.5 rounded-md bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 text-[11px] font-bold">📦 ${m_pack[1].replace(/[\._-]/g, ' ')}</span>`;
    }

    const groupPill = item.release_group 
      ? `<span class="px-2 py-0.5 rounded-md bg-slate-900/90 text-cyan-400 border border-cyan-500/20 text-[11px] font-mono font-bold">-${escapeHtml(item.release_group)}</span>` 
      : '';

    // Seeders Badge Color
    const seeders = item.seeders || 0;
    const seedersClass = seeders >= 25 
      ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/30' 
      : (seeders >= 5 ? 'bg-blue-950/80 text-blue-300 border-blue-500/30' : 'bg-amber-950/80 text-amber-300 border-amber-500/30');

    const btnLabel = isCloudCached
      ? (m_ep ? `⚡ Grab ${m_ep[1].toUpperCase()}` : (m_pack ? `⚡ Grab Pack` : `⚡ 1-Click Grab`))
      : (m_ep ? `Enqueue ${m_ep[1].toUpperCase()}` : `Enqueue`);
    const releaseYear = (item.title.match(/\b(19|20)\d{2}\b/) || [])[0] || null;

    card.innerHTML = `
      <div class="flex-1 flex flex-col gap-2 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          ${badgeHtml}
          ${tvPill}
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

        <div class="flex items-center gap-1.5 shrink-0">
          ${isInstantCached ? `
            <button onclick="openStreamPlayer({ title: '${escapeJs(item.title)}', year: ${releaseYear || 'null'}, domain: '${state.searchDomain}', season: ${item.season || 0}, episode: ${item.episode || 0}, reference_id: '${item.browser_stream_reference_id || item.stream_reference_id || item.reference_id}' })" class="px-3 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-white font-bold text-xs flex items-center gap-1.5 transition active:scale-95 shrink-0 shadow-md shadow-cyan-500/20" title="Stream the verified browser-compatible release">
              <i data-lucide="play" class="w-3.5 h-3.5 fill-white"></i>
              <span>Stream</span>
            </button>
          ` : isExternalCached ? `
            <button onclick="openStreamPlayer({ title: '${escapeJs(item.title)}', year: ${releaseYear || 'null'}, domain: '${state.searchDomain}', season: ${item.season || 0}, episode: ${item.episode || 0}, reference_id: '${item.reference_id}' })" class="px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs flex items-center gap-1.5 transition active:scale-95 shrink-0 shadow-md" title="Open the cached release with an external player">
              <i data-lucide="monitor-play" class="w-3.5 h-3.5"></i>
              <span>External</span>
            </button>
          ` : `
            <button onclick="cacheToCloud('${escapeJs(item.magnet_url || '')}', '${escapeJs(item.title)}', '${state.searchDomain}', ${item.season || 0}, '${item.reference_id}', ${(item.title.match(/\b(19|20)\d{2}\b/) || [])[0] || 'null'})" class="px-3 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 font-bold text-xs flex items-center gap-1.5 transition active:scale-95 shrink-0" title="Cache this release in AllDebrid for instant downloading">
              <i data-lucide="cloud" class="w-3.5 h-3.5"></i>
              <span>Cache AD</span>
            </button>
          `}
          <button onclick="onSearchReleaseClick('${item.reference_id}', '${escapeJs(item.title)}', ${isCloudCached})" class="px-3.5 py-2 rounded-xl ${isCloudCached ? 'bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white font-extrabold shadow-lg shadow-emerald-500/20' : 'bg-surface-hover hover:bg-slate-700 text-slate-200 border border-surface-border font-bold'} text-xs flex items-center gap-1.5 transition active:scale-95 shrink-0" title="Queue download to Local Disk via IDM">
            <i data-lucide="${isInstantCached ? 'zap' : (isCloudCached ? 'cloud' : 'download')}" class="w-3.5 h-3.5 ${isInstantCached ? 'fill-white' : ''}"></i>
            <span>${isCloudCached ? 'Grab' : 'Queue'}</span>
          </button>
        </div>
      </div>
    `;

    container.appendChild(card);
  });

  if (window.lucide) lucide.createIcons();
}

async function onDetailIngestClick(item) {
  const target = item || state.currentDetailItem;
  if (!target) return;
  const targetYear = target.year || (target.release_date ? parseInt(target.release_date.substring(0, 4)) : null);
  showToast(`⚡ Resolving 1-click grab for "${target.title}"${targetYear ? ` (${targetYear})` : ''}...`, 'info');
  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: target.title,
        year: targetYear,
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

    // Add Complete Series Run Boxset Tab
    if (seasons.length > 1) {
      const allBtn = document.createElement('button');
      allBtn.id = 'tv-season-tab-0';
      allBtn.className = 'px-3 py-1.5 rounded-xl font-bold text-xs transition flex items-center gap-1.5 shrink-0 bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border';
      allBtn.innerHTML = `
        <i data-lucide="package" class="w-3.5 h-3.5 text-cyan-400"></i>
        <span>📦 Complete Series Run</span>
      `;
      allBtn.onclick = () => switchTVSeasonTab(0);
      tabs.appendChild(allBtn);
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
  loadSeasonCacheStatus(state.tvManifest.title, state.activeTVSeason, state.tvManifest.domain || state.activeDomain);
}

function switchTVSeasonTab(seasonNum) {
  state.activeTVSeason = seasonNum;
  if (!state.tvManifest) return;

  // Update active styling on tabs (including Complete Series tab 0)
  const allTab0 = document.getElementById('tv-season-tab-0');
  if (allTab0) {
    allTab0.className = `px-3 py-1.5 rounded-xl font-bold text-xs transition flex items-center gap-1.5 shrink-0 ${
      seasonNum === 0
        ? 'bg-cyan-500 text-white shadow-md shadow-cyan-500/25'
        : 'bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border'
    }`;
  }

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
  if (packBtnLabel) {
    packBtnLabel.innerText = seasonNum === 0 ? '⚡ Ingest Complete Series Pack' : `⚡ Ingest Season ${seasonNum} Pack`;
  }

  renderActiveSeasonEpisodes();
  loadSeasonCacheStatus(state.tvManifest.title, seasonNum, state.tvManifest.domain || state.activeDomain);
}

async function loadSeasonCacheStatus(title, seasonNum, domain) {
  if (!title || seasonNum === undefined || seasonNum === null) return;
  const banner = document.getElementById('tv-season-cache-banner');
  const cacheKey = `${title}_${seasonNum}_${domain}`;

  if (!state.seasonCacheMap) state.seasonCacheMap = {};

  if (!state.seasonCacheMap[cacheKey]) {
    if (banner) {
      banner.innerHTML = `
        <div class="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs flex items-center justify-between gap-3 text-slate-400 shadow-sm">
          <div class="flex items-center gap-2">
            <div class="w-3.5 h-3.5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin"></div>
            <span>Inspecting AllDebrid instant cache & Prowlarr indexers for Season ${seasonNum}...</span>
          </div>
        </div>
      `;
    }

    try {
      const res = await fetch(`/api/tv/season-cache?title=${encodeURIComponent(title)}&season=${seasonNum}&domain=${encodeURIComponent(domain)}`);
      const data = await res.json();
      if (data.ok) {
        state.seasonCacheMap[cacheKey] = data;
      }
    } catch (err) {
      console.error("Failed to load season cache status:", err);
    }
  }

  renderActiveSeasonEpisodes();
}

function renderActiveSeasonEpisodes() {
  const checklist = document.getElementById('tv-episodes-checklist');
  const banner = document.getElementById('tv-season-cache-banner');
  if (!checklist || !state.tvManifest) return;

  const currentSeason = (state.tvManifest.seasons || []).find((s) => s.season_number === state.activeTVSeason);
  checklist.innerHTML = '';

  const cacheKey = `${state.tvManifest.title}_${state.activeTVSeason}_${state.tvManifest.domain || state.activeDomain}`;
  const cacheData = state.seasonCacheMap ? state.seasonCacheMap[cacheKey] : null;

  // Render Season Cache Banner
  if (banner) {
    if (cacheData && cacheData.ok) {
      const pack = cacheData.season_pack;
      const isCompleteRun = state.activeTVSeason === 0;
      if (pack && pack.cached) {
        banner.innerHTML = `
          <div class="p-3 rounded-xl bg-gradient-to-r from-emerald-950/70 via-teal-950/40 to-slate-900 border border-emerald-500/50 text-xs flex items-center justify-between gap-3 shadow-lg">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="p-1 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-black text-[10px] flex items-center gap-1 shrink-0">
                <i data-lucide="zap" class="w-3.5 h-3.5 text-emerald-400 fill-emerald-400"></i> ${isCompleteRun ? '⚡ CACHED COMPLETE SERIES' : '⚡ CACHED SEASON PACK'}
              </span>
              <div class="min-w-0">
                <p class="font-bold text-emerald-200 truncate">${escapeHtml(pack.title)}</p>
                <p class="text-[11px] text-slate-400">${pack.resolution} • ${pack.size_formatted || 'Full Boxset'} • 0-second AllDebrid RAM Grab</p>
              </div>
            </div>
            <button onclick="onIngestActiveSeasonPack('${pack.reference_id}')" class="px-3.5 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-black font-black text-xs shrink-0 shadow-md flex items-center gap-1 transition active:scale-95">
              <i data-lucide="zap" class="w-3.5 h-3.5 fill-black"></i> ${isCompleteRun ? 'Grab Entire Run' : 'Grab Pack'}
            </button>
          </div>
        `;
      } else if (pack && !pack.cached) {
        banner.innerHTML = `
          <div class="p-3 rounded-xl bg-slate-900/90 border border-amber-500/40 text-xs flex items-center justify-between gap-3 shadow-md">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="p-1 rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/40 font-bold text-[10px] flex items-center gap-1 shrink-0">
                <i data-lucide="download-cloud" class="w-3.5 h-3.5 text-amber-400"></i> ${isCompleteRun ? 'P2P COMPLETE SERIES' : 'P2P PACK'}
              </span>
              <div class="min-w-0">
                <p class="font-bold text-amber-200 truncate">${escapeHtml(pack.title)}</p>
                <p class="text-[11px] text-slate-400">${pack.resolution} • ${pack.size_formatted || ''} • ${pack.seeders} Seeds (Uncached)</p>
              </div>
            </div>
            <button onclick="onIngestActiveSeasonPack('${pack.reference_id}')" class="px-3 py-1.5 rounded-lg bg-surface-card hover:bg-slate-700 text-slate-200 border border-surface-border font-bold text-xs shrink-0 flex items-center gap-1">
              <i data-lucide="download" class="w-3 h-3"></i> ${isCompleteRun ? 'Queue Entire Run' : 'Queue Pack'}
            </button>
          </div>
        `;
      } else {
        banner.innerHTML = `
          <div class="p-2.5 rounded-xl bg-slate-900/70 border border-slate-800 text-xs flex items-center gap-2 text-slate-400">
            <i data-lucide="info" class="w-4 h-4 text-slate-500 shrink-0"></i>
            <span>${isCompleteRun ? 'No single complete series boxset found on indexers. Individual season packs and episodes are available in the tabs above.' : 'No full season pack found on indexers. Individual episode downloads are indexed below.'}</span>
          </div>
        `;
      }
    }
  }

  let episodesToRender = [];
  if (state.activeTVSeason === 0) {
    (state.tvManifest.seasons || []).forEach((s) => {
      (s.episodes || []).forEach((ep) => {
        episodesToRender.push({ ...ep, season_number: s.season_number });
      });
    });
  } else {
    episodesToRender = (currentSeason && currentSeason.episodes) ? currentSeason.episodes.map((ep) => ({ ...ep, season_number: state.activeTVSeason })) : [];
  }

  if (episodesToRender.length === 0) {
    checklist.innerHTML = '<div class="p-8 text-center text-slate-400 text-sm">No episodes listed.</div>';
    if (window.lucide) lucide.createIcons();
    return;
  }

  const epCacheMap = (cacheData && cacheData.episode_cache_map) ? cacheData.episode_cache_map : {};
  const isPackCached = bool(cacheData && cacheData.season_pack && cacheData.season_pack.cached);

  episodesToRender.forEach((ep) => {
    const sNum = ep.season_number;
    const epKey = `${sNum}_${ep.episode_number}`;
    const isOwned = ep.owned || false;
    const isSelected = state.selectedTVEpisodes.has(epKey);
    const epCachedInfo = epCacheMap[ep.episode_number];

    const row = document.createElement('div');
    row.className = `p-3 rounded-xl border transition flex items-center justify-between gap-3 ${
      isOwned
        ? 'bg-emerald-950/20 border-emerald-500/30 text-slate-300 opacity-80'
        : isSelected
        ? 'bg-cyan-950/40 border-cyan-500/50 text-white'
        : 'bg-surface-hover/60 border-surface-border hover:border-slate-600 text-slate-200'
    }`;

    let cacheBadgeHtml = '';
    if (isOwned) {
      cacheBadgeHtml = '<span class="text-[11px] font-bold px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1"><i data-lucide="check" class="w-3 h-3"></i> In Plex</span>';
    } else if (epCachedInfo && epCachedInfo.cached) {
      cacheBadgeHtml = '<span class="text-[10px] font-black px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/50 flex items-center gap-1 shadow-sm"><i data-lucide="zap" class="w-3 h-3 fill-emerald-400 text-emerald-400"></i> ⚡ Cached Ep</span>';
    } else if (isPackCached) {
      cacheBadgeHtml = `<span class="text-[10px] font-black px-2 py-0.5 rounded-md bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 flex items-center gap-1"><i data-lucide="zap" class="w-3 h-3 fill-cyan-400 text-cyan-400"></i> ⚡ In ${state.activeTVSeason === 0 ? 'Series Boxset' : 'Cached Pack'}</span>`;
    } else if (epCachedInfo && !epCachedInfo.cached) {
      cacheBadgeHtml = `<span class="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/30">⏳ P2P (${epCachedInfo.seeders || 0}s)</span>`;
    } else {
      cacheBadgeHtml = '<span class="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 border border-slate-700">Missing</span>';
    }

    row.innerHTML = `
      <div class="flex items-center gap-3 min-w-0">
        <input type="checkbox" ${isOwned ? 'disabled checked' : isSelected ? 'checked' : ''} onchange="toggleEpisodeCheckbox(${sNum}, ${ep.episode_number})" class="w-4 h-4 rounded text-cyan-500 border-surface-border focus:ring-0 cursor-pointer ${isOwned ? 'opacity-50 cursor-not-allowed' : ''}">
        
        <span class="text-xs font-black px-2 py-0.5 rounded bg-surface-card border border-surface-border shrink-0 text-slate-300">
          S${String(sNum).padStart(2, '0')}E${String(ep.episode_number).padStart(2, '0')}
        </span>

        <div class="min-w-0">
          <p class="text-xs sm:text-sm font-bold truncate">${escapeHtml(ep.title || `Episode ${ep.episode_number}`)}</p>
          <p class="text-[11px] text-slate-400 truncate">${ep.air_date ? `Aired: ${ep.air_date}` : ''} ${ep.runtime_min ? `• ${ep.runtime_min}m` : ''}</p>
        </div>
      </div>

      <div class="shrink-0 flex items-center gap-2">
        ${cacheBadgeHtml}
      </div>
    `;

    checklist.appendChild(row);
  });

  if (window.lucide) lucide.createIcons();
  updateSelectedCountLabel();
}

function bool(val) {
  return !!val;
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

function selectAllMissingWholeShow() {
  if (!state.tvManifest || !state.tvManifest.seasons) return;
  let addedCount = 0;
  state.tvManifest.seasons.forEach((s) => {
    (s.episodes || []).forEach((ep) => {
      if (!ep.owned) {
        state.selectedTVEpisodes.add(`${s.season_number}_${ep.episode_number}`);
        addedCount++;
      }
    });
  });
  renderActiveSeasonEpisodes();
  updateSelectedCountLabel();
  showToast(`⚡ Selected all ${addedCount} missing episodes across ${state.tvManifest.seasons.length} seasons.`, 'info');
}

function deselectAllEpisodes() {
  state.selectedTVEpisodes.clear();
  renderActiveSeasonEpisodes();
  updateSelectedCountLabel();
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

  // Group selected episodes by season
  const seasonGroups = {};
  state.selectedTVEpisodes.forEach((epKey) => {
    const [sStr, epStr] = epKey.split('_');
    const sNum = parseInt(sStr);
    const epNum = parseInt(epStr);
    if (!seasonGroups[sNum]) seasonGroups[sNum] = [];
    seasonGroups[sNum].push(epNum);
  });

  const totalEpisodes = state.selectedTVEpisodes.size;
  const seasonsCount = Object.keys(seasonGroups).length;

  showToast(`⚡ Ingesting ${totalEpisodes} episodes across ${seasonsCount} season${seasonsCount === 1 ? '' : 's'} for "${state.tvManifest.title}"...`, "info");
  closeTVEpisodePickerModal();

  for (const [sNumStr, epList] of Object.entries(seasonGroups)) {
    const sNum = parseInt(sNumStr);
    try {
      const res = await fetch('/api/tv/ingest-episodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tmdb_id: state.tvManifest.tmdb_id,
          title: state.tvManifest.title,
          domain: state.tvManifest.domain || state.activeDomain,
          season: sNum,
          episode_numbers: epList,
          pack_mode: false
        })
      });
      const data = await res.json();
      if (data.ok) {
        showToast(`⚡ Queued: ${state.tvManifest.title} Season ${sNum} (${epList.length} ep${epList.length === 1 ? '' : 's'})`, "success");
      } else {
        showToast(`Season ${sNum} queue failed: ${data.error || 'Unknown error'}`, "error");
      }
    } catch (err) {
      console.error("TV episode download error for season:", sNum, err);
    }
  }
  setTimeout(loadSidebarHistory, 1500);
}

async function onIngestActiveSeasonPack(customRefId) {
  if (!state.tvManifest) return;
  const isComplete = state.activeTVSeason === 0;
  const label = isComplete ? 'Complete Series Run' : `Season ${state.activeTVSeason} Pack`;
  showToast(`⚡ Ingesting ${label} for "${state.tvManifest.title}"...`, "info");
  closeTVEpisodePickerModal();

  try {
    const res = await fetch('/api/tv/ingest-episodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reference_id: customRefId || null,
        tmdb_id: state.tvManifest.tmdb_id,
        title: state.tvManifest.title,
        domain: state.tvManifest.domain || state.activeDomain,
        season: state.activeTVSeason,
        pack_mode: true
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message || `⚡ Queued: ${state.tvManifest.title} (${label})`, "success");
      setTimeout(loadSidebarHistory, 1500);
    } else {
      showToast(`Ingest failed: ${data.error || 'No matching packs found'}`, "error");
    }
  } catch (err) {
    console.error("TV pack download error:", err);
    showToast("Failed to queue TV pack.", "error");
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
    const diagModal = document.getElementById('ingest-diag-modal');
    if (diagModal && !diagModal.classList.contains('hidden')) {
      closeIngestDiagnosticModal();
      return;
    }
    const tvModal = document.getElementById('tv-ingest-modal');
    if (tvModal && !tvModal.classList.contains('hidden')) {
      closeTVEpisodePickerModal();
      return;
    }
    const searchModal = document.getElementById('search-modal');
    if (searchModal && !searchModal.classList.contains('hidden')) {
      closeSearchModal();
      return;
    }
    const mediaModal = document.getElementById('media-modal');
    if (mediaModal && !mediaModal.classList.contains('hidden')) {
      closeModal();
    }
  }
});

// Modal Backdrop Click-to-Close
[
  { id: 'media-modal', closeFn: closeModal },
  { id: 'search-modal', closeFn: closeSearchModal },
  { id: 'tv-ingest-modal', closeFn: closeTVEpisodePickerModal },
  { id: 'ingest-diag-modal', closeFn: closeIngestDiagnosticModal }
].forEach(({ id, closeFn }) => {
  const modalEl = document.getElementById(id);
  if (modalEl) {
    modalEl.classList.add('modal-backdrop-clickable');
    modalEl.addEventListener('click', (e) => {
      if (e.target === modalEl) {
        closeFn();
      }
    });
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

// Helper for formatting UTC SQLite timestamps relative to current time and in EST
function formatESTTime(timeStr) {
  if (!timeStr) return '<span class="text-slate-500">-</span>';
  let utcStr = timeStr;
  if (!timeStr.endsWith('Z') && !timeStr.includes('+')) {
    utcStr = timeStr.replace(' ', 'T') + 'Z';
  }
  const d = new Date(utcStr);
  if (isNaN(d.getTime())) return escapeHtml(timeStr);

  const now = new Date();
  const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);

  let rel = '';
  if (diffSec < 60) rel = 'Just now';
  else if (diffSec < 3600) rel = `${Math.floor(diffSec / 60)}m ago`;
  else if (diffSec < 86400) rel = `${Math.floor(diffSec / 3600)}h ago`;
  else rel = `${Math.floor(diffSec / 86400)}d ago`;

  let estTime = '';
  try {
    estTime = d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    });
  } catch (e) {
    estTime = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  return `<span class="text-slate-200 font-semibold">${rel}</span> <span class="text-[10px] text-slate-400">(${estTime} EST)</span>`;
}


// =========================================================================
// BLOCK 5.4: GLASSMORPHIC CLOUD STREAMING PLAYER & VIEW TRACKING
// =========================================================================

state.activeStream = null;
let streamHeartbeatTimer = null;

function formatDuration(sec) {
  if (!sec || isNaN(sec) || sec <= 0) return '00:00';
  const totalSec = Math.floor(sec);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

async function openStreamPlayer(config) {
  if (!config || !config.title) {
    showToast("Missing media title for streaming", "warning");
    return;
  }
  const modal = document.getElementById('stream-player-modal');
  const video = document.getElementById('cloud-video-player');
  const source = document.getElementById('cloud-video-source');
  const loading = document.getElementById('player-loading-overlay');
  const titleEl = document.getElementById('player-media-title');
  const releaseEl = document.getElementById('player-release-info');
  const fileSelect = document.getElementById('player-file-select');
  const singleFileBadge = document.getElementById('player-single-file-badge');

  if (!modal || !video) {
    console.error("[StreamPlayer] Modal or video element not found in DOM!");
    return;
  }

  state.activeStream = null;
  setStreamPlayerState('checking');
  showToast(`⏳ Searching AllDebrid for an instant stream of "${config.title}"...`, "info");

  // Show modal immediately with loading state
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  const uncachedOverlay = document.getElementById('player-uncached-overlay');
  if (uncachedOverlay) {
    uncachedOverlay.classList.add('hidden');
    uncachedOverlay.style.display = 'none';
  }
  if (loading) {
    loading.classList.remove('hidden');
    loading.style.display = 'flex';
  }
  if (titleEl) titleEl.innerText = config.title || 'Loading Stream...';
  if (releaseEl) releaseEl.innerText = 'Searching AllDebrid for instant-cached releases...';

  // Stop previous playback
  try {
    video.pause();
    video.currentTime = 0;
  } catch (e) {}
  if (streamHeartbeatTimer) clearInterval(streamHeartbeatTimer);

  try {
    const res = await fetch('/api/stream/unlock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: config.title,
        year: config.year || null,
        domain: config.domain || state.activeDomain || 'movies',
        season: config.season || 0,
        episode: config.episode || 0,
        reference_id: config.reference_id,
        magnet_url: config.magnet_url,
        file_id: config.file_id,
        poster_url: config.poster_url
      })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.ok || !data.stream_url) {
      if (data.cached === false) {
        // Show uncached overlay with 1-click cloud cache button
        if (loading) {
          loading.classList.add('hidden');
          loading.style.display = 'none';
        }
        const uncachedMsg = document.getElementById('player-uncached-message');
        const cacheCloudBtn = document.getElementById('btn-player-cache-cloud');
        if (uncachedMsg) {
          uncachedMsg.innerText = data.error || `"${config.title}" is not instant-cached on AllDebrid yet. Click below to download it to AllDebrid cloud storage first.`;
        }
        if (cacheCloudBtn) {
          cacheCloudBtn.onclick = () => {
            cacheToCloud(data.magnet_url || config.magnet_url, data.title || config.title, data.domain || config.domain, data.season || config.season, config.reference_id, config.year);
            closeStreamPlayer();
            switchTab('history');
            switchHistorySubTab('cloud_transfers');
          };
        }
        if (uncachedOverlay) {
          uncachedOverlay.classList.remove('hidden');
          uncachedOverlay.style.display = 'flex';
        }
        setStreamPlayerState('unavailable');
        if (window.lucide) lucide.createIcons();
        return;
      }
      throw new Error(data.error || 'Failed to resolve streaming URL');
    }

    state.activeStream = {
      id: data.stream_id,
      stream_url: data.stream_url,
      title: data.title || config.title,
      domain: data.domain || config.domain,
      season: data.season || 0,
      episode: data.episode || 0,
      year: config.year || null,
      filename: data.filename,
      reference_id: config.reference_id,
      all_files: data.all_files || []
    };
    const browserStreamReady = data.browser_stream_ready === true;
    setStreamPlayerState(browserStreamReady ? 'ready' : 'external');

    if (titleEl) {
      let epTag = '';
      if (data.season > 0 && data.episode > 0) {
        epTag = ` (S${String(data.season).padStart(2, '0')}E${String(data.episode).padStart(2, '0')})`;
      }
      titleEl.innerText = `${data.title}${epTag}`;
    }
    if (releaseEl) {
      const sizeStr = data.filesize ? `${(data.filesize / 1073741824).toFixed(2)} GB` : '';
      releaseEl.innerText = `${data.filename || ''} ${sizeStr ? `• ${sizeStr}` : ''} • Direct HTTPS Stream`;
    }

    // Populate file switcher if multi-file pack
    if (fileSelect && singleFileBadge) {
      const files = data.all_files || [];
      if (files.length > 1) {
        fileSelect.innerHTML = '';
        files.forEach(f => {
          const opt = document.createElement('option');
          opt.value = f.id;
          opt.innerText = f.name;
          if (f.id === data.file_id) opt.selected = true;
          fileSelect.appendChild(opt);
        });
        fileSelect.classList.remove('hidden');
        singleFileBadge.classList.add('hidden');
      } else {
        fileSelect.classList.add('hidden');
        singleFileBadge.classList.remove('hidden');
        singleFileBadge.innerText = 'Direct Cloud Stream';
      }
    }

    // Detect codec from resolved filename
    const resolvedFilename = (data.filename || '').toLowerCase();
    const streamIsHEVC = resolvedFilename.includes('x265') || resolvedFilename.includes('hevc') || resolvedFilename.includes('h265') || resolvedFilename.includes('h.265') || resolvedFilename.includes('10bit');

    if (!browserStreamReady) {
      // Unsupported container/audio/video combination: keep it out of native
      // HTML5 playback so users do not get video with silent audio.
      if (loading) {
        loading.classList.add('hidden');
        loading.style.display = 'none';
      }

      // Build external player overlay
      const uncachedOverlay = document.getElementById('player-uncached-overlay');
      const uncachedMsg = document.getElementById('player-uncached-message');
      const cacheCloudBtn = document.getElementById('btn-player-cache-cloud');
      const formatLabel = streamIsHEVC ? 'HEVC / 10-Bit' : 'External Player Recommended';
      const formatReason = streamIsHEVC
        ? 'This release is encoded in HEVC / x265 (10-bit).'
        : 'This release does not advertise the browser-safe MP4 + H.264 + AAC/MP3 combination. It may contain an MKV container or an audio track such as DDP/DTS that browsers cannot decode reliably.';

      if (uncachedMsg) {
        uncachedMsg.innerHTML = `
          <div class="text-center space-y-3 max-w-lg mx-auto">
            <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-bold">
              <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
              <span>0-Second Stream Ready (${formatLabel})</span>
            </div>
            <p class="text-slate-300 text-xs leading-relaxed">
              ${formatReason} Use VLC, Infuse, or PotPlayer for reliable audio and video playback.
            </p>
            <div class="p-3 bg-slate-900/90 border border-slate-700/80 rounded-xl space-y-2 text-left">
              <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                <span>Direct Stream Link</span>
                <span class="text-[10px] text-emerald-400 font-medium">⚡ Zero-Buffer AllDebrid CDN</span>
              </div>
              <div class="flex items-center gap-2">
                <input id="external-stream-url" type="text" readonly value="${data.stream_url}" class="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-xs text-slate-200 font-mono select-all" onclick="this.select()">
                <button onclick="navigator.clipboard.writeText('${data.stream_url.replace(/'/g, "\\'")}'); showToast('📋 Direct Stream URL copied to clipboard!', 'info')" class="px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition flex items-center gap-1 shrink-0">
                  <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                  <span>Copy</span>
                </button>
              </div>
              <div class="text-[10px] text-slate-400 italic">
                💡 <strong>VLC Stream:</strong> Press <kbd class="px-1.5 py-0.5 bg-slate-800 rounded border border-slate-700 font-mono text-slate-300">Ctrl + N</kbd> in VLC, paste this URL, and press Enter.
              </div>
            </div>
            <div class="flex items-center gap-2 pt-1">
              <a href="${data.stream_url}" target="_blank" download="${escapeHtml(data.filename || 'media')}" class="flex-1 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs text-center transition flex items-center justify-center gap-1.5 shadow-md">
                <i data-lucide="download" class="w-4 h-4"></i>
                <span>Download / Save File</span>
              </a>
              <button onclick="launchExternalPlayer('vlc')" class="px-4 py-2.5 rounded-xl bg-surface-card hover:bg-slate-700 text-slate-300 border border-surface-border font-bold text-xs transition flex items-center justify-center gap-1.5">
                <i data-lucide="monitor-play" class="w-4 h-4 text-cyan-400"></i>
                <span>Open in local VLC</span>
              </button>
            </div>
          </div>
        `;
      }
      if (cacheCloudBtn) cacheCloudBtn.style.display = 'none';

      if (uncachedOverlay) {
        uncachedOverlay.classList.remove('hidden');
        uncachedOverlay.style.display = 'flex';
      }

      if (window.lucide) lucide.createIcons();
      showToast(`⚡ Stream ready — use an external player for reliable audio: "${config.title}"`, 'info');
      return;
    }

    // H.264 / browser-compatible: proceed with native HTML5 playback
    // Attach stream URL to video player
    video.src = data.stream_url;
    source.src = data.stream_url;
    source.type = data.mime_type || 'video/mp4';
    video.load();

    video.onerror = () => {
      if (loading) {
        loading.classList.add('hidden');
        loading.style.display = 'none';
      }
      showToast("⚠️ Browser video decoding notice. Click 🚀 VLC or 🎬 PotPlayer above to stream directly in hardware video player!", "warning");
    };

    // Resume from initial progress
    if (data.initial_progress && data.initial_progress > 5) {
      video.onloadedmetadata = () => {
        video.currentTime = data.initial_progress;
        showToast(`Resumed playback at ${formatDuration(data.initial_progress)}`, 'info');
      };
    }

    video.play().catch(e => console.log("Autoplay notice:", e));
    if (loading) {
      loading.classList.add('hidden');
      loading.style.display = 'none';
    }

    // Start progress heartbeat timer (every 8 seconds)
    streamHeartbeatTimer = setInterval(sendStreamHeartbeat, 8000);

  } catch (err) {
    console.error("Stream unlock error:", err);
    if (loading) {
      loading.classList.add('hidden');
      loading.style.display = 'none';
    }
    setStreamPlayerState('error');
    showToast(`Streaming error: ${err.message}`, 'error');
  }
}

function setStreamPlayerState(status) {
  const statusConfig = {
    checking: {
      icon: 'search',
      label: '⏳ Searching AllDebrid...',
      className: 'text-slate-400',
      title: 'Searching for an instant-cached stream...'
    },
    ready: {
      icon: 'zap',
      label: '⚡ Instant Cloud Stream',
      className: 'text-emerald-400',
      title: 'Open the verified instant stream'
    },
    external: {
      icon: 'monitor-play',
      label: '🖥️ External Player Ready',
      className: 'text-indigo-300',
      title: 'Open the verified stream in VLC, Infuse, or PotPlayer'
    },
    unavailable: {
      icon: 'cloud-off',
      label: '⏳ Not Instant-Cached',
      className: 'text-amber-400',
      title: 'No verified instant-cached stream was found'
    },
    error: {
      icon: 'alert-triangle',
      label: '⚠️ Stream Unavailable',
      className: 'text-rose-400',
      title: 'The stream could not be confirmed'
    }
  };
  const config = statusConfig[status] || statusConfig.checking;
  const isReady = status === 'ready' || status === 'external';

  const buttonStyles = {
    'btn-player-vlc': {
      ready: ['text-orange-400', 'hover:bg-orange-950/40', 'border-orange-500/30'],
      disabled: ['text-slate-500', 'border-slate-700/60']
    },
    'btn-player-infuse': {
      ready: ['text-rose-400', 'hover:bg-rose-950/40', 'border-rose-500/30'],
      disabled: ['text-slate-500', 'border-slate-700/60']
    },
    'btn-player-potplayer': {
      ready: ['text-amber-400', 'hover:bg-amber-950/40', 'border-amber-500/30'],
      disabled: ['text-slate-500', 'border-slate-700/60']
    },
    'btn-player-copy': {
      ready: ['text-slate-300', 'hover:bg-slate-700'],
      disabled: ['text-slate-500']
    },
    'btn-player-download': {
      ready: ['bg-gradient-to-r', 'from-cyan-500', 'to-blue-600', 'hover:from-cyan-400', 'hover:to-blue-500', 'text-white', 'shadow-md', 'shadow-cyan-500/20', 'active:scale-95'],
      disabled: ['bg-slate-800', 'text-slate-500', 'border', 'border-slate-700/60']
    }
  };

  Object.entries(buttonStyles).forEach(([id, styles]) => {
    const button = document.getElementById(id);
    if (!button) return;
    button.disabled = !isReady;
    button.setAttribute('aria-disabled', String(!isReady));
    button.title = config.title;
    button.classList.toggle('opacity-50', !isReady);
    button.classList.toggle('cursor-not-allowed', !isReady);
    [...styles.ready, ...styles.disabled].forEach((className) => button.classList.remove(className));
    (isReady ? styles.ready : styles.disabled).forEach((className) => button.classList.add(className));
  });

  const statusTag = document.getElementById('player-status-tag');
  if (statusTag) {
    statusTag.className = `${config.className} font-bold flex items-center gap-1`;
    statusTag.innerHTML = `<i data-lucide="${config.icon}" class="w-3.5 h-3.5"></i><span>${config.label}</span>`;
    if (window.lucide) lucide.createIcons();
  }
}

async function sendStreamHeartbeat(isCompleted = false) {
  const video = document.getElementById('cloud-video-player');
  if (!video || !state.activeStream) return;

  const curTime = video.currentTime;
  const dur = video.duration || 0;
  if (isNaN(curTime) || curTime < 1) return;

  try {
    await fetch('/api/stream/progress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: state.activeStream.id,
        progress_seconds: curTime,
        duration_seconds: dur,
        completed: isCompleted || (dur > 0 && (curTime / dur) >= 0.9)
      })
    });
  } catch (e) {
    // Non-blocking telemetry error
  }
}

function closeStreamPlayer() {
  const modal = document.getElementById('stream-player-modal');
  const video = document.getElementById('cloud-video-player');
  const loading = document.getElementById('player-loading-overlay');
  const uncachedOverlay = document.getElementById('player-uncached-overlay');

  if (streamHeartbeatTimer) {
    clearInterval(streamHeartbeatTimer);
    streamHeartbeatTimer = null;
  }

  if (video) {
    sendStreamHeartbeat();
    try {
      video.pause();
      video.src = '';
    } catch (e) {}
  }

  if (modal) {
    modal.classList.add('hidden');
    modal.style.display = 'none';
  }
  if (loading) {
    loading.classList.add('hidden');
    loading.style.display = 'none';
  }
  if (uncachedOverlay) {
    uncachedOverlay.classList.add('hidden');
    uncachedOverlay.style.display = 'none';
  }
  state.activeStream = null;

  // Refresh stream history tab if visible
  const streamsView = document.getElementById('subview-history-streams');
  if (streamsView && !streamsView.classList.contains('hidden')) {
    loadStreamHistoryTable();
  }
}

function switchPlayerFile(fileId) {
  if (!state.activeStream) return;
  openStreamPlayer({
    title: state.activeStream.title,
    domain: state.activeStream.domain,
    season: state.activeStream.season,
    episode: state.activeStream.episode,
    reference_id: state.activeStream.reference_id,
    year: state.activeStream.year,
    file_id: parseInt(fileId)
  });
}

function copyCurrentStreamUrl() {
  if (!state.activeStream || !state.activeStream.stream_url) {
    showToast("No active stream URL", "warning");
    return;
  }
  navigator.clipboard.writeText(state.activeStream.stream_url)
    .then(() => showToast("📋 Stream URL copied to clipboard!", "success"))
    .catch(() => showToast("Failed to copy URL", "error"));
}

async function launchExternalPlayer(type) {
  if (!state.activeStream || !state.activeStream.stream_url) {
    showToast("No active stream available", "warning");
    return;
  }
  const url = state.activeStream.stream_url;

  if (type === 'vlc') {
    try {
      const response = await fetch('/api/player/vlc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stream_url: url })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        throw new Error(result.error || 'VLC could not be started');
      }
      showToast("🚀 VLC opened with the current stream", "success");
    } catch (error) {
      showToast(`${error.message}. Use Copy Stream URL as a fallback.`, "error");
    }
  } else if (type === 'infuse') {
    window.location.href = `infuse://x-callback-url/play?url=${encodeURIComponent(url)}`;
    showToast("🍎 Launching Infuse Player...", "info");
  } else if (type === 'potplayer') {
    window.location.href = `potplayer://${url}`;
    showToast("🎬 Launching PotPlayer...", "info");
  }
}

async function downloadCurrentStreamItem() {
  if (!state.activeStream) return;
  const { title, domain, season, reference_id } = state.activeStream;
  showToast(`⬇️ Queueing "${title}" for permanent download to Plex...`, "info");
  if (reference_id) {
    await onIngestPrewarmedItem(reference_id, title, domain, season);
  } else {
    await onDetailIngestClick({ title, domain, season });
  }
}

async function cacheToCloud(magnetUrl, title, domain, season = 0, referenceId = '', year = null) {
  showToast(`☁️ Enqueueing "${title}" to AllDebrid Cloud Downloader...`, "info");
  try {
    const res = await fetch('/api/cloud/pre-cache', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        magnet_url: magnetUrl,
        reference_id: referenceId,
        domain: domain || state.activeDomain || 'movies',
        title: title,
        season: season || 0,
        year: year || null
      })
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`☁️ Sent to AllDebrid. Once finished, it will be ready for instant downloading; browser readiness is verified separately.`, "success");
      setTimeout(loadPrewarmTable, 1500);
    } else {
      showToast(data.error || "Failed to enqueue to AllDebrid cloud.", "error");
    }
  } catch (err) {
    showToast(`Cloud caching failed: ${err.message}`, "error");
  }
}

async function prepareBrowserStream() {
  const item = state.currentDetailItem;
  if (!item) return;

  const button = document.getElementById('modal-prepare-stream-btn');
  const label = document.getElementById('modal-prepare-stream-btn-label');
  const domain = item.domain || state.activeDomain || 'movies';
  const year = item.year || (item.release_date ? parseInt(item.release_date.substring(0, 4), 10) : null);
  const season = item.stream_season || item.season || 0;
  const episode = item.episode || 0;

  if (button) {
    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');
    button.classList.add('opacity-60', 'cursor-wait');
  }
  if (label) label.innerText = '🔎 Finding Browser Copy';
  showToast(`🔎 Finding an exact browser-compatible copy of "${item.title}"...`, 'info');

  try {
    const res = await fetch('/api/stream/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        domain,
        title: item.title,
        year,
        season,
        episode
      })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `Browser preparation failed (HTTP ${res.status})`);
    }

    if (data.browser_stream_ready) {
      item.cloud_cached = true;
      item.instant_download_ready = true;
      item.browser_stream_ready = true;
      item.instant_cached = true;
      item.instant_stream_status = 'browser_ready';
      item.stream_prepare_status = 'ready';
      item.stream_reference_id = data.reference_id;
      item.browser_stream_reference_id = data.reference_id;
      item.stream_release_title = data.release_title;
      item.browser_stream_release_title = data.release_title;
      item.browser_stream_candidate = data.browser_stream_candidate || item.browser_stream_candidate;
      item.download_candidate = data.download_candidate || item.download_candidate;
      setDetailStreamButtonState(item);
      setDetailPrepareStreamButtonState(item);
      renderDetailStreamCandidates(item);
      showToast(`▶️ "${item.title}" is verified and ready in the browser.`, 'success');
      return;
    }

    item.stream_prepare_status = data.status || 'queued';
    setDetailPrepareStreamButtonState(item);
    showToast(`☁️ A browser-compatible copy of "${item.title}" is being cached in AllDebrid.`, 'success');
    pollCloudNotifications();
  } catch (err) {
    item.stream_prepare_status = 'failed';
    setDetailPrepareStreamButtonState(item);
    showToast(`${err.message} Search remains available for unrestricted IDM/Plex acquisition.`, 'error');
  }
}

async function resumeStreamSession(id, title, domain, season, episode, year = null) {
  openStreamPlayer({
    title: title,
    domain: domain,
    year: year,
    season: season,
    episode: episode
  });
}

async function downloadStreamSessionItem(title, domain, season, year = null) {
  showToast(`⬇️ Resolving local Plex grab for "${title}"...`, "info");
  await onDetailIngestClick({ title, domain, season, year });
}

async function deleteStreamSession(id) {
  try {
    await fetch(`/api/stream/history/${encodeURIComponent(id)}`, { method: 'DELETE' });
    showToast("Stream record deleted", "info");
    loadStreamHistoryTable();
  } catch (err) {
    showToast("Failed to delete record", "error");
  }
}

async function onDetailStreamClick() {
  const item = state.currentDetailItem;
  if (!item) return;
  const canStream = item.browser_stream_ready === true || item.instant_stream_status === 'external_ready';
  if (!canStream) {
    showToast('⏳ This title is not verified as browser-streamable yet.', 'info');
    return;
  }
  const title = item.title || item.name || "Unknown Media";
  closeModal();
  openStreamPlayer({
    title: title,
    domain: item.domain || state.activeDomain || 'movies',
    year: item.year || (item.release_date ? parseInt(item.release_date.substring(0, 4)) : null),
    reference_id: item.stream_reference_id || null,
    season: item.stream_season || item.season || 0,
    episode: item.episode || 0,
    poster_url: item.poster_url || (item.poster_path ? `https://image.tmdb.org/t/p/w500${item.poster_path}` : '')
  });
}

// Global Keyboard Shortcuts for Video Player
document.addEventListener('keydown', (e) => {
  const playerModal = document.getElementById('stream-player-modal');
  if (!playerModal || playerModal.classList.contains('hidden')) return;

  const video = document.getElementById('cloud-video-player');
  if (!video) return;

  if (e.key === 'Escape') {
    closeStreamPlayer();
  } else if (e.key === ' ' || e.code === 'Space') {
    e.preventDefault();
    if (video.paused) video.play();
    else video.pause();
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    video.currentTime = Math.min(video.duration || 0, video.currentTime + 10);
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    video.currentTime = Math.max(0, video.currentTime - 10);
  } else if (e.key === 'f' || e.key === 'F') {
    e.preventDefault();
    if (!document.fullscreenElement) {
      video.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }
});


// =========================================================================
// NEWLY CLOUD-CACHED NOTIFICATION CENTER & POLLING
// =========================================================================

state.knownReadyCloudTransfers = new Set();
let hasInitializedNotifications = false;

async function pollCloudNotifications() {
  try {
    const res = await fetch('/api/cloud/notifications');
    if (!res.ok) return;
    const data = await res.json();
    const notifications = data.notifications || [];
    const badge = document.getElementById('cloud-notification-badge');
    const countLabel = document.getElementById('cloud-notification-count-label');
    const listEl = document.getElementById('cloud-notification-list');

    if (badge) {
      if (notifications.length > 0) {
        badge.innerText = notifications.length;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }

    if (countLabel) {
      countLabel.innerText = `${notifications.length} Ready`;
    }

    // Check for newly completed transfers to pop alert toast
    notifications.forEach(item => {
      const itemId = String(item.id);
      if (!state.knownReadyCloudTransfers.has(itemId)) {
        state.knownReadyCloudTransfers.add(itemId);
        if (hasInitializedNotifications) {
          const capability = item.browser_stream_ready
            ? 'verified and ready to stream in the browser'
            : 'cached and ready in AllDebrid';
          showToast(`🎉 "${item.title || item.name}" is ${capability}!`, "success");
        }
      }
    });

    hasInitializedNotifications = true;

    // Populate dropdown list
    if (listEl) {
      listEl.innerHTML = '';
      if (notifications.length === 0) {
        listEl.innerHTML = `
          <div class="py-6 text-center text-slate-500 text-xs">
            <i data-lucide="bell-off" class="w-6 h-6 mx-auto mb-1.5 opacity-40"></i>
            No new cloud-cached media.
          </div>
        `;
      } else {
        notifications.slice(0, 10).forEach(n => {
          const itemEl = document.createElement('div');
          const browserReady = Boolean(n.browser_stream_ready);
          const mediaTitle = n.title || n.name || 'Unknown Media';
          const mediaDomain = n.domain || 'movies';
          const mediaYear = n.year || 'null';
          const mediaSeason = n.season || 0;
          itemEl.className = 'p-2.5 rounded-xl bg-surface-card hover:bg-surface-hover transition flex items-center justify-between gap-2 border border-surface-border/50';
          itemEl.innerHTML = `
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                <p class="font-bold text-white text-xs truncate" title="${escapeHtml(mediaTitle)}">${escapeHtml(mediaTitle)}</p>
              </div>
              <p class="text-[10px] text-slate-400 font-mono mt-0.5">${browserReady ? 'Browser Stream Ready' : 'Ready in AllDebrid'} · ${n.size_formatted || 'Cloud Ready'}</p>
            </div>
            <div class="flex items-center gap-1 shrink-0">
              ${browserReady ? `
                <button onclick="closeNotificationDropdown(); openStreamPlayer({ title: '${escapeJs(mediaTitle)}', domain: '${escapeJs(mediaDomain)}', year: ${mediaYear}, season: ${mediaSeason}, reference_id: '${escapeJs(n.reference_id || '')}' })" class="px-2 py-1 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-white font-bold text-[11px] flex items-center gap-1 shadow-sm">
                  <i data-lucide="play" class="w-3 h-3 fill-white"></i>
                  <span>Stream</span>
                </button>
              ` : `
                <button onclick="closeNotificationDropdown(); openSearchModal('${escapeJs(mediaTitle)}', '${escapeJs(mediaDomain)}')" class="px-2 py-1 rounded-lg bg-slate-700 hover:bg-slate-600 text-white font-bold text-[11px] flex items-center gap-1 shadow-sm">
                  <i data-lucide="search" class="w-3 h-3"></i>
                  <span>Search</span>
                </button>
              `}
              <button onclick="closeNotificationDropdown(); onDetailIngestClick({ title: '${escapeJs(mediaTitle)}', domain: '${escapeJs(mediaDomain)}', year: ${mediaYear}, season: ${mediaSeason} })" class="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition" title="Download to Plex">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          `;
          listEl.appendChild(itemEl);
        });
      }
      if (window.lucide) lucide.createIcons();
    }

  } catch (e) {
    // Non-blocking poll error
  }
}

function toggleNotificationDropdown() {
  const dropdown = document.getElementById('cloud-notification-dropdown');
  if (!dropdown) return;
  dropdown.classList.toggle('hidden');
  if (!dropdown.classList.contains('hidden')) {
    pollCloudNotifications();
  }
}

function closeNotificationDropdown() {
  const dropdown = document.getElementById('cloud-notification-dropdown');
  if (dropdown) dropdown.classList.add('hidden');
}

async function deleteCloudTransfer(id) {
  try {
    const res = await fetch(`/api/cloud/transfers/${encodeURIComponent(id)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.ok) {
      showToast("Cloud transfer removed", "info");
      loadCloudTransfersTable();
      pollCloudNotifications();
    }
  } catch (err) {
    showToast("Failed to delete transfer", "error");
  }
}

// Close notification dropdown when clicking outside
document.addEventListener('click', (e) => {
  const bellBtn = document.getElementById('btn-cloud-notifications');
  const dropdown = document.getElementById('cloud-notification-dropdown');
  if (dropdown && !dropdown.classList.contains('hidden')) {
    if (bellBtn && !bellBtn.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.classList.add('hidden');
    }
  }
});

// Start notification polling every 10 seconds
setInterval(pollCloudNotifications, 10000);
setTimeout(pollCloudNotifications, 1500);







