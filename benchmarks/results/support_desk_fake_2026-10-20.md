# Support-desk benchmark (fake mode, 2026-10-20)

Agent model: `scripted-agent`. Settings: `{"seed": 7, "learn_tasks": 16, "eval_tasks": 20, "learn_tool_budget": 8, "eval_tool_budget": 4}`.

| | Without memory | With Retrack memory |
|---|---|---|
| Success rate | 50% | 100% |
| Tool calls per task | 3.00 | 2.00 |
| Tokens per task | 641 | 657 |
| Cost per task (USD) | 0.000128 | 0.000114 |

Success rate change: **+50%** (95% interval +30% to +70%).
Tokens per task change: **+17** (95% interval -19 to +53).
Memory was recalled on 20 of 20 tasks.

## By task family

| Family | Success without | Success with | Tool calls without | Tool calls with |
|---|---|---|---|---|
| address | 100% | 100% | 2.00 | 1.00 |
| refund | 0% | 100% | 4.00 | 3.00 |

## Memory learned

| Playbook | Status | Support | Trusted | Uses | Successes |
|---|---|---|---|---|---|
| Change the delivery address of order 82226 to Flat 45, Block | active | 28 | 28 | 10 | 10 |
| Customer says order 16328 arrived damaged; refund it. | active | 18 | 18 | 10 | 10 |

Failure signatures recorded: 1.

> Fake mode uses a scripted agent and a $0 test embedder. It proves the pipeline
> works end to end; its numbers are not evidence of real-world gains.
