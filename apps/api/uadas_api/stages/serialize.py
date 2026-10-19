# File: apps/api/uadas_api/stages/serialize.py
"""The Phase 1.5 result-section model, serialized: one typed JSON shape for every stage result.

Why this module and not ad-hoc dicts per operation: the core's renderers already turn any analysis
result into a short list of ``ResultSection`` values (key/value, table, figure, prose, metric,
assumptions) that the desktop's ``ResultCard`` displayed and the web client will render the same
way (Phase 4.8). The API therefore returns exactly that list, tagged with a ``type`` so the
client can switch on it, and the OpenAPI document types each variant (a discriminated union). A
renderer already formats numbers into display strings, so a section carries text, not floats.

``FigureSection.figure`` is a Plotly figure and is emitted as its own JSON (``figure.to_json()``),
the form ``Plotly.newPlot`` consumes.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from ninja import Schema
from pydantic import Field

from uadas_core.results.base_result_renderer import (
    AssumptionsSection,
    FigureSection,
    KeyValueSection,
    MetricSection,
    ProseSection,
    ResultSection,
    TableSection,
)

STAGE_NAMES = Literal[
    "upload",
    "understand",
    "clean",
    "explore",
    "analyze",
    "visualize",
    "predict",
    "explain",
    "report",
    "reproduce",
]  # pinned to PipelineStage by a test
EXPERTISE_NAMES = Literal[
    "beginner",
    "student",
    "analyst",
    "researcher",
    "engineer",
    "decision_maker",
]  # pinned to ExpertiseLevel by a test


class KeyValueItem(Schema):
    label: str
    value: str


class KeyValueOut(Schema):
    type: Literal["key_value"] = "key_value"
    title: str
    items: list[KeyValueItem]


class TableOut(Schema):
    type: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[list[str]]


class FigureOut(Schema):
    type: Literal["figure"] = "figure"
    title: str
    figure: dict[str, Any]


class ProseOut(Schema):
    type: Literal["prose"] = "prose"
    title: str
    text: str


class MetricOut(Schema):
    type: Literal["metric"] = "metric"
    title: str
    value: str
    caption: str = ""


class AssumptionsOut(Schema):
    type: Literal["assumptions"] = "assumptions"
    title: str
    assumptions: list[str]


SectionOut = Annotated[
    KeyValueOut | TableOut | FigureOut | ProseOut | MetricOut | AssumptionsOut,
    Field(discriminator="type"),
]


class StageResultOut(Schema):
    """What a finished stage run produced: its sections, and the derived dataset if it made one."""

    stage: STAGE_NAMES
    operation: str
    kind: Literal["dataset", "result", "figure"]
    title: str
    headline: str
    expertise_level: EXPERTISE_NAMES
    sections: list[SectionOut]
    dataset_id: str | None = None
    parent_dataset_id: str | None = None


def section_to_dict(section: ResultSection) -> dict[str, Any]:
    """One core section as its tagged JSON object."""
    if isinstance(section, KeyValueSection):
        return {
            "type": "key_value",
            "title": section.title,
            "items": [{"label": k, "value": v} for k, v in section.items],
        }
    if isinstance(section, TableSection):
        return {
            "type": "table",
            "title": section.title,
            "columns": list(section.columns),
            "rows": [list(row) for row in section.rows],
        }
    if isinstance(section, FigureSection):
        return {
            "type": "figure",
            "title": section.title,
            "figure": json.loads(section.figure.to_json()),
        }
    if isinstance(section, ProseSection):
        return {"type": "prose", "title": section.title, "text": section.text}
    if isinstance(section, MetricSection):
        return {
            "type": "metric",
            "title": section.title,
            "value": section.value,
            "caption": section.caption,
        }
    if isinstance(section, AssumptionsSection):
        return {
            "type": "assumptions",
            "title": section.title,
            "assumptions": list(section.assumptions),
        }
    raise TypeError(f"unknown result section type: {type(section).__name__}")


def sections_to_dicts(sections: list[ResultSection]) -> list[dict[str, Any]]:
    """Every section, serialized, in order."""
    return [section_to_dict(section) for section in sections]


def summary_lines(sections: list[dict[str, Any]]) -> list[str]:
    """``"label: value"`` lines of the textual sections (what a report shows; figures are skipped)."""
    lines: list[str] = []
    for section in sections:
        kind = section["type"]
        if kind == "key_value":
            lines.extend(f"{i['label']}: {i['value']}" for i in section["items"])
        elif kind == "metric":
            lines.append(f"{section['title']}: {section['value']}")
        elif kind == "prose":
            lines.append(f"{section['title']}: {section['text']}")
    return lines
