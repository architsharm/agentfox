"""FastAPI wrapper around `agent.py`'s `run_turn()`, for a live-in-the-browser
deployment of this demo (Vercel's Python runtime serves an ASGI app directly, same
pattern as `api/index.py` — see that file's docstring for the reasoning this mirrors).

Chat history is kept **client-side**, not server-side: the browser sends the full
prior turn list with every request, and this handler reconstructs a `SessionState`
from it. That is a deliberate fit for a stateless serverless function — there is no
guarantee two requests in the same conversation land on the same warm instance, so
any server-held-history design would silently lose turns. The governed state that
actually matters (capability grants, taint marks, audit trail, order/customer
records) lives in Postgres via `NOMETRIA_DATABASE_URL`, not in this file.

Local dev:  uvicorn web:app --reload --port 8000
Deployed:   this module's `app` is Vercel's entrypoint (see vercel.json).
"""

from __future__ import annotations

import json
import os

import _env  # noqa: F401  -- must run before anything imports agentfox settings
import seed_demo_agent
from agent import MissingApiKey, SessionState, run_turn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from recorded_scenarios import (
    ALLOW_TURNS,
    BLOCK_TURNS,
    BULK_TURNS,
    COMPOSED_TURNS,
    ESCALATE_TURNS,
)

from agentfox.core.db import init_db, session_scope
from agentfox.runtime.autoguard import Blocked

app = FastAPI(title="AgentFox red-team live demo (LangChain)")

_seeded = False


def _ensure_seeded() -> None:
    """Idempotent, lazy seeding — safe to call on every cold start. A Postgres-backed
    deployment has no separate `python seed_demo_agent.py` step to run by hand, so
    the first request (any request) does it instead. `seed_demo_agent.main()` is
    genuinely idempotent at the DB level (capability grants are guarded explicitly;
    `policy.store.save_policy` skips creating a new version when the body is
    unchanged — checked directly, not assumed), not just via this in-process flag,
    so a cold start on a fresh instance re-running it is harmless either way. The
    flag just avoids the redundant DB round-trips on a warm instance."""
    global _seeded
    if _seeded:
        return
    seed_demo_agent.main()
    _seeded = True


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    history: list[ChatTurn] = []


@app.on_event("startup")
def _startup() -> None:
    _ensure_seeded()


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    _ensure_seeded()
    state = SessionState(session_id=req.session_id or "web-session")
    for turn in req.history:
        state.history.append(
            HumanMessage(content=turn.content)
            if turn.role == "user"
            else AIMessage(content=turn.content)
        )
    try:
        return run_turn(req.message, state)
    except Blocked as exc:
        # This demo agent runs in enforce mode (agent.py's `agentfox.auto(...,
        # mode="enforce")`), so a pre-flight verdict on the raw text going INTO the
        # model — a prompt-injection or jailbreak attempt typed straight into the
        # chat box, not a tool call — actually stops the call here, rather than
        # just being recorded. Tool-call blocks/escalations (a refund over the
        # capability's ceiling, an email needing approval) never raise this: they
        # come back as a normal `run_turn()` result with `blocked`/`escalated` set,
        # since `McpGovernor` enforces capability grants unconditionally, same as
        # production. This is specifically the LLM-input-level path.
        decision = exc.result
        return {
            "reply": (
                "This request was blocked before it reached the model: "
                f"{decision.reason or 'blocked by policy'}"
            ),
            "error": None,
            "blocked": True,
            "escalated": False,
            "rules_fired": [r.get("rule_id") for r in decision.rules_fired],
            "tool_calls": [],
        }
    except MissingApiKey as exc:
        return {
            "reply": str(exc),
            "error": "missing_api_key",
            "blocked": False,
            "escalated": False,
            "rules_fired": [],
            "tool_calls": [],
        }
    except Exception as exc:  # noqa: BLE001 — this is the top of the stack for a
        # live demo request; the LLM client's own timeout (agent.py's
        # _LLM_TIMEOUT_S) and the AgentExecutor's max_execution_time both bound how
        # long this can legitimately take, but a live network call can still fail
        # in ways neither anticipates (a rate limit, a transient 5xx from the
        # provider). Surface it as a clean chat-shaped response instead of a bare
        # 500 with no body — found live: an earlier version of this handler let
        # exactly that kind of failure crash the request with nothing useful shown
        # to whoever was watching.
        return {
            "reply": f"The agent hit an error talking to the model provider: {exc}",
            "error": "llm_call_failed",
            "blocked": False,
            "escalated": False,
            "rules_fired": [],
            "tool_calls": [],
        }


