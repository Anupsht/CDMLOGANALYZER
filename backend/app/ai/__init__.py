"""Phase 8 — AI explanation layer.

Architecture (``docs/ai-explanations.md``):

    deterministic analysis (Phases 2–5)  →  structured digest  →  provider
    (deterministic composer, or an external OpenAI-compatible LLM when
    ``CDM_AI_BASE_URL`` is configured)  →  safety validation  →  stored,
    evidence-referenced explanation.

The AI never replaces the rules engine: it only *explains* the already
computed picture, under a strict safety contract (see :mod:`app.ai.safety`).
"""
