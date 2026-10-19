-- The agent's final answer (redacted at ingest, truncated to 4,000 characters), so the
-- judge can check what the agent actually delivered, not only which steps succeeded.
alter table public.runs add column output_text text;
