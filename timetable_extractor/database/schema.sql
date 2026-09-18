-- CELCAT timetable warehouse
--
-- Design notes
--
-- * CELCAT republishes the whole site in one batch. Each republish is a
--   `publication`; sessions are stored per publication rather than being
--   overwritten, so a semester's timetable can be diffed against the one
--   before it ("which classes moved room this week?").
-- * `sync_runs` records every check we make, including checks that found
--   nothing new. The server exposes only its *current* Last-Modified, so
--   this table is the only place an update history can accumulate.
-- * One real class appears in up to three PDFs - the course's, the room's
--   and each teacher's. They are merged into a single `sessions` row, with
--   `session_sources` recording every PDF that described it. That merge is
--   what fills in staff names, which course PDFs usually omit.
-- * Times are stored as minutes from midnight so overlap queries are plain
--   integer comparisons; the rendered label is kept for display.
-- * `weeks` is the expanded set of week numbers, so "which classes run in
--   week 8" is an array containment query rather than string parsing.
--
-- Safe to re-run: every statement is idempotent.

-- Enum types
-- Declaration order is sort order, so ORDER BY day gives Monday-first.
DO $$ BEGIN
    CREATE TYPE day_of_week AS ENUM (
        'Monday', 'Tuesday', 'Wednesday', 'Thursday',
        'Friday', 'Saturday', 'Sunday'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE resource_kind AS ENUM ('course', 'staff', 'room');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;


-- Publication history

CREATE TABLE IF NOT EXISTS publications (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Timestamp CELCAT prints in the finder.xml footer.
    published_at        TIMESTAMPTZ,
    -- What the web server reported for finder.xml.
    http_last_modified  TIMESTAMPTZ,
    http_etag           TEXT,
    -- Content identity: the same bytes must never create a second row.
    xml_sha256          TEXT        NOT NULL UNIQUE,
    resource_count      INTEGER     NOT NULL DEFAULT 0,
    discovered_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE publications IS
    'One row per distinct finder.xml the site has served, i.e. per republish.';

CREATE TABLE IF NOT EXISTS sync_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    publication_id  BIGINT      REFERENCES publications(id) ON DELETE SET NULL,
    -- False when the conditional request came back 304 Not Modified.
    index_changed   BOOLEAN     NOT NULL DEFAULT false,
    pdfs_checked    INTEGER     NOT NULL DEFAULT 0,
    pdfs_changed    INTEGER     NOT NULL DEFAULT 0,
    pdfs_added      INTEGER     NOT NULL DEFAULT 0,
    pdfs_removed    INTEGER     NOT NULL DEFAULT 0,
    note            TEXT
);

COMMENT ON TABLE sync_runs IS
    'Every update check, including no-op checks. Builds the update history '
    'the server itself does not expose.';

CREATE INDEX IF NOT EXISTS sync_runs_started_idx ON sync_runs (started_at DESC);


-- Organisational units

CREATE TABLE IF NOT EXISTS faculties (
    id      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS departments (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT    NOT NULL,
    faculty_id  INTEGER REFERENCES faculties(id) ON DELETE SET NULL,
    UNIQUE (name, faculty_id)
);


-- The finder.xml index

CREATE TABLE IF NOT EXISTS resources (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    celcat_id               TEXT          NOT NULL,
    kind                    resource_kind NOT NULL,
    pdf_link                TEXT          NOT NULL UNIQUE,
    name                    TEXT          NOT NULL,
    department_id           INTEGER       REFERENCES departments(id) ON DELETE SET NULL,
    faculty_id              INTEGER       REFERENCES faculties(id)   ON DELETE SET NULL,
    -- Lets a resource that disappears from the index be spotted.
    first_seen_publication  BIGINT        REFERENCES publications(id) ON DELETE SET NULL,
    last_seen_publication   BIGINT        REFERENCES publications(id) ON DELETE SET NULL,
    UNIQUE (kind, celcat_id)
);

CREATE INDEX IF NOT EXISTS resources_kind_idx ON resources (kind);


-- Entities

CREATE TABLE IF NOT EXISTS courses (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- "COMP 2601". Normalised to a single space so the same course from a
    -- course PDF and a room PDF resolves to one row.
    code            TEXT    NOT NULL UNIQUE,
    title           TEXT,
    department_id   INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    faculty_id      INTEGER REFERENCES faculties(id)   ON DELETE SET NULL,
    resource_id     BIGINT  REFERENCES resources(id)   ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS staff (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    resource_id BIGINT  REFERENCES resources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- "TLC LT B". The trailing letter is significant: "FSS 101 W" and
    -- "FSS 101 E" are the west and east wings, not the same room.
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT,
    resource_id BIGINT  REFERENCES resources(id) ON DELETE SET NULL
);


-- Per-file change tracking

CREATE TABLE IF NOT EXISTS pdf_files (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pdf_link            TEXT          NOT NULL UNIQUE,
    kind                resource_kind NOT NULL,
    http_etag           TEXT,
    http_last_modified  TIMESTAMPTZ,
    sha256              TEXT,
    byte_size           INTEGER,
    first_seen_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    -- When the bytes last actually differed, as opposed to when we last looked.
    content_changed_at  TIMESTAMPTZ,
    last_checked_at     TIMESTAMPTZ
);

COMMENT ON COLUMN pdf_files.content_changed_at IS
    'Last time the file''s bytes differed from what we already had. A sync '
    'that returns 304 updates last_checked_at only.';


-- The fact table

CREATE TABLE IF NOT EXISTS sessions (
    id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    publication_id  BIGINT      NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    semester        TEXT,

    course_id       INTEGER     NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    room_id         INTEGER     REFERENCES rooms(id) ON DELETE SET NULL,

    day             day_of_week NOT NULL,
    -- Minutes from midnight: overlap tests become integer comparisons.
    start_min       SMALLINT    NOT NULL CHECK (start_min >= 0   AND start_min < 1440),
    end_min         SMALLINT    NOT NULL CHECK (end_min   >  0   AND end_min  <= 1440),

    activity_type   TEXT,
    -- "L1" lab / "T2" tutorial / "G1" group: the stream a student picks.
    stream_label    TEXT,

    weeks_raw       TEXT,
    -- Expanded week numbers, e.g. "W1-W7, W9-W12" -> {1,2,3,4,5,6,7,9,10,11,12}
    weeks           SMALLINT[]  NOT NULL DEFAULT '{}',
    week_count      SMALLINT,

    notes           TEXT,
    raw_text        TEXT,

    CONSTRAINT sessions_time_order CHECK (end_min > start_min)
);

-- One row per real class per publication. COALESCE is needed because NULLs
-- compare as distinct in a plain UNIQUE constraint, which would let the same
-- roomless session be inserted repeatedly.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_natural_key
    ON sessions (
        publication_id,
        course_id,
        day,
        start_min,
        end_min,
        COALESCE(room_id, -1),
        COALESCE(activity_type, ''),
        COALESCE(stream_label, ''),
        COALESCE(weeks_raw, '')
    );

CREATE INDEX IF NOT EXISTS sessions_publication_idx ON sessions (publication_id);
CREATE INDEX IF NOT EXISTS sessions_course_idx      ON sessions (course_id);
-- Drives "what is in this room / free at this time" lookups.
CREATE INDEX IF NOT EXISTS sessions_room_slot_idx   ON sessions (room_id, day, start_min, end_min);
CREATE INDEX IF NOT EXISTS sessions_slot_idx        ON sessions (day, start_min, end_min);
-- Array containment: sessions running in a given teaching week.
CREATE INDEX IF NOT EXISTS sessions_weeks_idx       ON sessions USING GIN (weeks);


CREATE TABLE IF NOT EXISTS session_staff (
    session_id  BIGINT  NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    staff_id    INTEGER NOT NULL REFERENCES staff(id)    ON DELETE CASCADE,
    PRIMARY KEY (session_id, staff_id)
);

CREATE INDEX IF NOT EXISTS session_staff_staff_idx ON session_staff (staff_id);


CREATE TABLE IF NOT EXISTS session_sources (
    session_id      BIGINT NOT NULL REFERENCES sessions(id)  ON DELETE CASCADE,
    pdf_file_id     BIGINT NOT NULL REFERENCES pdf_files(id) ON DELETE CASCADE,
    PRIMARY KEY (session_id, pdf_file_id)
);

COMMENT ON TABLE session_sources IS
    'Which PDFs described a session. A session confirmed by the course, room '
    'and staff timetables is more trustworthy than one seen in a single PDF.';


-- What a republish changed
--
-- Diffing two publications is cheap but not free: about 7,000 rows compared
-- per pair. It happens once per republish and is read on every page view, so
-- the result is computed at load time and stored rather than recomputed.
--
-- Rows are per (from, to) pair rather than per publication, so a student two
-- publications behind can be answered directly instead of by replaying hops.
-- Replaying is not equivalent: a class that moves and moves back composes to
-- two changes when the honest answer is none.

CREATE TABLE IF NOT EXISTS publication_changes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_publication_id BIGINT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    to_publication_id   BIGINT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,

    -- course_added | course_dropped | course_renamed
    -- class_added  | class_removed  | class_moved | class_venue_confirmed
    change_type     TEXT   NOT NULL,

    course_code     TEXT   NOT NULL,
    course_title    TEXT,
    activity_type   TEXT,
    stream_label    TEXT,

    -- The slots either side, already rendered, so describing a change needs no
    -- second query. Null on the side where the thing did not exist.
    before          JSONB,
    after           JSONB
);

COMMENT ON TABLE publication_changes IS
    'One row per thing that changed between two publications. Written by the '
    'loader, read by /explore/changes.';

CREATE INDEX IF NOT EXISTS publication_changes_pair_idx
    ON publication_changes (to_publication_id, from_publication_id);

-- The per-course lookup the builder needs: "did anything happen to these six
-- courses since the publication my timetable was built against?"
CREATE INDEX IF NOT EXISTS publication_changes_course_idx
    ON publication_changes (to_publication_id, course_code);

-- One row per change per pair. Re-running a diff must not double it.
CREATE UNIQUE INDEX IF NOT EXISTS publication_changes_identity_idx
    ON publication_changes (
        from_publication_id, to_publication_id, change_type, course_code,
        COALESCE(activity_type, ''), COALESCE(stream_label, '')
    );


-- Convenience views

-- The publication students are served: the newest one that actually has
-- sessions. The EXISTS is not cosmetic. A publication row is committed before
-- its sessions are written, so without it a load still in progress is already
-- "current" while empty, and current_sessions - which every student-facing
-- query reads - returns nothing at all. On 17 September 2026 a load died
-- between the two commits and the live site served an empty timetable until it
-- was run again. loader.load_all now extracts before it writes anything, which
-- shrinks that window to the final insert; this closes it wherever a load
-- stops. The cost is an index lookup on sessions_publication_idx.
CREATE OR REPLACE VIEW latest_publication AS
    SELECT * FROM publications p
     WHERE EXISTS (SELECT 1 FROM sessions s WHERE s.publication_id = p.id)
     ORDER BY COALESCE(p.published_at, p.discovered_at) DESC LIMIT 1;

-- The timetable as it currently stands, flattened for querying.
CREATE OR REPLACE VIEW current_sessions AS
    SELECT
        s.id,
        c.code                      AS course_code,
        c.title                     AS course_title,
        d.name                      AS department,
        f.name                      AS faculty,
        s.day,
        s.start_min,
        s.end_min,
        to_char(make_interval(mins => s.start_min), 'HH24:MI') AS start_time,
        to_char(make_interval(mins => s.end_min),   'HH24:MI') AS end_time,
        s.activity_type,
        s.stream_label,
        r.code                      AS room,
        s.weeks_raw,
        s.weeks,
        s.week_count,
        s.semester,
        s.notes,
        COALESCE(
            (SELECT array_agg(st.name ORDER BY st.name)
               FROM session_staff ss
               JOIN staff st ON st.id = ss.staff_id
              WHERE ss.session_id = s.id),
            '{}'
        )                           AS staff,
        (SELECT count(*) FROM session_sources src WHERE src.session_id = s.id)
                                    AS source_count
    FROM sessions s
    JOIN courses  c ON c.id = s.course_id
    LEFT JOIN rooms       r ON r.id = s.room_id
    LEFT JOIN departments d ON d.id = c.department_id
    LEFT JOIN faculties   f ON f.id = c.faculty_id
    WHERE s.publication_id = (SELECT id FROM latest_publication);
