from __future__ import annotations

from typing import Any

FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "correctness",
                            "security",
                            "architecture",
                            "reliability",
                            "performance",
                            "testing",
                        ],
                    },
                    "file_path": {"type": "string"},
                    "line_start": {"type": ["integer", "null"]},
                    "line_end": {"type": ["integer", "null"]},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "confidence": {"type": "number"},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "evidence": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
                "required": [
                    "category",
                    "file_path",
                    "severity",
                    "confidence",
                    "title",
                    "explanation",
                    "evidence",
                    "recommendation",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["APPROVE", "COMMENT", "REQUEST_CHANGES"],
        },
        "risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "summary": {"type": "string"},
    },
    "required": ["decision", "risk", "summary"],
    "additionalProperties": False,
}

PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "replacement": {"type": "string"},
        "line_start": {"type": "integer"},
        "line_end": {"type": "integer"},
    },
    "required": ["replacement", "line_start", "line_end"],
    "additionalProperties": False,
}
