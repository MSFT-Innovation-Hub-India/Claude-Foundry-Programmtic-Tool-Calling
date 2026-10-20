"""Styling for the Streamlit UI: responsive cards, KPI tiles and wrapping tables (no scrolling grids)."""

CSS = """
<style>
:root {
  --blue: #0F6CBD; --blue-soft: #E6F0FA;
  --green: #107C41; --green-soft: #E3F4EA;
  --ink: #1B2430; --muted: #5B6675; --line: #E1E6EE; --card: #FFFFFF;
}
.block-container {max-width: 1600px !important; padding: 1.2rem clamp(0.8rem, 2.5vw, 2.5rem) 3rem;}
header[data-testid="stHeader"] {background: transparent;}
[data-testid="stSidebar"], [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}

/* hero */
.hero {background: linear-gradient(120deg, #0B3C6F 0%, #0F6CBD 55%, #2B88D8 100%); color: #fff;
  border-radius: 14px; padding: 1.1rem 1.5rem; margin-bottom: 1rem;
  box-shadow: 0 4px 14px rgba(15,108,189,.25);}
.hero h1 {font-size: clamp(1.25rem, 2.2vw, 1.75rem); margin: 0; font-weight: 650; letter-spacing: -.01em; color:#fff;}
.hero p {margin: .25rem 0 .7rem; opacity: .9; font-size: .92rem;}
.chip {display: inline-block; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
  border-radius: 999px; padding: .12rem .65rem; margin: 0 .35rem .3rem 0; font-size: .75rem;}

/* chat bubbles */
.bubble {display: flex; gap: .6rem; align-items: flex-start; margin: .35rem 0;}
.bubble .av {flex: 0 0 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; font-size: 1rem;}
.bubble .msg {background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .55rem .9rem;
  max-width: 820px; font-size: .95rem;}
.bubble.bot .av {background: var(--blue-soft);}
.bubble.user {justify-content: flex-end;}
.bubble.user .av {background: #FCE9D9; order: 2;}
.bubble.user .msg {background: var(--blue); color: #fff; border-color: var(--blue);}

/* panels */
.ph {display: flex; align-items: center; gap: .75rem; padding: .7rem .9rem; border-radius: 12px;
  background: var(--card); border: 1px solid var(--line); margin-bottom: .6rem;}
.ph .num {flex: 0 0 34px; height: 34px; border-radius: 9px; display: grid; place-items: center;
  font-weight: 700; color: #fff;}
.ph.trad {border-left: 5px solid var(--blue);} .ph.trad .num {background: var(--blue);}
.ph.prog {border-left: 5px solid var(--green);} .ph.prog .num {background: var(--green);}
.ph .pt {font-weight: 650; font-size: 1.05rem;} .ph .ps {color: var(--muted); font-size: .82rem; line-height: 1.3;}

/* KPI tiles */
.kpis {display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: .5rem; margin: .4rem 0 .8rem;}
.kpi {background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: .5rem .6rem;}
.kpi .l {color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .04em;}
.kpi .v {font-size: 1.35rem; font-weight: 650; line-height: 1.25;}
.kpi.hi {background: var(--blue-soft); border-color: #BCD6F0;}
.prog-col .kpi.hi {background: var(--green-soft); border-color: #B9E0C8;}

.sec {font-weight: 650; margin: 1rem 0 .4rem; font-size: .95rem;}

/* wrapping tables: no horizontal scrolling */
table.t {width: 100%; border-collapse: separate; border-spacing: 0; background: var(--card);
  border: 1px solid var(--line); border-radius: 10px; overflow: hidden; font-size: .8rem; table-layout: auto;}
table.t th {background: #F0F3F8; color: var(--muted); font-weight: 600; text-align: left; padding: .45rem .55rem;
  font-size: .7rem; text-transform: uppercase; letter-spacing: .03em;}
table.t td {padding: .45rem .55rem; border-top: 1px solid var(--line); vertical-align: top;
  overflow-wrap: anywhere; word-break: break-word;}
table.t td.n, table.t th.n {text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums;}
table.t tr.tot td {font-weight: 650; background: #F7F9FC;}
table.t code {font-size: .74rem; background: #F0F3F8; padding: .05rem .3rem; border-radius: 4px; overflow-wrap: normal; word-break: normal;}
.badge {display: inline-block; padding: .05rem .5rem; border-radius: 999px; font-size: .7rem; font-weight: 600; white-space: nowrap;}
.badge.model {background: var(--blue-soft); color: var(--blue);}
.badge.sandbox {background: var(--green-soft); color: var(--green);}
.badge.good {background: var(--green-soft); color: var(--green);}
.badge.bad {background: #FDE7E9; color: #B3261E;}
.badge.neutral {background: #EEF1F6; color: var(--muted);}

/* token bars */
.bars {background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: .8rem 1rem;}
.bar-row {display: grid; grid-template-columns: 120px 1fr 90px; gap: .6rem; align-items: center; margin: .35rem 0; font-size: .82rem;}
.bar {display: flex; height: 18px; border-radius: 5px; overflow: hidden; background: #EEF1F6;}
.bar span {display: block; height: 100%;}
.seg-in {background: #0F6CBD;} .seg-re {background: #8764B8;} .seg-out {background: #F2A33A;}
.seg-trad {display: block; height: 100%; background: var(--blue);} .seg-prog {display: block; height: 100%; background: var(--green);}
.bar.ghosted {position: relative;}
.bar.ghosted .ghost {position: absolute; left: 0; top: 0; height: 100%; background: #CDD6E3;}
.bar.ghosted .front {position: absolute; left: 0; top: 0;}
.legend .ghostkey {background: #CDD6E3;}
.legend i.seg-trad, .legend i.seg-prog {display: inline-block; height: 10px;}

/* stacked cells inside the token table */
.kv {display: flex; justify-content: space-between; gap: .8rem; white-space: nowrap; line-height: 1.45;}
.kv span {color: var(--muted); font-size: .72rem;}
.kv b {font-weight: 600; font-variant-numeric: tabular-nums;}
.kv b.dim {color: #A6AFBC; font-weight: 400;}
.kv b.saved {color: var(--green);}
table.t td.stack {min-width: 108px;}
table.t tr.cost td {background: #F7F9FC; border-top: 2px solid var(--line);}
table.t tr.cost s {color: var(--muted);}
.good-txt {color: var(--green); font-weight: 600;}
.cfg {font-weight: 600; font-size: .8rem; margin: .6rem 0 .1rem; color: var(--ink);}
.cfg:first-child {margin-top: 0;}
.chip.on {background: rgba(255,255,255,.95); color: #0B3C6F; font-weight: 600;}
.legend {font-size: .75rem; color: var(--muted); margin-top: .4rem;}
.legend i {display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 .3rem 0 .8rem; vertical-align: middle;}

/* live activity */
.live {background: var(--card); border: 1px dashed #BCD0E8; border-radius: 10px; padding: .6rem .9rem; font-size: .85rem;}
.live div {margin: .2rem 0; overflow-wrap: anywhere;}
.pulse {color: var(--muted); animation: p 1.2s ease-in-out infinite;}
@keyframes p {50% {opacity: .35;}}

.note {color: var(--muted); font-size: .8rem; margin-top: .6rem; line-height: 1.45;}

/* stack the two panels on narrow screens; each panel always fills its row */
.st-key-panels [data-testid="stHorizontalBlock"] {flex-wrap: wrap !important; gap: 1.2rem; width: 100%;}
.st-key-panels [data-testid="stColumn"] {flex: 1 1 440px !important; width: auto !important; min-width: 0 !important; max-width: 100% !important;}

@media (max-width: 640px) {
  .bar-row {grid-template-columns: 1fr; gap: .15rem;}
  .hero {padding: .9rem 1rem;}
}
</style>
"""
