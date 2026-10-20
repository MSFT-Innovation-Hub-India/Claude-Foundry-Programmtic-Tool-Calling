"""Streamlit UI: traditional tool calling vs. programmatic tool calling, side by side."""
from __future__ import annotations

import html
import queue
import threading

import streamlit as st

from core import history
from core.agents import RunResult, run_programmatic, run_traditional
from core.config import Config, RunOptions
from ui_history import render_history
from ui_style import CSS

FIXED_QUESTION = "Can you get me the status of my claims?"
PANELS = {
    "trad": ("trad", "1", "Traditional tool calling",
             "After every tool call the result goes back to the model, which decides what to do next."),
    "prog": ("prog", "2", "Programmatic tool calling",
             "Claude writes one script; the sandbox runs the tools and returns a single result to the model."),
}

st.set_page_config(
    page_title="Claude tool calling on Foundry", page_icon="🩺", layout="wide", initial_sidebar_state="collapsed"
)
st.markdown(CSS, unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape(str(value))


def n(value: int) -> str:
    return f"{value:,}"


def md_html(markup: str) -> None:
    # Single-line HTML: blank lines or indentation would make Markdown treat it as a code block.
    st.markdown(markup.replace("\n", ""), unsafe_allow_html=True)


# Settings live in a popover (no sidebar). Their widget keys (opt_*) are read from session_state on every rerun,
# so the header chips and the next run always reflect the current switches.
if "history" not in st.session_state:
    st.session_state["history"] = history.load()


def current_options() -> RunOptions:
    """Per-run switches: the Settings popover (deployment, Jira payload, e-mail); caching comes from .env (on by default)."""
    ss = st.session_state
    return RunOptions(
        deployment=(ss.get("opt_deployment") or Config.default_deployment).strip(),
        jira_payload=ss.get("opt_jira", Config.default_jira_payload),
        prompt_caching=Config.default_prompt_caching,
        cold_cache=Config.default_cold_cache,
        email_mode="send" if ss.get("opt_email", Config.default_email_mode == "send") else "dry_run",
    )


options = current_options()

# ------------------------------------------------------------------ header and greeting
md_html(f"""
<div class="hero">
<h1>🩺 Insurance claims assistant</h1>
<p>Claude on Microsoft Foundry · the same question and tools, answered with two tool-calling strategies.</p>
<span class="chip">Patient: {esc(Config.patient_name)}</span>
<span class="chip">Model: {esc(options.deployment)}</span>
<span class="chip">Auth: Entra ID</span>
<span class="chip">Jira payload: {esc(options.jira_payload)}</span>
<span class="chip {'on' if options.prompt_caching else ''}">Prompt caching: {'ON' if options.prompt_caching else 'off'}</span>
</div>
""")


def bubble(kind: str, text: str) -> None:
    avatar = "🤖" if kind == "bot" else "🧑"
    md_html(f'<div class="bubble {kind}"><div class="av">{avatar}</div><div class="msg">{esc(text)}</div></div>')


bubble("bot", f"Hey {Config.patient_name}, how can I help you today with your Insurance Claims?")
col_in, col_cfg, col_btn = st.columns([6, 1.3, 1], vertical_alignment="bottom")
col_in.text_input("Your message", value=FIXED_QUESTION, disabled=True, label_visibility="collapsed")
with col_cfg.popover("⚙️ Settings", use_container_width=True):
    st.markdown(f"**Patient:** {Config.patient_name} · **Escalation:** {Config.escalation_email}")
    st.markdown(f"**Foundry resource:** `{Config.foundry_resource}`")
    st.text_input(
        "Claude deployment", value=Config.default_deployment, key="opt_deployment",
        help="Programmatic tool calling needs a deployment Hosted on Anthropic (not Hosted on Azure).",
    )
    st.radio(
        "Jira tool output", ["raw", "compact"], index=0 if Config.default_jira_payload == "raw" else 1,
        key="opt_jira",
        format_func=lambda v: "Raw Jira API payload (realistic)" if v == "raw" else "Trimmed to 7 fields by the tool",
        help="Raw = the full Jira REST response (~1.7k tokens per ticket) goes to the model (traditional) or to the "
             "sandbox script (programmatic). Compact removes most of what programmatic calling can save.",
    )
    st.checkbox(
        "Send real escalation e-mails (WorkIQ)", value=Config.default_email_mode == "send", key="opt_email",
        help="Both approaches escalate the same unassigned grievance, so a live run sends two e-mails.",
    )
    st.caption("Auth: Microsoft Entra ID (az login) for Foundry and Azure SQL; WorkIQ CLI sign-in for e-mail.")
run_clicked = col_btn.button("Send", type="primary", use_container_width=True)
options = current_options()


# ------------------------------------------------------------------ rendering helpers
def panel_header(key: str) -> None:
    css, num, title, sub = PANELS[key]
    md_html(f'<div class="ph {css}"><div class="num">{num}</div><div><div class="pt">{title}</div>'
            f'<div class="ps">{sub}</div></div></div>')


def kv(items: list[tuple[str, int, str]]) -> str:
    """Stacked label/value lines for one table cell. Zero values are dimmed; classes: '' | 'saved' (green)."""
    return "".join(
        f"<div class='kv'><span>{label}</span><b class='{'dim' if value == 0 else cls}'>{n(value)}</b></div>"
        for label, value, cls in items
    )


def token_cell(input_t: int, reasoning_t: int, output_t: int) -> str:
    return kv([("Input", input_t, ""), ("Reasoning", reasoning_t, ""), ("Output", output_t, "")])


def cache_cell(read_t: int, write_t: int) -> str:
    return kv([("Read ▼", read_t, "saved"), ("Write", write_t, "")])


def cache_row(run: RunResult, colspan: int) -> str:
    """Actual token counts only: how much of the input was served from the prompt cache (green when any was)."""
    read, write, total_in = run.cache_read_tokens, run.cache_write_tokens, run.input_tokens
    if read > 0 and total_in:
        text = (f"<span class='good-txt'>▼ Prompt cache: {n(read)} of {n(total_in)} input tokens "
                f"({read / total_in * 100:.0f}%) read from cache</span> · {n(write)} written to cache")
    else:
        text = f"Prompt cache: no tokens read from cache · {n(write)} written to cache"
    return f"<tr class='cost'><td colspan='{colspan}'>{text}</td></tr>"


def steps_table(run: RunResult) -> str:
    head = ("<tr><th>#</th><th>What happened</th><th>Tokens</th><th>Cache</th><th class='n'>Total</th>"
            "<th class='n'>Time</th></tr>")
    rows = "".join(
        f"<tr><td>{s.index}</td><td>{esc(s.label)}</td>"
        f"<td class='stack'>{token_cell(s.input_tokens, s.reasoning_tokens, s.visible_output_tokens)}</td>"
        f"<td class='stack'>{cache_cell(s.cache_read_tokens, s.cache_write_tokens)}</td>"
        f"<td class='n'>{n(s.total_tokens)}</td><td class='n'>{s.latency_s:.1f}s</td></tr>"
        for s in run.steps
    )
    total = ("<tr class='tot'><td></td><td>Total</td>"
             f"<td class='stack'>{token_cell(run.input_tokens, run.reasoning_tokens, run.visible_output_tokens)}</td>"
             f"<td class='stack'>{cache_cell(run.cache_read_tokens, run.cache_write_tokens)}</td>"
             f"<td class='n'>{n(run.total_tokens)}</td><td class='n'>{run.wall_time_s:.1f}s</td></tr>")
    cost = cache_row(run, 6) if run.options.prompt_caching else ""
    return f"<table class='t'>{head}{rows}{total}{cost}</table>"


def tools_table(run: RunResult) -> str:
    head = "<tr><th>#</th><th>Tool</th><th>Arguments</th><th>Called from</th><th class='n'>Time</th></tr>"
    rows = ""
    for t in run.tools:
        args = ", ".join(f"{k}={str(v)[:60]}" for k, v in t.arguments.items())
        badge = ("<span class='badge sandbox'>sandbox script</span>" if t.caller == "code_execution"
                 else "<span class='badge model'>model (direct)</span>")
        rows += (f"<tr><td>{t.step_index}</td><td><code>{esc(t.name).replace('_', '_<wbr>')}</code></td>"
                 f"<td>{esc(args)}</td><td>{badge}</td><td class='n'>{t.duration_s:.2f}s</td></tr>")
    return f"<table class='t'>{head}{rows}</table>"


def cache_status_line(run: RunResult) -> str:
    """One line telling whether this run started with a warm prompt cache (reused an earlier request's cache)."""
    if not run.options.prompt_caching:
        return ""
    if run.cache_warm:
        badge, text = "<span class='badge good'>Cache warm</span>", "reused the prefix cached by an earlier request"
    else:
        badge, text = ("<span class='badge neutral'>Cache cold</span>",
                       "first request: wrote the cache; later calls in this run read it")
    return f"<div class='note' style='margin:0 0 .5rem'>{badge} {text}</div>"


def render_result(run: RunResult, key: str) -> None:
    panel_header(key)
    md_html(cache_status_line(run) or "<div class='note' style='margin:0 0 .5rem'>Prompt caching off</div>")
    if run.error:
        st.error(run.error)
    with st.container(border=True):
        st.markdown(run.final_text or "_No answer produced._")
    md_html('<div class="sec">Token usage per step</div>' + steps_table(run))
    md_html('<div class="sec">Tool executions</div>' + tools_table(run))

    code = next((s.code for s in run.steps if s.code), "")
    if code:
        with st.expander("Script Claude wrote and ran in the sandbox"):
            st.code(code, language="python", wrap_lines=True)
        out = next((s.code_output for s in run.steps if s.code_output), "")
        if out:
            with st.expander("Sandbox output returned to the model"):
                st.code(out, language="json", wrap_lines=True)
    with st.expander("Raw tool results"):
        for t in run.tools:
            st.markdown(f"`{t.name}`")
            st.code(t.result[:3000], language="json", wrap_lines=True)


def render_token_mix(t: RunResult, p: RunResult) -> None:
    peak = max(t.total_tokens, p.total_tokens, 1)

    def bar(label: str, r: RunResult) -> str:
        def w(v):
            return f"{v / peak * 100:.2f}%"
        return (f"<div class='bar-row'><div>{label}</div><div class='bar'>"
                f"<span class='seg-in' style='width:{w(r.input_tokens)}' title='input'></span>"
                f"<span class='seg-re' style='width:{w(r.reasoning_tokens)}' title='reasoning'></span>"
                f"<span class='seg-out' style='width:{w(r.visible_output_tokens)}' title='output'></span></div>"
                f"<div class='n'><b>{n(r.total_tokens)}</b></div></div>")

    md_html("<div class='sec'>Token mix</div><div class='bars'>" + bar("Traditional", t) + bar("Programmatic", p)
            + "<div class='legend'><i class='seg-in'></i>input<i class='seg-re'></i>reasoning"
              "<i class='seg-out'></i>output</div></div>")
    md_html("<div class='note'>Output tokens exclude reasoning (billed output = reasoning + output). Programmatic calling "
            "adds a fixed code-execution overhead (~3.7k input tokens); it pays off when tool results are large or "
            "numerous, because they stay in the sandbox instead of being re-sent to the model on every later call. "
            "Run the request again within about 5 minutes: the prompt cache is then warm from the first call and the "
            "caching saving grows.</div>")


# ------------------------------------------------------------------ run
if run_clicked:
    st.session_state.pop("results", None)
    bubble("user", FIXED_QUESTION)

    with st.container(key="panels"):
        left, right = st.columns(2)
        with left:
            panel_header("trad")
            live_trad = st.empty()
        with right:
            panel_header("prog")
            live_prog = st.empty()
    live = {"trad": live_trad, "prog": live_prog}

    events: queue.Queue = queue.Queue()
    results: dict[str, RunResult] = {}
    run_options = options  # frozen snapshot: switches changed during the run do not affect it

    def worker(key, fn):
        results[key] = fn(FIXED_QUESTION, lambda kind, obj: events.put((key, kind, obj)), run_options)
        events.put((key, "done", None))

    for key, fn in (("trad", run_traditional), ("prog", run_programmatic)):
        threading.Thread(target=worker, args=(key, fn), daemon=True).start()

    def live_line(kind: str, obj) -> str:
        if kind == "step":
            cached = f" · cached {n(obj.cache_read_tokens)}" if run_options.prompt_caching else ""
            return (f"🧠 <b>Step {obj.index}</b> · {esc(obj.label)} "
                    f"<span class='badge neutral'>in {n(obj.input_tokens)}{cached} · reasoning "
                    f"{n(obj.reasoning_tokens)} · out {n(obj.visible_output_tokens)}</span>")
        where = "sandbox" if obj.caller == "code_execution" else "model"
        return f"🔧 <code>{esc(obj.name)}</code> called by {where} · {obj.duration_s:.2f}s"

    lines = {"trad": [], "prog": []}
    pending = {"trad", "prog"}
    for key in live:
        live[key].markdown("<div class='live'><div class='pulse'>⏳ starting…</div></div>", unsafe_allow_html=True)
    while pending:
        try:
            key, kind, obj = events.get(timeout=0.3)
        except queue.Empty:
            continue
        if kind == "done":
            pending.discard(key)
            continue
        lines[key].append(f"<div>{live_line(kind, obj)}</div>")
        live[key].markdown(
            "<div class='live'>" + "".join(lines[key]) + "<div class='pulse'>⏳ working…</div></div>",
            unsafe_allow_html=True,
        )

    st.session_state["results"] = results
    history.append(run_options, results["trad"], results["prog"])
    st.session_state["history"] = history.load()
    st.rerun()

# ------------------------------------------------------------------ results (persist across reruns)
results = st.session_state.get("results")
if results:
    bubble("user", FIXED_QUESTION)
    with st.container(key="panels"):
        left, right = st.columns(2)
        with left:
            render_result(results["trad"], "trad")
        with right:
            render_result(results["prog"], "prog")
    st.divider()
    render_token_mix(results["trad"], results["prog"])

st.divider()
render_history()
