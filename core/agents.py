"""Two ways of letting Claude (in Microsoft Foundry) answer the same question with the same four tools.

* run_traditional  - classic tool use: after every tool call the result goes back through the model, which decides
                     what to do next (one model round trip per tool-call batch).
* run_programmatic - programmatic tool calling: Claude writes ONE Python script that runs in the code-execution
                     sandbox and awaits the tools; only the script's printed output returns to the model.
"""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from anthropic import AnthropicFoundry
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from .config import Config, RunOptions
from .tools import execute_tool, tool_definitions

MAX_TOKENS = 4096
MAX_STEPS = 12

BASE_SYSTEM_PROMPT = """You are the Contoso Insurance claims assistant. You are talking to the patient {patient}.

To report on the patient's claims, use the tools as follows:
1. get_patient_grievance_mappings - the grievances (Jira ids) the patient raised and the claim each one is about.
2. get_jira_grievance_status - call once per grievance id to get its status, assignee, key, summary and created date.
3. get_patient_claims - all claims of the patient from the claims database.
4. escalate_unassigned_grievance - for every DENIED claim whose grievance is still UNASSIGNED, send ONE escalation
   e-mail asking a person to intervene (pass the grievance key, summary, created date, claim id and claim details).
   Never escalate a grievance that already has an assignee.

Then answer the patient in a friendly, concise way: give the status of EACH claim (Paid / Pending / Denied with the
reason) and the amount as given (the data has no currency, so do not add a currency symbol). For denied claims that have a grievance, say whether a person (name them) is already assigned, or that you
escalated it for intervention because nobody was assigned yet. Report only what the tools returned; do not comment on data quality or speculate."""

PROGRAMMATIC_ADDENDUM = """

The tools are available inside the code-execution sandbox as async Python functions. Orchestrate the whole workflow in
ONE script: fetch what you need (use asyncio.gather for independent calls), do the matching/filtering in code, call
the escalation tool from code, and print only a compact JSON summary of the facts needed for the final answer."""


@dataclass
class Step:
    index: int
    label: str
    input_tokens: int = 0        # all input: uncached + cache write + cache read
    output_tokens: int = 0       # billed output, includes reasoning
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_s: float = 0.0
    text: str = ""
    code: str = ""
    code_output: str = ""
    tool_calls: list[str] = field(default_factory=list)

    @property
    def visible_output_tokens(self) -> int:
        return max(self.output_tokens - self.reasoning_tokens, 0)

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cache_read_tokens - self.cache_write_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_index(self) -> float:
        """Relative cost in 'uncached input token' units, using the multipliers in Config (an assumption, not a bill)."""
        return (
            self.uncached_input_tokens
            + self.cache_write_tokens * Config.cache_write_multiplier
            + self.cache_read_tokens * Config.cache_read_multiplier
            + self.output_tokens * Config.output_multiplier
        )

    @property
    def cost_index_no_cache(self) -> float:
        """What the very same tokens would cost without caching (token counts are identical either way)."""
        return self.input_tokens + self.output_tokens * Config.output_multiplier


@dataclass
class ToolExecution:
    name: str
    arguments: dict
    result: str
    duration_s: float
    caller: str  # "direct" | "code_execution"
    step_index: int


