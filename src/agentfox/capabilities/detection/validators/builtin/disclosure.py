"""Validators: disclosure. See `validators/builtin/__init__.py`.

An agent repeating its own instructions back: the system prompt, or a canary
token planted in it.
"""

from __future__ import annotations

import difflib
import re

from pydantic import BaseModel, ConfigDict, Field

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)

_WORD = re.compile(r"\w+(?:['’]\w+)*")
SHINGLE = 5


def _words(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Lower-cased words and their spans in the text."""
    words: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _WORD.finditer(text):
        words.append(m.group().lower().replace("’", "'"))
        spans.append(m.span())
    return words, spans


class SystemPromptLeakParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str = Field(min_length=1, max_length=200_000)
    #: Strings planted in the prompt that should never appear in an output.
    canaries: list[str] = Field(default_factory=list, max_length=100)
    #: Share (0-1) of the prompt's word 5-grams found in the output that counts as a leak.
    threshold: float = Field(0.4, gt=0, le=1)
    #: Consecutive prompt words, repeated in order, that count as a leak.
    min_overlap_words: int = Field(8, ge=3, le=1000)


@register_validator
class SystemPromptLeak(Validator):
    """Adapted from guardrails-ai/detect_system_prompt_leakage (Apache-2.0).

    Upstream compared the whole output with the whole prompt (`rapidfuzz.fuzz.ratio`),
    so a long answer quoting the prompt scored low and a short answer that merely
    resembled it scored high. This looks for the prompt's own words in the output:
    verbatim canaries, long runs of consecutive prompt words, and the share of the
    prompt's word 5-grams that reappear.
    """

    name = "system_prompt_leak"
    label = "System prompt leak"
    description = (
        "Flags an output that repeats the system prompt: a planted canary, a long run of "
        "its words in order, or a large share of its phrases."
    )
    entity_type = "DISCLOSURE.SYSTEM_PROMPT"
    surfaces = ("output", "agent_message")
    Params = SystemPromptLeakParams
    upstream = "guardrails-ai/detect_system_prompt_leakage"
    owasp_id = "LLM07"

    def check(self, text: str, params: SystemPromptLeakParams, ctx: CheckContext) -> list[Finding]:
        out: list[Finding] = []
        for canary in params.canaries:
            if not canary:
                continue
            start = text.find(canary)
            while start >= 0:
                end = start + len(canary)
                out.append(
                    span_finding(text, start, end, "canary from the system prompt in output")
                )
                start = text.find(canary, end)

        prompt_words, _ = _words(params.system_prompt)
        out_words, out_spans = _words(text)
        if not prompt_words or not out_words:
            return out

        # Share of the prompt's shingles that reappear (n shrinks for a short prompt).
        n = min(SHINGLE, len(prompt_words))
        prompt_shingles = {tuple(prompt_words[i : i + n]) for i in range(len(prompt_words) - n + 1)}
        hit_positions = [
            i
            for i in range(len(out_words) - n + 1)
            if tuple(out_words[i : i + n]) in prompt_shingles
        ]
        found = {tuple(out_words[i : i + n]) for i in hit_positions}
        share = len(found) / len(prompt_shingles)

        # Runs of consecutive prompt words, in order.
        matcher = difflib.SequenceMatcher(None, prompt_words, out_words, autojunk=False)
        runs = [b for b in matcher.get_matching_blocks() if b.size >= params.min_overlap_words]
        for block in runs:
            start = out_spans[block.b][0]
            end = out_spans[block.b + block.size - 1][1]
            out.append(
                span_finding(
                    text,
                    start,
                    end,
                    f"{block.size} consecutive words of the system prompt in output",
                    words=block.size,
                    share=round(share, 3),
                )
            )

        if share >= params.threshold and not runs and hit_positions:
            start = out_spans[hit_positions[0]][0]
            end = out_spans[hit_positions[-1] + n - 1][1]
            out.append(
                span_finding(
                    text,
                    start,
                    end,
                    f"{round(100 * share)}% of the system prompt's phrases in output",
                    share=round(share, 3),
                )
            )
        out.sort(key=lambda f: f.start)
        return out
