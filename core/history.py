"""Run history: every run is appended to runs/history.jsonl so configurations can be compared across runs and restarts."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from .agents import RunResult
from .config import Config, RunOptions


def load() -> list[dict]:
    if not Config.history_file.exists():
        return []
    records = []
    for line in Config.history_file.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def append(options: RunOptions, trad: RunResult, prog: RunResult) -> dict:
    record = {
        "ts": datetime.now().strftime("%d %b %H:%M:%S"),
        "config": options.label,
        "jira_payload": options.jira_payload,
        "prompt_caching": options.prompt_caching,
        "cold_cache": options.cold_cache,
        "deployment": options.deployment,
        "trad": trad.to_record(),
        "prog": prog.to_record(),
    }
    Config.history_file.parent.mkdir(exist_ok=True)
    with Config.history_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def clear() -> None:
    Config.history_file.unlink(missing_ok=True)


def summarise(records: list[dict]) -> list[dict]:
    """Average of the successful runs per (configuration, approach), in the order configurations first appeared."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    meta: dict[tuple, dict] = {}
    for rec in records:
        for key in ("trad", "prog"):
            if not rec[key].get("error"):
                gk = (rec["config"], key)
                groups[gk].append(rec[key])
                meta[gk] = {"jira_payload": rec["jira_payload"], "prompt_caching": rec["prompt_caching"]}
    rows = []
    for (config, key), items in groups.items():
        def avg(field: str) -> float:
            return sum(i.get(field, i["cost_index"]) for i in items) / len(items)

        rows.append({
            "config": config, "approach": key, "runs": len(items), **meta[(config, key)], "input": avg("input"),
            "cache_read": avg("cache_read"), "cache_write": avg("cache_write"), "reasoning": avg("reasoning"),
            "output": avg("output"), "total": avg("total"), "cost_index": avg("cost_index"),
            "cost_index_no_cache": avg("cost_index_no_cache"),
            "warm_runs": sum(1 for i in items if i.get("cache_warm")),
            "model_calls": avg("model_calls"), "wall_time_s": avg("wall_time_s"),
        })
    return rows
