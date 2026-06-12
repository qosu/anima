-- Per-call DeepSeek usage breakdown for billing_events (cost reporting).
-- cost_usd_micros is NULL when pricing for `model` is not in agent_loop._PRICING_USD_PER_M
-- (do not fabricate a cost for unverified pricing).
ALTER TABLE billing_events ADD COLUMN cache_hit_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE billing_events ADD COLUMN cache_miss_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE billing_events ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE billing_events ADD COLUMN cost_usd_micros INTEGER;