@dataclass
class RunResult:
    approach: str
    options: RunOptions = field(default_factory=RunOptions)
    final_text: str = ""
    steps: list[Step] = field(default_factory=list)
    tools: list[ToolExecution] = field(default_factory=list)
    wall_time_s: float = 0.0
    error: str = ""

    @property
    def input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.steps)

    @property
    def cache_read_tokens(self) -> int:
        return sum(s.cache_read_tokens for s in self.steps)

    @property
    def cache_write_tokens(self) -> int:
        return sum(s.cache_write_tokens for s in self.steps)

    @property
    def uncached_input_tokens(self) -> int:
        return sum(s.uncached_input_tokens for s in self.steps)

    @property
    def output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.steps)

    @property
    def reasoning_tokens(self) -> int:
        return sum(s.reasoning_tokens for s in self.steps)

    @property
    def visible_output_tokens(self) -> int:
        return self.output_tokens - self.reasoning_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_index(self) -> float:
        return sum(s.cost_index for s in self.steps)

    @property
    def cost_index_no_cache(self) -> float:
        return sum(s.cost_index_no_cache for s in self.steps)

    @property
    def cache_saving_pct(self) -> float:
        """Positive = caching made this run cheaper than the same tokens without caching."""
        base = self.cost_index_no_cache
        return (base - self.cost_index) / base * 100 if base else 0.0

    @property
    def cache_warm(self) -> bool:
        """True when the very first model call already read a cache written by an earlier request."""
        first = next((s for s in self.steps if s.total_tokens > 0), None)
        return bool(first and first.cache_read_tokens > 0)

    @property
    def model_calls(self) -> int:
        return sum(1 for s in self.steps if s.total_tokens > 0)

    def to_record(self) -> dict:
        """Compact, JSON-serialisable summary used by the run history."""
        return {
            "approach": self.approach, "input": self.input_tokens, "cache_read": self.cache_read_tokens,
            "cache_write": self.cache_write_tokens, "reasoning": self.reasoning_tokens,
            "output": self.visible_output_tokens, "total": self.total_tokens, "cost_index": round(self.cost_index),
            "cost_index_no_cache": round(self.cost_index_no_cache), "cache_warm": self.cache_warm,
            "model_calls": self.model_calls, "wall_time_s": round(self.wall_time_s, 1), "error": self.error,
        }


EventCallback = Callable[[str, object], None]


def _client() -> AnthropicFoundry:
    provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
    return AnthropicFoundry(resource=Config.foundry_resource, azure_ad_token_provider=provider)


def _record_step(index: int, label: str, response, latency: float) -> Step:
    usage = response.usage
    details = getattr(usage, "output_tokens_details", None)
    read = usage.cache_read_input_tokens or 0
    write = usage.cache_creation_input_tokens or 0
    return Step(
        index=index,
        label=label,
        input_tokens=usage.input_tokens + write + read,
        output_tokens=usage.output_tokens,
        reasoning_tokens=(getattr(details, "thinking_tokens", 0) or 0) if details else 0,
        cache_read_tokens=read,
        cache_write_tokens=write,
        latency_s=latency,
    )


def _request_kwargs(options: RunOptions, system: str, tools: list[dict]) -> dict:
    """Common arguments of a Messages API call. Automatic prompt caching is a single top-level field."""
    kwargs = dict(model=options.deployment, max_tokens=MAX_TOKENS, system=system, tools=tools)
    if options.prompt_caching:
        kwargs["extra_body"] = {"cache_control": {"type": "ephemeral"}}
    return kwargs


def _system_prompt(options: RunOptions, addendum: str = "") -> str:
    prompt = BASE_SYSTEM_PROMPT.format(patient=Config.patient_name) + addendum
    if options.prompt_caching and options.cold_cache:
        # A unique first line makes the cached prefix unique, so a run never reads a cache written by an earlier run.
        prompt = f"[run {uuid.uuid4().hex[:8]}]\n" + prompt
    return prompt


def _assistant_content(response) -> list[dict]:
    return [b.model_dump(exclude_none=True) for b in response.content]


def _caller_label(block) -> str:
    caller = getattr(block, "caller", None)
    kind = getattr(caller, "type", "direct") if caller else "direct"
    return "direct" if kind == "direct" else "code_execution"


def _run_tools(blocks, step_index: int, run: RunResult, emit: EventCallback) -> list[dict]:
    """Executes tool_use blocks (concurrently) and returns the tool_result blocks."""

    def work(block):
        started = time.perf_counter()
        output = execute_tool(block.name, block.input, run.options)
        return ToolExecution(
            block.name, dict(block.input), output, time.perf_counter() - started, _caller_label(block), step_index
        )

    with ThreadPoolExecutor(max_workers=max(len(blocks), 1)) as pool:
        executions = list(pool.map(work, blocks))

    results = []
    for block, ex in zip(blocks, executions):
        run.tools.append(ex)
        emit("tool", ex)
        results.append({"type": "tool_result", "tool_use_id": block.id, "content": ex.result})
    return results


def _describe_tool_calls(blocks) -> list[str]:
    return [f"{b.name}({', '.join(f'{k}={v!r}' for k, v in b.input.items() if k in ('grievance_id', 'grievance_key'))})" for b in blocks]


