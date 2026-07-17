from __future__ import annotations

import time

from app.db import execute, query_all
from app.utils import esc


def add_chat_exchange(user_id: int, question: str, answer: str) -> None:
    created_at = int(time.time())
    execute(
        """
        INSERT INTO ai_chat_messages (user_id, role, content, created_at)
        VALUES (?, 'user', ?, ?)
        """,
        (user_id, question, created_at),
    )
    execute(
        """
        INSERT INTO ai_chat_messages (user_id, role, content, created_at)
        VALUES (?, 'assistant', ?, ?)
        """,
        (user_id, answer, created_at),
    )


def render_chat_history(user_id: int, limit: int = 30) -> str:
    messages = query_all(
        """
        SELECT * FROM (
            SELECT * FROM ai_chat_messages
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        ) AS recent_messages
        ORDER BY created_at, id
        """,
        (user_id, limit),
    )
    if not messages:
        content = '<p class="chat-history-empty">No conversation yet. Send a message to start.</p>'
    else:
        content = "".join(
            f'<div class="chat-message {"user-message" if message["role"] == "user" else "ai-message"}">{esc(message["content"])}</div>'
            for message in messages
        )

    return f"""
    <section class="chat-history" aria-label="Chat history">
        <h3>Chat history</h3>
        <div class="chat-window">{content}</div>
    </section>
    """