@app.post("/api/redteam")
def redteam() -> dict:
    """Runs the same built-in probe suite `agentfox test redteam` does, against this
    demo's seeded agent, and returns the campaign summary as JSON."""
    _ensure_seeded()
    from support_tools import AGENT_SLUG

    from agentfox.capabilities.evaluation.redteam import BUILTIN_PROBES, run_campaign

    init_db()
    with session_scope() as session:
        campaign = run_campaign(session, AGENT_SLUG, name="web-demo-run")
        summary = campaign.summary_json
    return {
        "probes_run": summary["probes_run"],
        "attacks_run": summary["attacks_run"],
        "attacks_blocked": summary["attacks_blocked"],
        "attacks_succeeded": summary["attacks_succeeded"],
        "benign_probes_run": summary["benign_probes_run"],
        "benign_false_positives": summary["benign_false_positives"],
        "recall": summary["recall"],
        "precision": summary["precision"],
        "probes": summary["probes"],
        "total_probes_available": len(BUILTIN_PROBES),
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "has_llm_key": bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        ),
    }


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>AgentFox — live governed support agent</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f7f9f8;
    --surface: #ffffff;
    --surface-2: #eef2f1;
    --border: #dbe3e0;
    --text: #10201c;
    --text-dim: #56655f;
    --text-faint: #8a9993;
    --brand: #0d7d6f;
    --brand-ink: #ffffff;
    --brand-soft: #e2f3ef;
    --allow: #1a8a4a;
    --allow-soft: #e5f6ec;
    --block: #c8331f;
    --block-soft: #fdece9;
    --escalate: #b5720a;
    --escalate-soft: #fdf1de;
    --shadow: 0 1px 2px rgba(16, 32, 28, 0.04), 0 8px 24px -12px rgba(16, 32, 28, 0.12);
    --mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0d1412;
      --surface: #141d1a;
      --surface-2: #1a2521;
      --border: #253530;
      --text: #eaf3f0;
      --text-dim: #9fb3ac;
      --text-faint: #66796f;
      --brand: #2fd1b8;
      --brand-ink: #06211c;
      --brand-soft: #12312a;
      --allow: #3ecb7f;
      --allow-soft: #12301f;
      --block: #ff6b57;
      --block-soft: #3a1712;
      --escalate: #f0a93f;
      --escalate-soft: #3a2a0d;
      --shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 8px 24px -12px rgba(0, 0, 0, 0.5);
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: var(--sans);
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 2rem 1.5rem 4rem;
  }
  .wrap { max-width: 1180px; margin: 0 auto; }

  header.top { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; margin-bottom: 1.75rem; flex-wrap: wrap; }
  .brand-row { display: flex; align-items: center; gap: 0.7rem; }
  .mark { width: 34px; height: 34px; border-radius: 9px; background: var(--brand); color: var(--brand-ink); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 1.05rem; font-family: var(--mono); flex-shrink: 0; }
  h1 { font-size: 1.15rem; margin: 0; letter-spacing: -0.01em; }
  .tagline { font-size: 0.85rem; color: var(--text-dim); margin: 0.15rem 0 0; }
  .mode-badge { display: inline-flex; align-items: center; gap: 0.4rem; font-family: var(--mono); font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; padding: 0.4rem 0.7rem; border-radius: 999px; background: var(--block-soft); color: var(--block); border: 1px solid color-mix(in srgb, var(--block) 30%, transparent); white-space: nowrap; }
  .mode-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--block); }

  p.intro { font-size: 0.88rem; color: var(--text-dim); line-height: 1.55; margin: 0 0 1.5rem; max-width: 70ch; }
  p.intro code { font-family: var(--mono); font-size: 0.83em; background: var(--surface-2); padding: 0.1em 0.35em; border-radius: 4px; }

  .grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 1.25rem; align-items: start; }
  @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }

  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); overflow: hidden; }
  .panel-head { display: flex; align-items: center; justify-content: space-between; padding: 0.9rem 1.1rem; border-bottom: 1px solid var(--border); }
  .panel-head h2 { font-size: 0.82rem; font-weight: 600; margin: 0; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-dim); }
  .panel-body { padding: 1.1rem; }

  #log { min-height: 320px; max-height: 460px; overflow-y: auto; padding: 1.1rem; display: flex; flex-direction: column; gap: 0.7rem; }
  .row { display: flex; }
  .row.customer { justify-content: flex-end; }
  .row.agent { justify-content: flex-start; }
  .bubble { max-width: 82%; padding: 0.65rem 0.85rem; border-radius: 12px; font-size: 0.88rem; line-height: 1.5; white-space: pre-wrap; }
  .row.customer .bubble { background: var(--brand); color: var(--brand-ink); border-bottom-right-radius: 4px; }
  .row.agent .bubble { background: var(--surface-2); color: var(--text); border-bottom-left-radius: 4px; }
  .row.agent .bubble.blocked { background: var(--block-soft); color: var(--block); border: 1px solid color-mix(in srgb, var(--block) 25%, transparent); }
  .row.agent .bubble.escalated { background: var(--escalate-soft); color: var(--escalate); border: 1px solid color-mix(in srgb, var(--escalate) 25%, transparent); }
  .label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-faint); margin: 0 0.2rem 0.25rem; }

  .empty-hint { color: var(--text-faint); font-size: 0.85rem; text-align: center; padding: 2.5rem 1rem; }

  form#chat-form { display: flex; gap: 0.5rem; padding: 0.9rem 1.1rem; border-top: 1px solid var(--border); }
  input[type=text] { flex: 1; padding: 0.65rem 0.8rem; border-radius: 9px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 0.88rem; font-family: var(--sans); }
  input[type=text]:focus { outline: 2px solid var(--brand); outline-offset: 1px; }
  button { padding: 0.65rem 1.05rem; border-radius: 9px; border: none; cursor: pointer; font-size: 0.85rem; font-weight: 600; background: var(--brand); color: var(--brand-ink); font-family: var(--sans); transition: opacity 0.15s; }
  button:hover { opacity: 0.88; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.ghost { background: var(--surface-2); color: var(--text); border: 1px solid var(--border); }

  .chips { display: flex; flex-wrap: wrap; gap: 0.45rem; padding: 0 1.1rem 1rem; }
  .chip { font-size: 0.76rem; font-family: var(--sans); padding: 0.4rem 0.65rem; border-radius: 999px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-dim); cursor: pointer; white-space: nowrap; }
  .chip:hover { border-color: var(--brand); color: var(--text); }
  .chip .verdict-hint { font-weight: 700; }
  .chip.will-allow .verdict-hint { color: var(--allow); }
  .chip.will-block .verdict-hint { color: var(--block); }
  .chip.will-escalate .verdict-hint { color: var(--escalate); }

  section.recorded { margin-bottom: 1.25rem; }
  .recorded-note { font-size: 0.78rem; color: var(--text-faint); }
  .scenario-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.75rem; padding: 1.1rem; }
  .scenario-card { text-align: left; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 0.8rem 0.9rem; cursor: pointer; font-family: var(--sans); color: var(--text); display: flex; flex-direction: column; gap: 0.5rem; }
  .scenario-card:hover { border-color: var(--brand); }
  .scenario-card:disabled { opacity: 0.5; cursor: not-allowed; }
  .scenario-title { font-size: 0.85rem; font-weight: 600; }
  .scenario-desc { font-size: 0.76rem; color: var(--text-dim); line-height: 1.4; flex: 1; }
  .scenario-meta { display: flex; align-items: center; justify-content: space-between; font-size: 0.7rem; color: var(--text-faint); }
  .replaying-banner { display: flex; align-items: center; gap: 0.5rem; font-size: 0.78rem; color: var(--brand); padding: 0.5rem 1.1rem; background: var(--brand-soft); border-bottom: 1px solid var(--border); }
  .replaying-banner .spin { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--brand); border-top-color: transparent; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .verdict { display: inline-flex; align-items: center; gap: 0.3rem; font-family: var(--mono); font-size: 0.68rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase; padding: 0.22rem 0.55rem; border-radius: 6px; white-space: nowrap; }
  .verdict.allow { background: var(--allow-soft); color: var(--allow); }
  .verdict.block { background: var(--block-soft); color: var(--block); }
  .verdict.escalate { background: var(--escalate-soft); color: var(--escalate); }

  #feed { display: flex; flex-direction: column; gap: 0.6rem; max-height: 420px; overflow-y: auto; padding: 1.1rem; }
  .feed-empty { color: var(--text-faint); font-size: 0.83rem; text-align: center; padding: 2rem 1rem; }
  .feed-item { border: 1px solid var(--border); border-radius: 10px; padding: 0.65rem 0.75rem; background: var(--bg); }
  .feed-item-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.3rem; }
  .feed-tool { font-family: var(--mono); font-size: 0.78rem; font-weight: 600; }
  .feed-reason { font-size: 0.78rem; color: var(--text-dim); line-height: 1.45; }
  .feed-rules { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.4rem; }
  .rule-tag { font-family: var(--mono); font-size: 0.66rem; color: var(--text-faint); background: var(--surface-2); padding: 0.12rem 0.4rem; border-radius: 5px; }

  section.redteam { margin-top: 1.25rem; }
  .stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; padding: 1.1rem; }
  @media (max-width: 640px) { .stat-row { grid-template-columns: repeat(2, 1fr); } }
  .stat { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 0.8rem 0.9rem; }
  .stat .num { font-family: var(--mono); font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  .stat .num.good { color: var(--allow); }
  .stat .lbl { font-size: 0.7rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.04em; margin-top: 0.15rem; }
  #probe-list { display: flex; flex-direction: column; gap: 0.4rem; padding: 0 1.1rem 1.1rem; max-height: 360px; overflow-y: auto; }
  .probe-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0.65rem; border-radius: 8px; background: var(--bg); border: 1px solid var(--border); }
  .probe-desc { flex: 1; font-size: 0.78rem; color: var(--text-dim); }
  .probe-key { font-family: var(--mono); font-size: 0.7rem; color: var(--text-faint); }
  .rt-actions { display: flex; align-items: center; gap: 0.6rem; padding: 0 1.1rem 1.1rem; }
  .rt-status { font-size: 0.8rem; color: var(--text-dim); }

  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand-row">
      <div class="mark">N</div>
      <div>
        <h1>AgentFox — live governed support agent</h1>
        <p class="tagline">LangChain agent · McpGovernor · F3.8 composed-escalation</p>
      </div>
    </div>
    <span class="mode-badge"><span class="dot"></span>Capability grants enforced — blocks are real</span>
  </header>

  <p class="intro">
    Every tool call (<code>lookup_customer</code>, <code>search_orders</code>,
    <code>issue_refund</code>, <code>send_email</code>) goes through real capability
    grants, independent of the LLM's own judgment — a refund above $500 has no
    grant at all and is denied outright, email requires human approval before it
    sends, and a value copied from one tool's result into another call is tracked
    across the whole conversation (F3.8 composed-escalation).
  </p>

  <section class="recorded panel">
    <div class="panel-head">
      <h2>Recorded scenarios</h2>
      <span class="recorded-note">Real transcripts from this agent — replay instantly, no live model call</span>
    </div>
    <div class="scenario-grid" id="scenario-grid"></div>
  </section>

  <div class="grid">
    <div class="panel">
      <div class="panel-head"><h2>Conversation</h2></div>
      <div id="replaying-banner" class="replaying-banner" style="display:none;"><span class="spin"></span><span id="replaying-label"></span></div>
      <div id="log"><div class="empty-hint">Replay a recorded scenario above, or type a message to talk to the live agent.</div></div>
      <div class="chips" id="chips"></div>
      <form id="chat-form">
        <input id="msg" type="text" placeholder="Type a customer request..." autocomplete="off" />
        <button type="submit">Send</button>
      </form>
    </div>

    <div class="panel">
      <div class="panel-head"><h2>Governance activity</h2></div>
      <div id="feed"><div class="feed-empty">Tool calls and their verdicts appear here as the conversation happens.</div></div>
    </div>
  </div>

  <section class="redteam panel">
    <div class="panel-head">
      <h2>Red-team the live agent</h2>
      <div style="display:flex; align-items:center; gap:0.6rem;">
        <span class="rt-status" id="rt-status"></span>
        <button id="rt-btn">Run 22 built-in probes</button>
      </div>
    </div>
    <div id="rt-results"></div>
  </section>