# ----------------------------------------------------------------------------------------------
# Approach 1: traditional tool calling
# ----------------------------------------------------------------------------------------------


def run_traditional(
    user_message: str, emit: EventCallback = lambda *_: None, options: RunOptions | None = None
) -> RunResult:
    options = options or RunOptions()
    run = RunResult("Traditional tool calling", options)
    client = _client()
    system = _system_prompt(options)
    tools = tool_definitions(programmatic=False, options=options)
    messages = [{"role": "user", "content": user_message}]
    started = time.perf_counter()
    try:
        for i in range(1, MAX_STEPS + 1):
            t0 = time.perf_counter()
            response = client.messages.create(**_request_kwargs(options, system, tools), messages=messages)
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            step = _record_step(i, "Model decides next action", response, time.perf_counter() - t0)
            step.text = "".join(b.text for b in response.content if b.type == "text")
            step.tool_calls = _describe_tool_calls(tool_blocks)
            run.steps.append(step)
            emit("step", step)

            messages.append({"role": "assistant", "content": _assistant_content(response)})
            if response.stop_reason != "tool_use":
                run.final_text = step.text
                step.label = "Final answer"
                break
            step.label = "Calls " + ", ".join(b.name for b in tool_blocks)
            messages.append({"role": "user", "content": _run_tools(tool_blocks, i, run, emit)})
    except Exception as exc:
        run.error = f"{type(exc).__name__}: {exc}"
    run.wall_time_s = time.perf_counter() - started
    return run


# ----------------------------------------------------------------------------------------------
# Approach 2: programmatic tool calling
# ----------------------------------------------------------------------------------------------


def run_programmatic(
    user_message: str, emit: EventCallback = lambda *_: None, options: RunOptions | None = None
) -> RunResult:
    options = options or RunOptions()
    run = RunResult("Programmatic tool calling", options)
    client = _client()
    system = _system_prompt(options, PROGRAMMATIC_ADDENDUM)
    tools = [
        {"type": Config.code_execution_tool_version, "name": "code_execution"},
        *tool_definitions(programmatic=True, options=options),
    ]
    messages = [{"role": "user", "content": user_message}]
    container_id = None
    started = time.perf_counter()
    try:
        # One model "turn" may span several API requests: each request that pauses for a tool result
        # is a separate (cheap) request, but the model is only re-sampled when the script finishes.
        for i in range(1, MAX_STEPS * 3 + 1):
            kwargs = {"container": container_id} if container_id else {}
            t0 = time.perf_counter()
            response = client.messages.create(**_request_kwargs(options, system, tools), messages=messages, **kwargs)
            if getattr(response, "container", None):
                container_id = response.container.id

            step = _record_step(len(run.steps) + 1, "", response, time.perf_counter() - t0)
            step.text = "".join(b.text for b in response.content if b.type == "text")
            for b in response.content:
                if b.type == "server_tool_use" and b.name == "code_execution":
                    step.code = b.input.get("code", "")
                elif b.type.endswith("code_execution_tool_result"):
                    content = b.content
                    step.code_output = getattr(content, "stdout", "") or ""
                    if getattr(content, "stderr", ""):
                        step.code_output += "\n[stderr]\n" + content.stderr
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            step.tool_calls = _describe_tool_calls(tool_blocks)
            names = ", ".join(b.name for b in tool_blocks)
            if step.code:
                step.label = f"Model writes script; sandbox requests {names or 'tools'}"
            elif tool_blocks:
                step.label = f"Script continues; sandbox requests {names} (no model sampling)"
            elif response.stop_reason == "end_turn":
                step.label = "Final answer (model reads script output)"
            else:
                step.label = "Sandbox continues"
            run.steps.append(step)
            emit("step", step)

            messages.append({"role": "assistant", "content": _assistant_content(response)})
            if response.stop_reason == "tool_use":
                messages.append({"role": "user", "content": _run_tools(tool_blocks, step.index, run, emit)})
            elif response.stop_reason == "pause_turn":
                continue
            else:
                run.final_text = step.text
                break
    except Exception as exc:
        run.error = f"{type(exc).__name__}: {exc}"
    run.wall_time_s = time.perf_counter() - started
    return run
