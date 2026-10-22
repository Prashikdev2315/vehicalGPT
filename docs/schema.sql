-- VehicleGPT SQLite schema (contract: do not change without approval)
-- Timestamps are INTEGER Unix epoch milliseconds (UTC).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Catalog of known signals; used for alias resolution and validation of tool args
CREATE TABLE IF NOT EXISTS signal_catalog (
  signal       TEXT PRIMARY KEY,          -- canonical name, e.g. 'hvac_power'
  unit         TEXT NOT NULL,
  source       TEXT NOT NULL,             -- can | someip | vhal | qnx | adas | diag | derived
  description  TEXT,
  aliases      TEXT                       -- JSON array of synonyms
);

-- Raw signals (warm tier, ~48 h retention)
CREATE TABLE IF NOT EXISTS signals (
  ts      INTEGER NOT NULL,
  source  TEXT    NOT NULL,
  signal  TEXT    NOT NULL REFERENCES signal_catalog(signal),
  value   REAL    NOT NULL,
  unit    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_sig_ts ON signals(signal, ts);

-- Aggregates (1 s kept ~7 days, 1 min kept ~90 days)
CREATE TABLE IF NOT EXISTS signals_1s (
  ts INTEGER NOT NULL, signal TEXT NOT NULL,
  avg REAL, min REAL, max REAL, n INTEGER,
  PRIMARY KEY (signal, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS signals_1m (
  ts INTEGER NOT NULL, signal TEXT NOT NULL,
  avg REAL, min REAL, max REAL, n INTEGER,
  PRIMARY KEY (signal, ts)
) WITHOUT ROWID;

-- Trips and digests (permanent)
CREATE TABLE IF NOT EXISTS trips (
  id            INTEGER PRIMARY KEY,
  ts_start      INTEGER NOT NULL,
  ts_end        INTEGER NOT NULL,
  distance_km   REAL,
  energy_kwh    REAL,
  fuel_l        REAL,
  avg_speed_kph REAL,
  city_share    REAL,                     -- 0..1 by distance
  highway_share REAL,                     -- 0..1 by distance
  avg_ambient_c REAL,
  hvac_energy_kwh REAL
);
CREATE INDEX IF NOT EXISTS idx_trips_start ON trips(ts_start);

CREATE TABLE IF NOT EXISTS digest_daily (
  day     TEXT NOT NULL,                  -- YYYY-MM-DD (vehicle local date)
  metric  TEXT NOT NULL,                  -- e.g. 'range_per_charge','energy_per_km'
  value   REAL NOT NULL,
  n_trips INTEGER,
  PRIMARY KEY (day, metric)
) WITHOUT ROWID;

-- Events (permanent until quota): ADAS disengagements, warnings, hard braking, etc.
CREATE TABLE IF NOT EXISTS events (
  id        INTEGER PRIMARY KEY,
  ts_start  INTEGER NOT NULL,
  ts_end    INTEGER,
  type      TEXT NOT NULL,                -- see tools.schema.json event_type enum
  source    TEXT NOT NULL,
  severity  TEXT CHECK (severity IN ('info','warning','critical')) DEFAULT 'info',
  trip_id   INTEGER REFERENCES trips(id),
  payload   TEXT                          -- JSON: details, reason codes
);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts_start);

-- Pointers to short ring-buffered camera clips (no continuous video stored)
CREATE TABLE IF NOT EXISTS clip_refs (
  id        INTEGER PRIMARY KEY,
  event_id  INTEGER NOT NULL REFERENCES events(id),
  camera    TEXT,
  path      TEXT NOT NULL,
  ts_start  INTEGER NOT NULL,
  ts_end    INTEGER NOT NULL,
  detections TEXT                         -- JSON summary of detected objects
);

-- Diagnostics
CREATE TABLE IF NOT EXISTS dtcs (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  ecu         TEXT NOT NULL,
  code        TEXT NOT NULL,              -- e.g. 'P0A7E'
  status      TEXT NOT NULL,              -- pending | confirmed | cleared
  description TEXT
);
CREATE INDEX IF NOT EXISTS idx_dtcs_code_ts ON dtcs(code, ts);

CREATE TABLE IF NOT EXISTS dtc_knowledge (
  code        TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  related_causes TEXT                     -- JSON array; curated, not LLM-generated
);

-- Logs (templated with Drain3-style template ids)
CREATE TABLE IF NOT EXISTS log_templates (
  id       INTEGER PRIMARY KEY,
  template TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS logs (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  source      TEXT NOT NULL,              -- qnx | android | someip | ecu:<name>
  level       TEXT,
  template_id INTEGER REFERENCES log_templates(id),
  message     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);

CREATE VIRTUAL TABLE IF NOT EXISTS logs_fts USING fts5(
  message, content='logs', content_rowid='id'
);

-- Cached insight results (optional, speeds up repeated queries)
CREATE TABLE IF NOT EXISTS insight_cache (
  key        TEXT PRIMARY KEY,            -- hash of tool name + args
  packet     TEXT NOT NULL,               -- evidence packet JSON
  created_ts INTEGER NOT NULL
);

-- Full-rate signal snapshots around events (±60 s at native Hz)
-- Rows are kept as long as the parent event (permanent until event quota).
CREATE TABLE IF NOT EXISTS event_snapshots (
  event_id  INTEGER NOT NULL REFERENCES events(id),
  ts        INTEGER NOT NULL,
  signal    TEXT    NOT NULL,
  value     REAL    NOT NULL,
  PRIMARY KEY (event_id, signal, ts)
) WITHOUT ROWID;

-- Retention policy (read by the retention job)
CREATE TABLE IF NOT EXISTS retention_policy (
  table_name   TEXT PRIMARY KEY,
  keep_days    INTEGER,                   -- NULL = until quota
  max_bytes    INTEGER
);
INSERT OR IGNORE INTO retention_policy(table_name, keep_days, max_bytes) VALUES
  ('signals', 2, NULL),
  ('signals_1s', 7, NULL),
  ('signals_1m', 90, NULL),
  ('logs', 30, NULL),
  ('events', NULL, NULL),
  ('event_snapshots', NULL, NULL),
  ('trips', NULL, NULL),
  ('digest_daily', NULL, NULL);
