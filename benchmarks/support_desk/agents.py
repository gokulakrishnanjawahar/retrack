"""Agents for the support-desk benchmark, each run as a LangGraph graph so the Retrack
SDK captures it exactly like a customer's agent.

* ScriptedAgent ($0): a deterministic stand-in for an LLM. Without memory it learns by
  trial and error from tool errors, within its tool-call budget; with memory it applies
  what the recalled playbooks and warnings say. It proves the pipeline end to end; its
  numbers are not evidence of real-world gains.
* ClaudeAgent (real mode, spends credits): Claude Haiku 5.5 calling the same tools.
"""

import json
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from benchmarks.support_desk.world import Task, World

SYSTEM = (
    "You are a customer-support agent. Use the tools to complete the task exactly. "
    "Tools: lookup_order(order_id), check_delivery(order_id), "
    "issue_refund(order_id, amount_paise), update_address(order_id, address, pin_code)."
)


@dataclass
class AgentResult:
    tool_calls: int
    tokens_in: int
    tokens_out: int


class _State(TypedDict, total=False):
    task: str
    done: bool


def _single_node_graph(act):
    graph = StateGraph(_State)
    graph.add_node("act", act)
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    return graph.compile()


class ScriptedAgent:
    model_id = "scripted-agent"

    def __init__(self, max_tool_calls: int):
        self.max_tool_calls = max_tool_calls

    def run(self, world: World, task: Task, memory: str, config: dict[str, Any]) -> AgentResult:
        tools = world.tools()
        usage = AgentResult(0, 0, 0)
        history: list[str] = []
        knows = {
            "check": "check_delivery" in memory or "delivery not verified" in memory,
            "paise": "paise" in memory,
            "pin": "pin_code" in memory,
        }

        def think() -> None:
            # One model decision; its "prompt" grows with memory and history like a real one.
            prompt = "\n".join([SYSTEM, memory, task.text, *history])
            tokens_in, tokens_out = len(prompt) // 4, 40
            usage.tokens_in += tokens_in
            usage.tokens_out += tokens_out
            GenericFakeChatModel(
                messages=iter(
                    [
                        AIMessage(
                            content="next step",
                            usage_metadata={
                                "input_tokens": tokens_in,
                                "output_tokens": tokens_out,
                                "total_tokens": tokens_in + tokens_out,
                            },
                            response_metadata={"model_name": self.model_id},
                        )
                    ]
                )
            ).invoke(prompt)

        def call(name: str, **args) -> dict[str, Any] | None:
            if usage.tool_calls >= self.max_tool_calls:
                return None
            think()
            usage.tool_calls += 1
            result = tools[name].invoke(args)
            history.append(f"{name}({json.dumps(args)}) -> {json.dumps(result)}")
            error = str(result.get("error", ""))
            knows["check"] |= "check_delivery" in error
            knows["paise"] |= "paise" in error
            knows["pin"] |= "pin_code" in error
            return result

        def act(state: _State) -> dict:
            if task.family == "refund":
                order = call("lookup_order", order_id=task.order_id)
                while order is not None and usage.tool_calls < self.max_tool_calls:
                    if knows["check"]:
                        call("check_delivery", order_id=task.order_id)
                        knows["check"] = False  # checked for this order
                    amount = (
                        round(order["amount_rupees"] * 100)
                        if knows["paise"]
                        else int(order["amount_rupees"])
                    )
                    result = call("issue_refund", order_id=task.order_id, amount_paise=amount)
                    if result is None or "error" not in result:
                        break
            else:
                while usage.tool_calls < self.max_tool_calls:
                    if knows["pin"]:
                        args = {"address": task.new_address, "pin_code": task.pin_code}
                    else:
                        args = {"address": f"{task.new_address}, PIN {task.pin_code}"}
                    result = call("update_address", order_id=task.order_id, **args)
                    if result is None or "error" not in result:
                        break
            think()  # final answer
            return {"done": True}

        _single_node_graph(act).invoke({"task": task.text}, config=config)
        return usage


class ClaudeAgent:
    """Real mode: Claude Haiku 5.5 with tool calling. Spends credits; needs approval."""

    model_id = "claude-haiku-5-5"

    def __init__(self, max_tool_calls: int, api_key: str):
        from langchain_anthropic import ChatAnthropic  # benchmark-only dependency

        self.max_tool_calls = max_tool_calls
        self._model = ChatAnthropic(model=self.model_id, api_key=api_key, max_tokens=1024)

    def run(self, world: World, task: Task, memory: str, config: dict[str, Any]) -> AgentResult:
        tools = world.tools()
        model = self._model.bind_tools(list(tools.values()))
        usage = AgentResult(0, 0, 0)

        def act(state: _State) -> dict:
            system = SYSTEM + ("\n\n" + memory if memory else "")
            messages = [SystemMessage(system), HumanMessage(task.text)]
            while True:
                reply = model.invoke(messages)
                meta = reply.usage_metadata or {}
                usage.tokens_in += meta.get("input_tokens", 0)
                usage.tokens_out += meta.get("output_tokens", 0)
                messages.append(reply)
                if not reply.tool_calls or usage.tool_calls >= self.max_tool_calls:
                    break
                for tool_call in reply.tool_calls:
                    usage.tool_calls += 1
                    result = tools[tool_call["name"]].invoke(tool_call["args"])
                    messages.append(ToolMessage(json.dumps(result), tool_call_id=tool_call["id"]))
            return {"done": True}

        _single_node_graph(act).invoke({"task": task.text}, config=config)
        return usage
