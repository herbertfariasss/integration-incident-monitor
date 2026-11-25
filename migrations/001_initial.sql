CREATE TABLE incidents (
    id BIGSERIAL PRIMARY KEY, integration TEXT NOT NULL, error_code TEXT NOT NULL,
    title TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    first_event_at TIMESTAMPTZ NOT NULL, last_event_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ, resolution TEXT
);
CREATE UNIQUE INDEX ux_open_incident ON incidents(integration, error_code) WHERE status = 'open';
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
    integration TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('success', 'failure')),
    error_code TEXT, message TEXT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL, incident_id BIGINT REFERENCES incidents(id),
    simulated_failures INTEGER NOT NULL DEFAULT 0 CHECK (simulated_failures >= 0)
);
CREATE INDEX ix_events_failure_lookup ON events(integration, error_code, status, occurred_at);
CREATE INDEX ix_events_incident_id ON events(incident_id);
CREATE TABLE deliveries (
    id BIGSERIAL PRIMARY KEY, event_id BIGINT NOT NULL UNIQUE REFERENCES events(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'exhausted')),
    cycle INTEGER NOT NULL DEFAULT 1, attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ, lease_until TIMESTAMPTZ, last_error TEXT
);
CREATE INDEX ix_deliveries_due ON deliveries(status, next_attempt_at);
CREATE TABLE delivery_attempts (
    id BIGSERIAL PRIMARY KEY, delivery_id BIGINT NOT NULL REFERENCES deliveries(id),
    cycle INTEGER NOT NULL, attempt_number INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('failed', 'succeeded')),
    failure_reason TEXT, UNIQUE(delivery_id, cycle, attempt_number)
);
