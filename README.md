# AgentCurious

**Live demo:** [agentcurious-frontend.onrender.com](https://agentcurious-frontend.onrender.com/)

A research agent that uses an LLM to actually do research — searching Wikipedia and the web, reasoning over the results, and streaming its thinking live to the user.

You ask a question. The agent plans, searches, reflects, and answers — and you watch every step happen in real time.

> Note: the backend is hosted on Render's free tier and spins down after ~15 min of inactivity. The first request after that may take 30–60 seconds to wake up.

---

## Features

- **Multi-tool agent loop** — the model decides what to search, parses results, and reflects on whether it has enough info before answering
- **Three search modes** — `Auto` (agent picks the source), `Wikipedia only`, or `Web only` (DuckDuckGo)
- **Live streaming** — every token of reasoning, every search call, and the final answer arrive over Server-Sent Events
- **Resilient** — gracefully handles Wikipedia API flakiness, rate limits, and malformed inputs
- **Zero build step** — frontend is a single HTML file with no `node_modules`, no bundler, no framework
- **One-command dev** — `./run_local.sh` boots the whole stack

---

## Tech stack

| Layer | Choice |
|-------|--------|
| LLM provider | [Groq](https://groq.com) — Llama 3.3 70B Versatile |
| Backend | FastAPI + Uvicorn |
| Search tools | Wikipedia (`wikipedia` package) + DuckDuckGo (`duckduckgo-search`) |
| Streaming | Server-Sent Events |
| Frontend | Vanilla HTML / CSS / JS (no frameworks) |

---

## How the agent works

The backend runs an agent loop that alternates between LLM calls and tool calls.

```
            ┌──────────────┐
            │  user query  │
            └──────┬───────┘
                   ▼
         ┌─────────────────────┐
         │  LLM plans + thinks │  <─── streams "thinking" events
         └─────────┬───────────┘
                   │
         did it write a search tag?
        ┌──────────┴──────────┐
       yes                    no
        │                     │
        ▼                     ▼
 ┌─────────────┐      did it write
 │  run tool   │      <information>?
 │ (wiki/web)  │      ┌────────────┐
 └──────┬──────┘     yes           no
        │            │             │
   feed results      ▼             ▼
   back to LLM   generate     keep looping
        │         answer       (max 8 rounds)
        └────► loop        (then force wrap-up)
```

The model is taught two tags:

- `<search_wiki>keywords</search_wiki>` — Wikipedia search
- `<search_web>keywords</search_web>` — DuckDuckGo search

When it writes `<information>...</information>`, the loop ends and the final answer is streamed.

In **Auto mode** the model has access to both tools. In **Wiki** or **Web** mode the system prompt only mentions one tool, forcing the source.

---

## Project structure

```
agentcurious/
├── backend/
│   ├── main.py            # FastAPI app, agent loop, search tools
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html         # entire frontend in one file
├── run_local.sh           # boots backend + frontend
├── render.yaml            # deploy config (Render)
└── .gitignore
```

---

## Running locally

### Prerequisites

- Python 3.10+
- A free [Groq API key](https://console.groq.com)

### Setup

From the project root:

```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
# Open .env and paste your Groq key:
# GROQ_API_KEY=gsk_...
```

### Start the app

```bash
./run_local.sh
```

- Backend: <http://localhost:8000>
- Frontend: <http://localhost:3000>

`Ctrl+C` stops both servers.

### Try it

Open the frontend in your browser, pick a source mode, and ask something like:

- *"What caused World War I?"* → Auto mode picks Wikipedia
- *"What's the latest iPhone model?"* → Auto mode picks Web
- *"Who is Sam Altman and what is OpenAI working on right now?"* → Auto mode mixes both

Or hit the API directly:

```bash
curl -N -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What is photosynthesis?", "mode": "auto"}'
```

---

## API

### `GET /`

Health check. Returns `{"status": "ok"}`.

### `POST /ask`

Runs the agent and streams events.

**Request body:**

```json
{
  "query": "your question",
  "mode": "auto" | "wiki" | "web"
}
```

`mode` is optional and defaults to `auto`.

**Response:** `text/event-stream`

Each line is `data: <json>\n\n`. Event types:

| Type | Fields | Meaning |
|------|--------|---------|
| `thinking` | `content` | A token of the model's reasoning |
| `search` | `content`, `source` | The agent issued a search; `source` is `wiki` or `web` |
| `search_result` | `content`, `source` | Snippet returned from the tool |
| `answer` | `content` | A token of the final answer |
| `error` | `content` | An error occurred (rate limit, network, etc.) |

---

## Design notes

**Why Groq over Gemini.** Gemini's free tier returned `429 RESOURCE_EXHAUSTED` on every call. Groq's free tier is generous and produces tokens fast — perfect for a "watch it think" UX.

**Why vanilla JS over React.** One page, one form, one streaming view. No routing, no shared state, no component reuse. A single HTML file is faster to ship, easier to deploy as a static asset, and clearer to read for anyone reviewing the code.

**Why Wikipedia + DuckDuckGo.** Wikipedia is unmatched for established facts. DuckDuckGo covers recent events and niche topics where Wikipedia is stale or missing. Together they cover both ends of the freshness spectrum.

**Why XML-style tool calls instead of function calling.** Lighter prompt, no schema management, model-agnostic. The model just writes a tag and the backend parses it — same idea as Anthropic's original tool-use approach.

