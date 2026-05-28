CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  source TEXT NOT NULL,
  title TEXT,
  summary TEXT,
  entity_type TEXT,
  entity_id TEXT,
  status TEXT,
  severity TEXT NOT NULL DEFAULT 'info',
  occurred_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  data_json TEXT
);

CREATE TABLE IF NOT EXISTS health_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_name TEXT NOT NULL,
  status TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  last_success_at TEXT,
  last_error_at TEXT,
  uptime_seconds INTEGER,
  details_json TEXT
);

CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  error_code TEXT,
  message TEXT NOT NULL,
  retryable INTEGER NOT NULL DEFAULT 0,
  severity TEXT NOT NULL DEFAULT 'error',
  occurred_at TEXT NOT NULL,
  context_json TEXT,
  stack_excerpt TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  requested_by TEXT,
  requested_from TEXT,
  started_at TEXT,
  finished_at TEXT,
  result_json TEXT,
  error_id INTEGER,
  FOREIGN KEY (error_id) REFERENCES errors(id)
);

CREATE TABLE IF NOT EXISTS tool_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_name TEXT NOT NULL,
  caller_type TEXT,
  caller_id TEXT,
  risk_level TEXT NOT NULL,
  input_json TEXT,
  output_summary_json TEXT,
  ok INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error_id INTEGER,
  FOREIGN KEY (error_id) REFERENCES errors(id)
);

CREATE TABLE IF NOT EXISTS kv_store (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (1, 'baseline_tool_friendly_schema');

-- Project specific schemas for media management
CREATE TABLE IF NOT EXISTS library_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    rating_key TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    file_path TEXT,
    size_bytes INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_results (
    id TEXT PRIMARY KEY,
    query_string TEXT NOT NULL,
    indexer TEXT NOT NULL,
    title TEXT NOT NULL,
    size_bytes INTEGER,
    seeders INTEGER,
    magnet_uri_hash TEXT NOT NULL,
    raw_json_payload TEXT
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id TEXT PRIMARY KEY,
    alldebrid_magnet_id TEXT,
    selected_file_name TEXT,
    target_dir TEXT DEFAULT 'F:\_temp\movies',
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

