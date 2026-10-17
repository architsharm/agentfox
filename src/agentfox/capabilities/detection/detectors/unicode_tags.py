"""Text hidden in Unicode tag characters (issue #15).

The tag block, U+E0000 to U+E007F, mirrors ASCII: U+E0041 is an invisible "A". A
string of them renders as nothing in a browser, an editor or a terminal, but a model
reads the letters. That makes it a way to put an instruction in front of a model that
no human reviewer can see ("ASCII smuggling"): in a web page an agent retrieves, a
tool description, a document, or a pasted prompt.

The block has one legitimate use, and it is narrow: the subdivision flags. 🏴 (U+1F3F4)
followed by the tags for a region code and a cancel tag (U+E007F) is the flag of
England, Scotland or Wales. Those sequences are skipped. Every other run of tag
characters fires. The detection's sample is the decoded text, redacted like every
other stored sample (its first characters and its length), since what is hidden may
itself be a secret on its way out.

`injection.heuristic` already flags zero-width and bidi characters; it does not cover
this block, and decoding a hidden payload is a different job from noticing that
something is hidden.
"""

from __future__ import annotations

import re

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    snippet,
)

OWASP = "LLM01"
ATLAS = "AML.T0051"

_TAGS = re.compile("[\U000e0000-\U000e007f]+")
#: 🏴, a region code spelt in tag letters and digits, then CANCEL TAG: a subdivision flag.
_FLAG = re.compile("\U0001f3f4[\U000e0030-\U000e0039\U000e0061-\U000e007a]{2,6}\U000e007f")
_FIRST_TAG = "\U000e0000"

#: Decoded hidden text at least this long is read as a message, not a stray character.
MESSAGE_LENGTH = 4


def decode(tags: str) -> str:
    """The ASCII a run of tag characters spells; tags with no ASCII twin are dropped."""
    return "".join(chr(ord(c) - 0xE0000) for c in tags if 0xE0020 <= ord(c) <= 0xE007E)


class UnicodeTagsDetector(BaseDetector):
    covers_threats = ("LLM01", "AML.T0051")
    key = "unicode.tags"
    version = "1.0"
    surfaces = (
        "input",
        "output",
        "tool_args",
        "tool_result",
        "retrieved",
        "memory_write",
        "agent_message",
        "completion",
        "reasoning",
    )

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        # Almost all text has no character this high: one scan for the block start.
        if not content or max(content) < _FIRST_TAG:
            return []
        # Blank out the flags, same length so offsets still point into `content`.
        scan = _FLAG.sub(lambda f: " " * len(f.group()), content)
        out: list[Detection] = []
        for m in _TAGS.finditer(scan):
            hidden = decode(m.group())
            message = len(hidden.strip()) >= MESSAGE_LENGTH
            out.append(
                Detection(
                    entity_type="INJECTION.HIDDEN_TAG_TEXT",
                    # A hidden sentence has no innocent reading; a lone stray tag might.
                    score=0.9 if message else 0.5,
                    start=m.start(),
                    end=m.end(),
                    sample=(
                        snippet(hidden, 0, len(hidden))
                        if hidden
                        else f"{len(m.group())} tag characters"
                    ),
                    owasp_id=OWASP,
                    atlas_id=ATLAS,
                    detail={"signal": "hidden_text", "count": len(m.group())},
                )
            )
        return out
