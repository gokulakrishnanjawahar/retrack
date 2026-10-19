-- What each tool returned (redacted at ingest, at most 1,000 characters), so the judge
-- and later the distiller can see results, not only success or error classes.
alter table public.steps add column result_redacted text;
