"""Newscast web dashboard — FastAPI.

Run with: uvicorn dashboard.app:app
"""

import json
import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Newscast Dashboard")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_URLS_FILE = os.path.join(BASE_DIR, "seen_urls.json")
MEMORY_FILE = os.path.join(BASE_DIR, "topic_memory.json")
COSTS_FILE = os.path.join(BASE_DIR, "costs.json")


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _render_html(
    episodes_count: int,
    seen_count: int,
    total_cost_sek: float,
    recent_episodes: list,
    recent_costs: list,
) -> str:
    episode_rows = ""
    for ep in recent_episodes:
        date_str = ep.get("date", "")[:10]
        ep_num = ep.get("episode", "?")
        headlines = ep.get("headlines", [])
        hl_html = "".join(f"<li>{h}</li>" for h in headlines)
        episode_rows += f"""
        <tr>
          <td>{date_str}</td>
          <td>Avsnitt {ep_num}</td>
          <td><ul class="headlines">{hl_html}</ul></td>
        </tr>"""

    cost_rows = ""
    for c in recent_costs:
        date_str = c.get("date", "")[:16].replace("T", " ")
        sek = c.get("sek", 0)
        usd = c.get("usd", 0)
        inp = c.get("claude_input", c.get("gpt4o_input", 0))
        out = c.get("claude_output", c.get("gpt4o_output", 0))
        cost_rows += f"""
        <tr>
          <td>{date_str}</td>
          <td>{sek:.2f} kr</td>
          <td>{usd:.4f} USD</td>
          <td>{inp:,}</td>
          <td>{out:,}</td>
        </tr>"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Newscast Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f1117;
      color: #e1e4e8;
      padding: 2rem;
      line-height: 1.5;
    }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.3rem; color: #ffffff; }}
    .subtitle {{ color: #8b949e; font-size: 0.9rem; margin-bottom: 2rem; }}
    .stats {{
      display: flex;
      gap: 1.5rem;
      margin-bottom: 2.5rem;
      flex-wrap: wrap;
    }}
    .stat-card {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 1.2rem 1.8rem;
      min-width: 160px;
    }}
    .stat-label {{ font-size: 0.8rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; }}
    .stat-value {{ font-size: 2rem; font-weight: 700; color: #58a6ff; margin-top: 0.3rem; }}
    h2 {{ font-size: 1.2rem; margin-bottom: 1rem; color: #c9d1d9; border-bottom: 1px solid #21262d; padding-bottom: 0.5rem; }}
    section {{ margin-bottom: 2.5rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th {{
      text-align: left;
      padding: 0.6rem 0.8rem;
      background: #161b22;
      color: #8b949e;
      font-weight: 600;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid #21262d;
    }}
    td {{
      padding: 0.7rem 0.8rem;
      border-bottom: 1px solid #21262d;
      vertical-align: top;
    }}
    tr:hover td {{ background: #161b22; }}
    ul.headlines {{
      padding-left: 1.2rem;
      margin: 0;
      color: #8b949e;
      font-size: 0.85rem;
    }}
    ul.headlines li {{ margin-bottom: 0.2rem; }}
    .tag {{
      display: inline-block;
      background: #1f6feb22;
      color: #58a6ff;
      border-radius: 4px;
      padding: 0.1rem 0.5rem;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .no-data {{ color: #8b949e; font-style: italic; padding: 1rem 0; }}
  </style>
</head>
<body>
  <h1>🎙 Newscast Dashboard</h1>
  <p class="subtitle">Uppdaterad {now}</p>

  <div class="stats">
    <div class="stat-card">
      <div class="stat-label">Genererade avsnitt</div>
      <div class="stat-value">{episodes_count}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Sedda artiklar</div>
      <div class="stat-value">{seen_count}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total kostnad</div>
      <div class="stat-value">{total_cost_sek:.2f} kr</div>
    </div>
  </div>

  <section>
    <h2>Senaste 20 avsnitten</h2>
    {"<p class='no-data'>Inga avsnitt genererade ännu.</p>" if not recent_episodes else f"""
    <table>
      <thead><tr><th>Datum</th><th>Avsnitt</th><th>Rubriker</th></tr></thead>
      <tbody>{episode_rows}</tbody>
    </table>"""}
  </section>

  <section>
    <h2>Senaste 10 körningarnas kostnader</h2>
    {"<p class='no-data'>Ingen kostnadsdata ännu.</p>" if not recent_costs else f"""
    <table>
      <thead>
        <tr>
          <th>Tidpunkt</th>
          <th>SEK</th>
          <th>USD</th>
          <th>Claude in</th>
          <th>Claude ut</th>
        </tr>
      </thead>
      <tbody>{cost_rows}</tbody>
    </table>"""}
  </section>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    memory = _load_json(MEMORY_FILE, [])
    seen = _load_json(SEEN_URLS_FILE, {})
    costs = _load_json(COSTS_FILE, [])

    episodes_count = len(memory)
    seen_count = len(seen)
    total_cost_sek = sum(c.get("sek", 0) for c in costs)

    # Sort memory by date desc, take 20
    recent_episodes = sorted(memory, key=lambda e: e.get("date", ""), reverse=True)[:20]
    # Sort costs by date desc, take 10
    recent_costs = sorted(costs, key=lambda c: c.get("date", ""), reverse=True)[:10]

    return _render_html(episodes_count, seen_count, total_cost_sek, recent_episodes, recent_costs)
