"""Structured database queries — scaffold."""

from __future__ import annotations


async def query_structured_db(query_description: str) -> dict:
    return {
        "status": "unavailable",
        "message": "Structured database queries are not available yet.",
        "query_description": query_description,
    }
