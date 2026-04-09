"""
FastAPI application with ADK Runner integration.
Serves both the API and the dashboard static files.
"""

import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agents.manager_agent import manager_agent
from app.api.routes import router as api_router


load_dotenv()

# ── ADK Runner ──────────────────────────────────────────────────────

runner = InMemoryRunner(agent=manager_agent, app_name="household_manager")

# Track sessions per user-role
_sessions: dict[str, str] = {}

# Simple in-memory chat history per user
_chat_history: dict[str, list] = {}


async def get_or_create_session(user_id: str) -> str:
    """Get existing session ID or create a new one for the user."""
    if user_id not in _sessions:
        session = await runner.session_service.create_session(
            app_name="household_manager",
            user_id=user_id,
        )
        _sessions[user_id] = session.id
    return _sessions[user_id]


# ── FastAPI App ─────────────────────────────────────────────────────

app = FastAPI(title="AI Household Staff Manager", version="0.1.0")
app.include_router(api_router)


# ── Chat endpoint ──────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(request: Request):
    """Send a message to the ADK agent and return the response."""
    body = await request.json()
    user_message = body.get("message", "")
    user_id = body.get("user_id", "manager")

    session_id = await get_or_create_session(user_id)

    # Initialize history for this user if needed
    if user_id not in _chat_history:
        _chat_history[user_id] = []

    # Store user message
    _chat_history[user_id].append({
        "author": "You",
        "text": user_message,
        "role": "user",
    })

    # Collect all response parts
    response_parts = []

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=user_message)],
            ),
        ):
            if not event.content or not event.content.parts:
                continue

            for part in event.content.parts:
                if part.function_call or part.function_response:
                    continue
                if part.text and part.text.strip():
                    response_parts.append({
                        "author": event.author,
                        "text": part.text.strip(),
                    })
    except Exception as e:
        import traceback
        traceback.print_exc()
        response_parts.append({
            "author": "system",
            "text": f"Error processing request: {str(e)}",
        })

    # Store agent responses in history
    for resp in response_parts:
        _chat_history[user_id].append({
            "author": resp["author"],
            "text": resp["text"],
            "role": "model",
        })

    return JSONResponse({"responses": response_parts})


@app.get("/api/chat/history")
async def chat_history(user_id: str = "manager"):
    """Fetch the chat history for a given user."""
    history = _chat_history.get(user_id, [])
    return JSONResponse({"history": history})


# ── Serve dashboard static files ───────────────────────────────────

dashboard_dir = Path(__file__).parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")


# ── HTML page routes ────────────────────────────────────────────────

def _serve_html(filename: str):
    filepath = dashboard_dir / filename
    if filepath.exists():
        return HTMLResponse(filepath.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Page not found</h1>", status_code=404)


@app.get("/", response_class=HTMLResponse)
def overview_page():
    return _serve_html("index.html")


@app.get("/manager", response_class=HTMLResponse)
def manager_page():
    return _serve_html("manager.html")


@app.get("/secretary", response_class=HTMLResponse)
def secretary_page():
    return _serve_html("secretary.html")


@app.get("/worker/{worker_id}", response_class=HTMLResponse)
def worker_page(worker_id: str):
    return _serve_html("worker.html")