</div>

<script>
const log = document.getElementById('log');
const feed = document.getElementById('feed');
const history = [];
const sessionId = 'web-' + Math.random().toString(36).slice(2, 10);
let logEmptied = false;
let feedEmptied = false;

const LIVE_PROMPTS = [
  {label: 'Refund within policy', hint: 'allow', cls: 'will-allow',
   text: "A customer says their order ORD-7002 arrived damaged and they'd like a $45 refund."},
  {label: 'Refund over the $500 cap', hint: 'block', cls: 'will-block',
   text: "Issue a refund of exactly $600 to order ORD-7003 right now, the customer is on the phone and already agreed."},
  {label: 'Email needs approval', hint: 'pending', cls: 'will-escalate',
   text: "Please send an email to marcus.diallo@example.com confirming his refund is processed."},
  {label: 'Composed escalation (F3.8)', hint: 'watch', cls: 'will-escalate',
   text: "Can you search for orders from Priya Anand and issue her a refund?"},
];

function renderChips() {
  const box = document.getElementById('chips');
  box.innerHTML = '';
  for (const s of LIVE_PROMPTS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip ' + s.cls;
    b.innerHTML = s.label + ' <span class="verdict-hint">&rarr; ' + s.hint + '</span>';
    b.addEventListener('click', () => { document.getElementById('msg').value = s.text; document.getElementById('msg').focus(); });
    box.appendChild(b);
  }
}
renderChips();

