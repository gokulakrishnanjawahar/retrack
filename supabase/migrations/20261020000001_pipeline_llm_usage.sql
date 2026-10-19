-- The distiller records its own LLM spend, like the judge.
grant execute on function private.increment_llm_usage(bigint, bigint) to retrack_pipeline;
