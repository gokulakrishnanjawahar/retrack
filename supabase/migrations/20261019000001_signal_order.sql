-- Signals saved in one transaction share now(); an identity column gives a reliable
-- "latest wins" order within a source.
alter table public.outcome_signals add column seq bigint generated always as identity;
