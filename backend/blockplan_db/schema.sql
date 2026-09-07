-- BlockPlan database schema.
--
-- Two things this schema has to get right, and they pull in opposite
-- directions:
--
--   1. The frozen dataset must survive the round trip UNCHANGED. Every number
--      quoted by this project was produced from those rows, so a value that
--      arrives back even slightly different invalidates the benchmark.
--   2. Live data must be able to arrive later without overwriting any of it.
--
-- Snapshots reconcile the two. The frozen dataset loads as snapshot 1 and is
-- never updated; live extracts arrive as 2, 3, ... and coexist. A plan records
-- the snapshot it was built from, so an approved plan stays reproducible
-- against the exact data that produced it.
--
-- TYPES. Planning inputs are typed (INTEGER / DOUBLE PRECISION / TEXT) because
-- the CSV loaders already call int() and float() on those strings, so typing
-- them changes nothing. Two deliberate exceptions:
--
--   * Flags are SMALLINT 0/1, not BOOLEAN. The CSVs hold "0"/"1" and the
--     loaders read them as ints; BOOLEAN would introduce a conversion where
--     none exists today. `trains.is_synthetic` holds "True"/"False" instead,
--     so it stays TEXT -- the point is to store what is there, not to tidy it.
--
--   * Evidence tables are ALL TEXT. Their values are rendered on the Evidence
--     screen and quoted in the report, so they must come back as the same
--     characters. It also avoids a real trap: benchmark_results.enum_seconds
--     holds 0.004162250999797834 -- eighteen decimal places -- which any
--     fixed-scale NUMERIC(p,s) would silently truncate.