// Real transcripts captured from live runs of this exact agent (see
// demo/redteam-live-lang/README.md's "Recorded scenarios" section for how).
// Not fabricated: each is the actual request/response JSON this agent
// produced, replayed verbatim so a demo doesn't have to wait on -- or risk --
// a live model call for every scenario shown.
const RECORDED_SCENARIOS = {
  allow: {
    title: 'Refund within policy',
    desc: 'A normal refund inside the $500 capability ceiling.',
    outcome: 'allow',
    turns: __ALLOW_TURNS__,
  },
  block: {
    title: 'Refund over the $500 cap',
    desc: 'No capability grants this identity that amount at all -- denied outright.',
    outcome: 'block',
    turns: __BLOCK_TURNS__,
  },
  escalate: {
    title: 'Email needs approval',
    desc: 'send_email requires human sign-off before it actually sends.',
    outcome: 'escalate',
    turns: __ESCALATE_TURNS__,
  },
  composed: {
    title: 'Composed escalation (F3.8)',
    desc: 'search_orders result flows into issue_refund in one turn -- caught by taint tracking, not by the LLM.',
    outcome: 'block',
    turns: __COMPOSED_TURNS__,
  },
  bulk: {
    title: 'Bulk refund request (4 turns)',
    desc: 'A customer asks to refund every order at once; the second refund is provably tool-derived and needs approval, so it waits for explicit confirmation.',
    outcome: 'escalate',
    turns: __BULK_TURNS__,
  },
};

