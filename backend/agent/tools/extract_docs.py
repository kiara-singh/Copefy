"""Unstructured document extraction — scaffold."""

from __future__ import annotations


async def extract_unstructured(file_reference: str) -> dict:
    return {
        "status": "unavailable",
        "message": "Document extraction is not available yet.",
        "file_reference": file_reference,
    }