-- ---------------------------------------------------------------------------
-- Snapshots
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dataset_snapshots (
    snapshot_id       INTEGER      PRIMARY KEY,
    label             TEXT         NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    seed              INTEGER,
    generator_version TEXT,
    -- The three DataMeet source hashes from manifest.json, verbatim. This is
    -- what lets someone check that snapshot 1 came from the files it claims.
    source_hashes     JSONB,
    -- The synthetic-data NOTICE, carried so it cannot be separated from the
    -- data it describes.
    notice            TEXT         NOT NULL,
    -- Frozen snapshots are append-only by convention; the loader refuses to
    -- rewrite one rather than relying on a trigger.
    is_frozen         BOOLEAN      NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- Reference: real public infrastructure and timetable
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stations (
    snapshot_id   INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    station_code  TEXT    NOT NULL,
    station_name  TEXT,
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    zone          TEXT,
    state         TEXT,
    seq           INTEGER,
    is_junction   SMALLINT,
    PRIMARY KEY (snapshot_id, station_code)
);

CREATE TABLE IF NOT EXISTS sections (
    snapshot_id       INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    section_id        TEXT    NOT NULL,
    from_station_code TEXT,
    to_station_code   TEXT,
    line              TEXT,
    length_km         DOUBLE PRECISION,
    tracks            INTEGER,
    electrified       SMALLINT,
    is_single         SMALLINT,
    headway_min       INTEGER,
    degraded_factor   DOUBLE PRECISION,
    support_trains    INTEGER,
    track_source      TEXT,
    PRIMARY KEY (snapshot_id, section_id)
);

CREATE TABLE IF NOT EXISTS trains (
    snapshot_id  INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    train_number TEXT    NOT NULL,
    train_name   TEXT,
    train_class  TEXT,
    is_synthetic TEXT,          -- "True"/"False" in the source; stored as-is
    direction    TEXT,
    PRIMARY KEY (snapshot_id, train_number)
);

-- No natural key: a train calls at a station once per stop_seq, but the CSV
-- carries no uniqueness guarantee and inventing one could reject a valid row.
CREATE TABLE IF NOT EXISTS train_stops (
    snapshot_id   INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    train_number  TEXT,
    train_name    TEXT,
    station_code  TEXT,
    arrival_min   INTEGER,
    departure_min INTEGER,
    day           INTEGER,
    stop_seq      INTEGER
);
CREATE INDEX IF NOT EXISTS train_stops_by_train
    ON train_stops (snapshot_id, train_number, stop_seq);

CREATE TABLE IF NOT EXISTS movements (
    snapshot_id  INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    train_number TEXT,
    train_class  TEXT,
    from_code    TEXT,
    to_code      TEXT,
    direction    TEXT,
    enter_min    INTEGER,
    is_synthetic TEXT
);
CREATE INDEX IF NOT EXISTS movements_by_snapshot ON movements (snapshot_id);

-- ---------------------------------------------------------------------------
-- Rules and catalogue
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS activities (
    snapshot_id           INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    activity_id           TEXT    NOT NULL,
    dept                  TEXT,
    label                 TEXT,
    asset                 TEXT,
    needs_t               SMALLINT,
    needs_p               SMALLINT,
    needs_d               SMALLINT,
    needs_train_movements SMALLINT,
    needs_live_ohe        SMALLINT,
    duration_mean_min     INTEGER,
    duration_sd_min       INTEGER,
    periodicity_days      INTEGER,
    min_block_min         INTEGER,
    min_block_provenance  TEXT,
    resource_class        TEXT,
    criticality_base      DOUBLE PRECISION,
    protection_source     TEXT,
    PRIMARY KEY (snapshot_id, activity_id)
);

-- One activity can compel more than one companion, so the key includes both.
CREATE TABLE IF NOT EXISTS pairing_rules (
    snapshot_id        INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    activity           TEXT    NOT NULL,
    compelled_dept     TEXT,
    companion_activity TEXT    NOT NULL,
    duration_mean_min  INTEGER,
    duration_sd_min    INTEGER,
    must_follow_parent SMALLINT,
    precedes_parent    SMALLINT,
    source             TEXT,          -- the manual clause this rule cites
    confidence         DOUBLE PRECISION,
    PRIMARY KEY (snapshot_id, activity, companion_activity)
);

CREATE TABLE IF NOT EXISTS resources (
    snapshot_id    INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    resource_class TEXT    NOT NULL,
    fleet_size     INTEGER,
    provenance     TEXT,
    PRIMARY KEY (snapshot_id, resource_class)
);

-- ---------------------------------------------------------------------------
-- Demand
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS jobs (
    snapshot_id           INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    job_id                TEXT    NOT NULL,
    dept                  TEXT,
    activity              TEXT,
    section_id            TEXT,
    location_desc         TEXT,
    km_from               DOUBLE PRECISION,
    km_to                 DOUBLE PRECISION,
    needs_t               SMALLINT,
    needs_p               SMALLINT,
    needs_d               SMALLINT,
    needs_train_movements SMALLINT,
    needs_live_ohe        SMALLINT,
    duration_mean_min     DOUBLE PRECISION,
    duration_sd_min       DOUBLE PRECISION,
    duration_min_min      DOUBLE PRECISION,
    duration_max_min      DOUBLE PRECISION,
    min_block_min         INTEGER,
    resources             TEXT,
    due_day               INTEGER,
    criticality           DOUBLE PRECISION,
    priority              TEXT,
    uncertainty_level     TEXT,
    provenance            TEXT,
    PRIMARY KEY (snapshot_id, job_id)
);

-- Identical columns to jobs, plus the scenario that generated them. Verified:
-- the eight scenario files carry exactly jobs.csv's 23 columns.
CREATE TABLE IF NOT EXISTS scenario_jobs (
    snapshot_id           INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    scenario              TEXT    NOT NULL,
    job_id                TEXT    NOT NULL,
    dept                  TEXT,
    activity              TEXT,
    section_id            TEXT,
    location_desc         TEXT,
    km_from               DOUBLE PRECISION,
    km_to                 DOUBLE PRECISION,
    needs_t               SMALLINT,
    needs_p               SMALLINT,
    needs_d               SMALLINT,
    needs_train_movements SMALLINT,
    needs_live_ohe        SMALLINT,
    duration_mean_min     DOUBLE PRECISION,
    duration_sd_min       DOUBLE PRECISION,
    duration_min_min      DOUBLE PRECISION,
    duration_max_min      DOUBLE PRECISION,
    min_block_min         INTEGER,
    resources             TEXT,
    due_day               INTEGER,
    criticality           DOUBLE PRECISION,
    priority              TEXT,
    uncertainty_level     TEXT,
    provenance            TEXT,
    PRIMARY KEY (snapshot_id, scenario, job_id)
);

CREATE TABLE IF NOT EXISTS block_requests (
    snapshot_id                INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    request_id                 TEXT    NOT NULL,
    job_id                     TEXT,
    department                 TEXT,
    preferred_date             INTEGER,
    preferred_window_start_min INTEGER,
    minimum_duration_min       INTEGER,
    requested_duration_min     INTEGER,
    protection_type            TEXT,
    deadline_day               INTEGER,
    priority                   TEXT,
    reason                     TEXT,
    provenance                 TEXT,
    PRIMARY KEY (snapshot_id, request_id)
);

CREATE TABLE IF NOT EXISTS scenarios (
    snapshot_id            INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    scenario               TEXT    NOT NULL,
    demand_scale           DOUBLE PRECISION,
    freight_scale          DOUBLE PRECISION,
    uncertainty_scale      DOUBLE PRECISION,
    urgency_shift          INTEGER,
    backlog                DOUBLE PRECISION,
    -- Blank for most scenarios in the source, and the adapter treats blank as
    -- a documented default. NULL preserves that distinction; a zero would not.
    extra_passenger_scale  DOUBLE PRECISION,
    cancel_window_fraction DOUBLE PRECISION,
    note                   TEXT,
    PRIMARY KEY (snapshot_id, scenario)
);

CREATE TABLE IF NOT EXISTS scenario_jobs_manifest (
    snapshot_id        INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    scenario           TEXT    NOT NULL,
    seed               INTEGER,
    target_jobs        INTEGER,
    generated_jobs     INTEGER,
    demand_scale       DOUBLE PRECISION,
    backlog_multiplier DOUBLE PRECISION,
    uncertainty_scale  DOUBLE PRECISION,
    urgency_shift      INTEGER,
    jobs_engg          INTEGER,
    jobs_snt           INTEGER,
    jobs_trd           INTEGER,
    overdue_jobs       INTEGER,
    file               TEXT,
    method             TEXT,
    PRIMARY KEY (snapshot_id, scenario)
);

-- ---------------------------------------------------------------------------
-- Execution realisations
--
-- Generated separately from the demand and never read by the planner. That
-- separation is what makes the reliability claim testable rather than
-- circular, and it is preserved here: nothing joins these into the planning
-- path.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution (
    snapshot_id         INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    realisation         INTEGER NOT NULL,
    job_id              TEXT    NOT NULL,
    actual_duration_min DOUBLE PRECISION,
    PRIMARY KEY (snapshot_id, realisation, job_id)
);

CREATE TABLE IF NOT EXISTS execution_companions (
    snapshot_id         INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    realisation         INTEGER NOT NULL,
    job_id              TEXT    NOT NULL,
    actual_duration_min DOUBLE PRECISION,
    parent_job_id       TEXT,
    provenance          TEXT,
    PRIMARY KEY (snapshot_id, realisation, job_id)
);

-- ---------------------------------------------------------------------------
-- Frozen evidence artefacts -- ALL TEXT, see the note at the top of this file
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS method_comparison (
    snapshot_id       INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    row_no            INTEGER NOT NULL,     -- preserves file order for display
    method            TEXT,
    blocks            TEXT,
    jobs_done         TEXT,
    jobs_deferred     TEXT,
    traffic_cost      TEXT,
    traffic_per_job   TEXT,
    exp_overrun_cost  TEXT,
    cross_dept_blocks TEXT,
    cross_dept_share  TEXT,
    mean_reliability  TEXT,
    min_reliability   TEXT,
    block_utilisation TEXT,
    PRIMARY KEY (snapshot_id, row_no)
);

-- benchmark_results and execution_scoring_* carry 20 and 26 columns and are
-- served straight to the Evidence screen. Held as JSONB of the original
-- strings: adding a column to the CSV must not require a schema change, and
-- the row is reproduced exactly as written.
CREATE TABLE IF NOT EXISTS benchmark_results (
    snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    row_no      INTEGER NOT NULL,
    scenario    TEXT,
    row_data    JSONB   NOT NULL,
    PRIMARY KEY (snapshot_id, row_no)
);

CREATE TABLE IF NOT EXISTS execution_scoring_summary (
    snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    row_no      INTEGER NOT NULL,
    method      TEXT,
    row_data    JSONB   NOT NULL,
    PRIMARY KEY (snapshot_id, row_no)
);

CREATE TABLE IF NOT EXISTS execution_scoring_blocks (
    snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    row_no      INTEGER NOT NULL,
    row_data    JSONB   NOT NULL,
    PRIMARY KEY (snapshot_id, row_no)
);

-- ---------------------------------------------------------------------------
-- Dataset metadata
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS data_dictionary (
    snapshot_id INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    row_no      INTEGER NOT NULL,
    row_data    JSONB   NOT NULL,
    PRIMARY KEY (snapshot_id, row_no)
);

-- The five-class provenance record: which fields are real, derived, rule,
-- synthetic or assumed. Kept in the database so a row and its provenance
-- cannot be separated.
CREATE TABLE IF NOT EXISTS data_provenance (
    snapshot_id    INTEGER NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    row_no         INTEGER NOT NULL,
    table_name     TEXT,
    field          TEXT,
    classification TEXT,          -- A / B / C / D / E, or a hybrid
    row_data       JSONB   NOT NULL,
    PRIMARY KEY (snapshot_id, row_no)
);

-- ---------------------------------------------------------------------------
-- Outputs -- the part that genuinely needs a database
--
-- Plans live in an in-memory dict today and die with the process. These tables
-- are what let an approved plan outlive a restart, and what an audit trail
-- needs. Written by the service, never by the loader.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS plans (
    plan_id         TEXT        PRIMARY KEY,   -- the request hash, unchanged
    snapshot_id     INTEGER     NOT NULL REFERENCES dataset_snapshots(snapshot_id),
    scenario        TEXT        NOT NULL,
    theta           DOUBLE PRECISION NOT NULL,
    horizon_days    INTEGER     NOT NULL,
    max_bundle_size INTEGER     NOT NULL,
    mc_samples      INTEGER     NOT NULL,
    seed            INTEGER,
    status          TEXT        NOT NULL,
    objective       DOUBLE PRECISION,
    summary         JSONB,
    instance        JSONB,
    stage_timings_s JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plan_blocks (
    plan_id          TEXT    NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    block_id         TEXT    NOT NULL,
    section_id       TEXT    NOT NULL,
    day              INTEGER NOT NULL,
    start_min        INTEGER NOT NULL,
    end_min          INTEGER NOT NULL,
    length           INTEGER NOT NULL,
    reliability      DOUBLE PRECISION,
    traffic_cost     DOUBLE PRECISION,
    exp_overrun_cost DOUBLE PRECISION,
    dept_mix         TEXT[],
    job_ids          TEXT[],
    PRIMARY KEY (plan_id, block_id)
);

CREATE TABLE IF NOT EXISTS plan_deferred (
    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    job_id  TEXT NOT NULL,
    dept    TEXT,
    PRIMARY KEY (plan_id, job_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    plan_id    TEXT        NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    block_id   TEXT        NOT NULL,
    decision   TEXT        NOT NULL,     -- APPROVED / REJECTED / AMENDED
    decided_by TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note       TEXT,
    PRIMARY KEY (plan_id, block_id, decided_at)
);

-- Empty today, and deliberately so. This is where real hand-back times would
-- accumulate once the system runs against live data -- the first point at
-- which a learned duration model would have anything genuine to learn.
CREATE TABLE IF NOT EXISTS execution_actuals (
    id                  BIGSERIAL   PRIMARY KEY,
    snapshot_id         INTEGER     REFERENCES dataset_snapshots(snapshot_id),
    plan_id             TEXT,
    block_id            TEXT,
    job_id              TEXT        NOT NULL,
    dept                TEXT,
    planned_start_min   INTEGER,
    planned_end_min     INTEGER,
    actual_start_min    INTEGER,
    actual_end_min      INTEGER,
    actual_duration_min DOUBLE PRECISION,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS execution_actuals_by_job ON execution_actuals (job_id);