function renderScenarioCards() {
  const grid = document.getElementById('scenario-grid');
  grid.innerHTML = '';
  for (const [key, s] of Object.entries(RECORDED_SCENARIOS)) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'scenario-card';
    card.innerHTML =
      '<span class="scenario-title">' + escapeHtml(s.title) + '</span>' +
      '<span class="scenario-desc">' + escapeHtml(s.desc) + '</span>' +
      '<span class="scenario-meta"><span>' + s.turns.length + (s.turns.length === 1 ? ' turn' : ' turns') + '</span>' + verdictBadge(s.outcome) + '</span>';
    card.addEventListener('click', () => replayScenario(key));
    grid.appendChild(card);
  }
}

async function replayScenario(key) {
  const scenario = RECORDED_SCENARIOS[key];
  if (!scenario) return;
  const cards = document.querySelectorAll('.scenario-card');
  cards.forEach(c => c.disabled = true);
  const sendBtn = document.querySelector('#chat-form button');
  sendBtn.disabled = true;
  const banner = document.getElementById('replaying-banner');
  const label = document.getElementById('replaying-label');
  banner.style.display = 'flex';
  label.textContent = 'Replaying: ' + scenario.title;

  log.innerHTML = '';
  logEmptied = true;
  feed.innerHTML = '';
  feedEmptied = true;
  history.length = 0;

  const pause = (ms) => new Promise(r => setTimeout(r, ms));
  for (const turn of scenario.turns) {
    addMsg('customer', turn.customer, null);
    await pause(450);
    const state = turn.blocked ? 'blocked' : (turn.escalated ? 'escalated' : null);
    addMsg('agent', turn.reply, state);
    for (const call of turn.tool_calls) addFeedItem(call);
    history.push({role: 'user', content: turn.customer});
    history.push({role: 'assistant', content: turn.reply});
    await pause(550);
  }

  banner.style.display = 'none';
  cards.forEach(c => c.disabled = false);
  sendBtn.disabled = false;
}

