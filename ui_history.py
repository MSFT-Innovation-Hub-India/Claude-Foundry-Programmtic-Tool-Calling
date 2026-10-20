"""History view: averages per configuration, a cost chart with the no-cache equivalent, and the latest runs."""
from __future__ import annotations

import streamlit as st

from core import history
from core.config import Config

APPROACH_NAME = {"trad": "Traditional", "prog": "Programmatic"}
APPROACH_CLASS = {"trad": "seg-trad", "prog": "seg-prog"}


def _md(markup: str) -> None:
    st.markdown(markup.replace("\n", ""), unsafe_allow_html=True)


def _n(value: float) -> str:
    return f"{value:,.0f}"


def saving_badge(cached: float, no_cache: float) -> str:
    """Green when caching reduced the cost index versus the same tokens without caching."""
    if not no_cache:
        return "<span class='badge neutral'>–</span>"
    pct = (no_cache - cached) / no_cache * 100
    if pct > 0.5:
        return f"<span class='badge good'>▼ {pct:.0f}%</span>"
    if pct < -0.5:
        return f"<span class='badge bad'>▲ {abs(pct):.0f}%</span>"
    return "<span class='badge neutral'>0%</span>"


def _cost_chart(rows: list[dict]) -> str:
    """One bar per approach: solid = cost with caching, pale ghost = cost of the same tokens without caching."""
    peak = max((r["cost_index_no_cache"] for r in rows), default=1) or 1
    out = "<div class='sec'>Cost index: with caching vs without</div><div class='bars'>"
    for cfg in dict.fromkeys(r["config"] for r in rows):
        out += f"<div class='cfg'>{cfg}</div>"
        for r in (x for x in rows if x["config"] == cfg):
            out += (f"<div class='bar-row'><div>{APPROACH_NAME[r['approach']]}</div><div class='bar ghosted'>"
                    f"<span class='ghost' style='width:{r['cost_index_no_cache'] / peak * 100:.2f}%'></span>"
                    f"<span class='{APPROACH_CLASS[r['approach']]} front' style='width:{r['cost_index'] / peak * 100:.2f}%'></span>"
                    f"</div><div class='n'><b>{_n(r['cost_index'])}</b> "
                    f"{saving_badge(r['cost_index'], r['cost_index_no_cache'])}</div></div>")
    return out + ("<div class='legend'><i class='ghostkey'></i>same tokens without caching"
                  "<i class='seg-trad'></i>traditional with caching<i class='seg-prog'></i>programmatic with caching</div>"
                  "</div>")


def _token_chart(rows: list[dict]) -> str:
    peak = max((r["total"] for r in rows), default=1) or 1
    out = "<div class='sec'>Total tokens (input + output)</div><div class='bars'>"
    for cfg in dict.fromkeys(r["config"] for r in rows):
        out += f"<div class='cfg'>{cfg}</div>"
        for r in (x for x in rows if x["config"] == cfg):
            out += (f"<div class='bar-row'><div>{APPROACH_NAME[r['approach']]}</div><div class='bar'>"
                    f"<span class='{APPROACH_CLASS[r['approach']]}' style='width:{r['total'] / peak * 100:.2f}%'></span></div>"
                    f"<div class='n'><b>{_n(r['total'])}</b></div></div>")
    return out + "</div>"


def render_history() -> None:
    records = st.session_state.get("history", [])
    st.markdown("### Run history")
    if not records:
        _md("<div class='note'>No runs recorded yet. Every run is saved to <code>runs/history.jsonl</code>. Run the "
            "request again within about 5 minutes to see the prompt cache warm and the saving grow.</div>")
        return

    rows = history.summarise(records)
    head = ("<tr><th>Configuration</th><th>Approach</th><th class='n'>Runs</th><th class='n'>Total tokens</th>"
            "<th class='n'>Cache read</th><th class='n'>Cost, no cache</th><th class='n'>Cost, cached</th>"
            "<th>Caching effect</th></tr>")
    body = "".join(
        f"<tr><td>{r['config']}</td><td>{APPROACH_NAME[r['approach']]}</td><td class='n'>{r['runs']}</td>"
        f"<td class='n'>{_n(r['total'])}</td><td class='n'>{_n(r['cache_read'])}</td>"
        f"<td class='n'>{_n(r['cost_index_no_cache'])}</td><td class='n'><b>{_n(r['cost_index'])}</b></td>"
        f"<td>{saving_badge(r['cost_index'], r['cost_index_no_cache'])}</td></tr>"
        for r in sorted(rows, key=lambda x: (x["config"], x["approach"]))
    )
    _md("<div class='sec'>Average per configuration</div>" f"<table class='t'>{head}{body}</table>")

    left, right = st.columns(2)
    with left:
        _md(_cost_chart(rows))
    with right:
        _md(_token_chart(rows))

    _md(f"<div class='note'><b>Cost index</b> weights tokens by an assumed price model: uncached input = 1, cache read = "
        f"{Config.cache_read_multiplier:g}×, cache write = {Config.cache_write_multiplier:g}×, output (incl. reasoning) = "
        f"{Config.output_multiplier:g}×. It shows relative economics, not a bill; adjust the multipliers in "
        f"<code>.env</code>. <b>Cost, no cache</b> is the same tokens priced without caching. Total tokens are the same "
        f"either way: caching changes the <i>price</i> of the repeated input, not how much the model reads.</div>")

    log_head = ("<tr><th>Time</th><th>Configuration</th><th>Approach</th><th>Cache</th><th class='n'>Total tokens</th>"
                "<th class='n'>Cache read</th><th class='n'>Cost, cached</th><th>Effect</th>"
                "<th class='n'>Calls</th><th class='n'>Time</th></tr>")
    log = ""
    for rec in reversed(records[-12:]):
        for key in ("trad", "prog"):
            m = rec[key]
            if m.get("error"):
                log += (f"<tr><td>{rec['ts']}</td><td>{rec['config']}</td><td>{APPROACH_NAME[key]}</td>"
                        f"<td colspan='7'><span class='badge bad'>failed</span> {m['error'][:80]}</td></tr>")
                continue
            warm = "<span class='badge good'>warm</span>" if m.get("cache_warm") else "<span class='badge neutral'>cold</span>"
            log += (f"<tr><td>{rec['ts']}</td><td>{rec['config']}</td><td>{APPROACH_NAME[key]}</td><td>{warm}</td>"
                    f"<td class='n'>{_n(m['total'])}</td><td class='n'>{_n(m['cache_read'])}</td>"
                    f"<td class='n'>{_n(m['cost_index'])}</td>"
                    f"<td>{saving_badge(m['cost_index'], m.get('cost_index_no_cache', m['cost_index']))}</td>"
                    f"<td class='n'>{m['model_calls']}</td><td class='n'>{m['wall_time_s']}s</td></tr>")
    _md("<div class='sec'>Recent runs</div>" f"<table class='t'>{log_head}{log}</table>")

    def _clear() -> None:
        history.clear()
        st.session_state["history"] = []

    st.button("Clear history", on_click=_clear)
