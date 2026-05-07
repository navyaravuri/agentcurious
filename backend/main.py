import re
import json
import asyncio
import wikipedia
from groq import Groq
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import os

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT_AUTO = (
    "You are a research assistant with access to two search tools:\n"
    "1. Wikipedia — best for established facts, history, biographies, science. Use <search_wiki>keywords</search_wiki>.\n"
    "2. Web (DuckDuckGo) — best for recent events, current people, news, niche topics. Use <search_web>keywords</search_web>.\n"
    "Use atomic short keyword queries (1-3 words). Pick the tool that fits the question best.\n"
    "After getting results, reflect in <search_quality>...</search_quality> tags on whether you have enough info. "
    "When you have all needed info, write it in <information>...</information> tags. "
    "Do not answer the question directly during research."
)

SYSTEM_PROMPT_WIKI = (
    "You are a research assistant with access to a Wikipedia search tool. "
    "To search, write <search_wiki>short keywords</search_wiki>. "
    "Use atomic short keyword queries (1-3 words). "
    "After getting results, reflect in <search_quality>...</search_quality> tags on whether you have enough info. "
    "When you have all needed info, write it in <information>...</information> tags. "
    "Do not answer the question directly during research."
)

SYSTEM_PROMPT_WEB = (
    "You are a research assistant with access to a DuckDuckGo web search tool. "
    "To search, write <search_web>short keywords</search_web>. "
    "Use atomic short keyword queries (1-3 words). "
    "After getting results, reflect in <search_quality>...</search_quality> tags on whether you have enough info. "
    "When you have all needed info, write it in <information>...</information> tags. "
    "Do not answer the question directly during research."
)

RESEARCH_PROMPT = (
    "Before researching, plan in <scratchpad>...</scratchpad> tags. "
    "Use short keyword queries. Question: {query}"
)

ANSWER_PROMPT = (
    "Question: {query}\n\n"
    "Research findings:\n{information}\n\n"
    "Answer the question clearly and concisely using the research findings."
)


def extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else None


wikipedia.set_user_agent("AgentCurious/1.0 (research agent; https://github.com)")


def wiki_search(query: str, n_results: int = 2) -> str:
    try:
        titles = wikipedia.search(query, results=n_results)
    except Exception:
        return ""
    results = []
    for title in titles:
        try:
            page = wikipedia.page(title, auto_suggest=False)
            results.append(
                f"Page Title: {page.title}\nPage Content:\n{page.content[:3000]}"
            )
        except Exception:
            continue
    return "\n---\n".join(results)


def web_search(query: str, n_results: int = 4) -> str:
    if DDGS is None:
        return ""
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=n_results))
    except Exception:
        return ""
    results = []
    for h in hits:
        title = h.get("title", "")
        body = h.get("body", "")
        url = h.get("href", "")
        results.append(f"Result: {title}\nURL: {url}\nSnippet: {body}")
    return "\n---\n".join(results)


def select_prompt(mode: str) -> str:
    if mode == "wiki":
        return SYSTEM_PROMPT_WIKI
    if mode == "web":
        return SYSTEM_PROMPT_WEB
    return SYSTEM_PROMPT_AUTO


async def run_agent(query: str, mode: str = "auto"):
    messages = [
        {"role": "system", "content": select_prompt(mode)},
        {"role": "user", "content": RESEARCH_PROMPT.format(query=query)},
    ]

    information = None

    for _ in range(8):
        full_response = ""
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL,
                messages=messages,
                stream=True,
                max_tokens=1024,
            )
            for chunk in response:
                text = chunk.choices[0].delta.content or ""
                if text:
                    full_response += text
                    yield {"type": "thinking", "content": text}
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return

        messages.append({"role": "assistant", "content": full_response})

        # Check both tool tags; whichever appears first wins.
        wiki_q = extract_tag(full_response, "search_wiki")
        web_q  = extract_tag(full_response, "search_web")

        if wiki_q and web_q:
            # Pick whichever the model wrote first
            wiki_pos = full_response.find("<search_wiki>")
            web_pos  = full_response.find("<search_web>")
            if web_pos != -1 and (wiki_pos == -1 or web_pos < wiki_pos):
                wiki_q = None
            else:
                web_q = None

        if wiki_q:
            yield {"type": "search", "source": "wiki", "content": wiki_q}
            try:
                results = await asyncio.to_thread(wiki_search, wiki_q)
            except Exception:
                results = ""
            yield {"type": "search_result", "source": "wiki", "content": results[:300]}
            messages.append({"role": "user", "content": f"Wikipedia results:\n{results}"})
            continue

        if web_q:
            yield {"type": "search", "source": "web", "content": web_q}
            try:
                results = await asyncio.to_thread(web_search, web_q)
            except Exception:
                results = ""
            yield {"type": "search_result", "source": "web", "content": results[:300]}
            messages.append({"role": "user", "content": f"Web results:\n{results}"})
            continue

        information = extract_tag(full_response, "information")
        if information:
            break

    if not information:
        messages.append({
            "role": "user",
            "content": "You have reached the search limit. Please write everything you have found so far inside <information>...</information> tags now.",
        })
        try:
            wrap_up = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL,
                messages=messages,
                stream=False,
                max_tokens=1024,
            )
            wrap_text = wrap_up.choices[0].message.content or ""
            information = extract_tag(wrap_text, "information") or wrap_text
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return

    answer_messages = [
        {"role": "user", "content": ANSWER_PROMPT.format(query=query, information=information)},
    ]

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=MODEL,
            messages=answer_messages,
            stream=True,
            max_tokens=1024,
        )
        for chunk in response:
            text = chunk.choices[0].delta.content or ""
            if text:
                yield {"type": "answer", "content": text}
    except Exception as e:
        yield {"type": "error", "content": str(e)}


class AskRequest(BaseModel):
    query: str
    mode: str = "auto"


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/ask")
async def ask(request: AskRequest):
    async def event_stream():
        async for event in run_agent(request.query, request.mode):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