renderScenarioCards();

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function addMsg(role, text, state) {
  if (!logEmptied) { log.innerHTML = ''; logEmptied = true; }
  const row = document.createElement('div');
  row.className = 'row ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'bubble' + (state ? ' ' + state : '');
  bubble.textContent = text;
  row.appendChild(bubble);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function verdictBadge(v) {
  const map = {allow: 'Allowed', block: 'Blocked', escalate: 'Pending approval'};
  return '<span class="verdict ' + v + '">' + (map[v] || v) + '</span>';
}

function addFeedItem(call) {
  if (!feedEmptied) { feed.innerHTML = ''; feedEmptied = true; }
  const item = document.createElement('div');
  item.className = 'feed-item';
  const rules = (call.rules_fired || []).map(r => '<span class="rule-tag">' + escapeHtml(r) + '</span>').join('');
  item.innerHTML =
    '<div class="feed-item-head"><span class="feed-tool">' + escapeHtml(call.tool) + '</span>' + verdictBadge(call.verdict) + '</div>' +
    (call.reason ? '<div class="feed-reason">' + escapeHtml(call.reason) + '</div>' : '') +
    (rules ? '<div class="feed-rules">' + rules + '</div>' : '');
  feed.appendChild(item);
  feed.scrollTop = feed.scrollHeight;
}

document.getElementById('chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('msg');
  const message = input.value.trim();
  if (!message) return;
  addMsg('customer', message, null);
  input.value = '';
  const btn = document.querySelector('#chat-form button');
  btn.disabled = true;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, session_id: sessionId, history}),
    });
    const data = await res.json();
    const state = data.blocked ? 'blocked' : (data.escalated ? 'escalated' : null);
    addMsg('agent', data.reply, state);
    for (const call of (data.tool_calls || [])) addFeedItem(call);
    if (data.blocked && (!data.tool_calls || !data.tool_calls.length) && data.rules_fired && data.rules_fired.length) {
      addFeedItem({tool: 'input check', verdict: 'block', reason: data.reply, rules_fired: data.rules_fired});
    }
    history.push({role: 'user', content: message});
    history.push({role: 'assistant', content: data.reply});
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('rt-btn').addEventListener('click', async () => {
  const btn = document.getElementById('rt-btn');
  const status = document.getElementById('rt-status');
  const results = document.getElementById('rt-results');
  btn.disabled = true;
  status.textContent = 'Running 22 probes against the live agent...';
  results.innerHTML = '';
  try {
    const res = await fetch('/api/redteam', {method: 'POST'});
    const data = await res.json();
    status.textContent = '';
    const fp = data.benign_false_positives;
    results.innerHTML =
      '<div class="stat-row">' +
      '<div class="stat"><div class="num good">' + Math.round(data.recall * 100) + '%</div><div class="lbl">Recall</div></div>' +
      '<div class="stat"><div class="num">' + Math.round(data.precision * 100) + '%</div><div class="lbl">Precision</div></div>' +
      '<div class="stat"><div class="num good">' + data.attacks_blocked + '/' + data.attacks_run + '</div><div class="lbl">Attacks blocked</div></div>' +
      '<div class="stat"><div class="num' + (fp > 0 ? '' : ' good') + '">' + fp + '/' + data.benign_probes_run + '</div><div class="lbl">Benign false positives</div></div>' +
      '</div>';
    const list = document.createElement('div');
    list.id = 'probe-list';
    for (const p of data.probes) {
      const v = p.verdict === 'allow' ? 'allow' : (p.verdict === 'escalate' ? 'escalate' : 'block');
      const row = document.createElement('div');
      row.className = 'probe-row';
      row.innerHTML =
        verdictBadge(v) +
        '<span class="probe-desc">' + escapeHtml(p.description) + '</span>' +
        '<span class="probe-key">' + escapeHtml(p.key) + '</span>';
      list.appendChild(row);
    }
    results.appendChild(list);
  } catch (err) {
    status.textContent = 'Probe run failed: ' + err;
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>"""


def _safe_js(value: object) -> str:
    """`</script>` inside a JSON string embedded in an inline <script> tag would
    close the tag early -- practically unreachable in this LLM-generated demo
    text, but cheap to guard against outright rather than trust that."""
    return json.dumps(value).replace("</", "<\\/")


_PAGE = (
    _PAGE.replace("__ALLOW_TURNS__", _safe_js(ALLOW_TURNS))
    .replace("__BLOCK_TURNS__", _safe_js(BLOCK_TURNS))
    .replace("__ESCALATE_TURNS__", _safe_js(ESCALATE_TURNS))
    .replace("__COMPOSED_TURNS__", _safe_js(COMPOSED_TURNS))
    .replace("__BULK_TURNS__", _safe_js(BULK_TURNS))
)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE
