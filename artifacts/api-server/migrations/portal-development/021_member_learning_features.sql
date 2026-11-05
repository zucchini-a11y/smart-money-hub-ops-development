-- Development-only member learning data. Do not run against the Production schema.
BEGIN;
SET LOCAL search_path TO smh_test;
DO $$
BEGIN
    IF current_schema() NOT IN ('smh_test') THEN
        RAISE EXCEPTION 'Member learning migration is Development-only (smh_test).';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS member_economic_calendar_events (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    event_date DATE NOT NULL,
    event_at_utc TIMESTAMPTZ,
    time_label TEXT NOT NULL,
    timezone_status TEXT NOT NULL,
    impact TEXT NOT NULL CHECK (impact IN ('high','medium','low','unavailable')),
    impact_basis TEXT NOT NULL CHECK (impact_basis IN ('smh_estimate','source_verified','unavailable')),
    source_url TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    previous_value TEXT,
    forecast_value TEXT,
    actual_value TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS member_economic_calendar_events_date
    ON member_economic_calendar_events(event_date, impact);
CREATE INDEX IF NOT EXISTS member_economic_calendar_events_source
    ON member_economic_calendar_events(source_key, event_date);

CREATE TABLE IF NOT EXISTS member_economic_calendar_sources (
    source_key TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available','stale','unverified','failed')),
    checked_at TIMESTAMPTZ,
    message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS member_journal_trades (
    id UUID PRIMARY KEY,
    clerk_user_id TEXT NOT NULL,
    instrument VARCHAR(24) NOT NULL CHECK (length(instrument) BETWEEN 2 AND 24),
    direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    entry_price NUMERIC(20,8) NOT NULL CHECK (entry_price > 0),
    stop_loss NUMERIC(20,8) NOT NULL CHECK (stop_loss > 0),
    take_profit NUMERIC(20,8) NOT NULL CHECK (take_profit > 0),
    position_size NUMERIC(20,8) NOT NULL CHECK (position_size > 0),
    risk_percent NUMERIC(7,4) CHECK (risk_percent IS NULL OR (risk_percent >= 0 AND risk_percent <= 100)),
    entry_at TIMESTAMPTZ NOT NULL,
    exit_at TIMESTAMPTZ,
    outcome TEXT NOT NULL CHECK (outcome IN ('open','win','loss','breakeven')),
    realized_pnl NUMERIC(20,8),
    notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 5000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (direction = 'long' AND stop_loss < entry_price AND take_profit > entry_price)
        OR
        (direction = 'short' AND stop_loss > entry_price AND take_profit < entry_price)
    ),
    CHECK (exit_at IS NULL OR exit_at >= entry_at),
    CHECK (outcome = 'open' OR exit_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS member_journal_trades_owner_date
    ON member_journal_trades(clerk_user_id, entry_at DESC);
CREATE INDEX IF NOT EXISTS member_journal_trades_owner_outcome
    ON member_journal_trades(clerk_user_id, outcome, entry_at DESC);

CREATE TABLE IF NOT EXISTS member_coach_rate_limits (
    clerk_user_id TEXT NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 1 CHECK (request_count > 0),
    PRIMARY KEY (clerk_user_id, bucket_start)
);
CREATE INDEX IF NOT EXISTS member_coach_rate_limits_expiry
    ON member_coach_rate_limits(bucket_start);

COMMIT;
