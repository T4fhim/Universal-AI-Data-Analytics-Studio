# File: src/core/expertise_level.py
"""The user's self-declared analytical expertise, shared across the AI and UI layers.

Milestone 8's "Progressive Expertise" feature needs one shared vocabulary
for "how should this be explained" that both the AI system prompt
(:mod:`src.ai.assistant_service`) and result-rendering UI panels
(milestone 10) read — defining it once here, as a small shared type
rather than a service, avoids the AI and UI layers drifting toward two
different notions of what "beginner" versus "engineer" means.

A plain :class:`~enum.Enum`, not a service: this module has no
behavior, no state, and nothing to register in
:mod:`src.core.bootstrap`'s dependency container — it belongs next to
:mod:`src.core.exceptions` as a small shared vocabulary type, matching
how that module is also core-but-not-a-service.
"""

from __future__ import annotations

from enum import Enum


class ExpertiseLevel(str, Enum):
    """How much statistical/technical background the user has told the app they have.

    Subclasses ``str`` so a member compares equal to and serializes as
    its plain string value (``ExpertiseLevel.BEGINNER == "beginner"``)
    — this is what lets ``ai.expertise_level`` in ``config.yaml`` store
    a plain string while code elsewhere works with the enum, with no
    manual ``.value``/round-trip conversion needed at the config
    boundary the way a plain ``Enum`` would require.
    """

    BEGINNER = "beginner"
    STUDENT = "student"
    ANALYST = "analyst"
    RESEARCHER = "researcher"
    ENGINEER = "engineer"
    DECISION_MAKER = "decision_maker"


# One short phrase per level, meant to be interpolated directly into
# the AI system prompt (see assistant_service._SYSTEM_PROMPT) to steer
# register/depth — not a full style guide, since the model is capable
# of filling in "explain like I'm a beginner" from a short, clear
# instruction without needing paragraphs of guidance per level.
EXPERTISE_LEVEL_GUIDANCE: dict[ExpertiseLevel, str] = {
    ExpertiseLevel.BEGINNER: (
        "Explain findings in plain language with minimal jargon. Define any "
        "statistical term you must use in one clause the first time it "
        "appears. Favor what a result means in practice over how it was "
        "computed."
    ),
    ExpertiseLevel.STUDENT: (
        "Explain findings clearly, including the reasoning behind them — "
        "this user is learning and benefits from seeing how a conclusion "
        "was reached, not just the conclusion itself. Define statistical "
        "terms briefly when first used."
    ),
    ExpertiseLevel.ANALYST: (
        "Use standard analytical/statistical vocabulary without defining "
        "basic terms. Be direct about findings, methods used, and any "
        "caveats worth flagging for someone who works with data regularly."
    ),
    ExpertiseLevel.RESEARCHER: (
        "Use precise statistical terminology. Be explicit about method, "
        "assumptions, and confidence/uncertainty — this user will want to "
        "evaluate the methodology itself, not just trust the conclusion."
    ),
    ExpertiseLevel.ENGINEER: (
        "Be technically precise and concise. Reference implementation "
        "details (which function/method computed a result) when relevant. "
        "Skip explanatory scaffolding this user does not need."
    ),
    ExpertiseLevel.DECISION_MAKER: (
        "Lead with the business-relevant conclusion and recommended action. "
        "Keep methodology brief and in service of the decision, not the "
        "main content — this user needs to act on the finding, not audit "
        "how it was computed."
    ),
}
