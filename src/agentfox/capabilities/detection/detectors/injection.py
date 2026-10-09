"""Prompt-injection and jailbreak detection (NOM-RTG-01).

Design position, stated because it drives the code: detection alone is a losing
arms race. This detector is deliberately *table stakes* — it exists to catch the
common cases cheaply and inside the latency budget, while the durable defence is
containment (``policy`` + taint tracking).

Three signal families, scored and combined:
  1. **Lexical** — known override/jailbreak phrasings.
  2. **Structural** — fake role delimiters, injected system blocks, encoded payloads.
  3. **Contextual** — severity is raised when the content arrived from an untrusted
     surface. The *same string* is far more suspicious in a retrieved document than
     in a user's message, and no model-era string filter models that.

Reference material: the multi-layer approach in Rebuff (stale) and
the scanner taxonomy of LLM Guard (archived Jul 2026). Reimplemented, not depended on.
"""

from __future__ import annotations

import base64
import codecs
import re

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    redact_sample,
    snippet,
)
from agentfox.capabilities.detection.normalize import (
    View,
    despaced,
    evasion_score,
    hidden_markup,
    normalize,
)
from agentfox.capabilities.detection.prefilter import LoweredText, opening_literals
from agentfox.core.vocab import taint_rank

OWASP = "LLM01"
ATLAS = "AML.T0051"
ATLAS_JAILBREAK = "AML.T0054"

# --- 1b. Paraphrase and non-English -----------------------------------------
# The corpus showed the original table caught canonical English and nothing else: an
# attacker who rewrites the sentence, or writes it in French, walked straight through.
# Neither is a sophisticated attack — non-English content is not an attack at all, it
# is Tuesday at any multinational.

_PARAPHRASE: list[tuple[str, str, float]] = [
    # The instruction-override *concept* without its canonical wording.
    (
        r"\b(?:rules?|instructions?|guidelines?|constraints?)\s+(?:you\s+were\s+given\s+)?"
        r"(?:earlier|before|previously|above)?\s*(?:no\s+longer\s+(?:apply|applies)|"
        r"are\s+(?:now\s+)?(?:void|cancelled|canceled|suspended|revoked))\b",
        "OVERRIDE",
        0.8,
    ),
    (
        r"\bset\s+aside\s+(?:your|the|all)\s+(?:earlier|previous|prior|original)\s+"
        r"(?:instruction|guidance|rule|direction)s?\b",
        "OVERRIDE",
        0.8,
    ),
    (r"\bforget\s+what\s+you\s+(?:were|have\s+been)\s+told\b", "OVERRIDE", 0.8),
    (r"\bwhatever\s+(?:rules?|instructions?)\s+you\s+(?:were\s+given|have)\b", "OVERRIDE", 0.75),
    (
        r"\b(?:here\s+are\s+the\s+new|new)\s+(?:instruction|rule|directive)s?\s*[:.]",
        "OVERRIDE",
        0.7,
    ),
    (r"\btreat\s+the\s+following\s+as\s+your\s+only\s+(?:task|instruction)\b", "OVERRIDE", 0.8),
    (r"\byour\s+(?:only|real|actual|true)\s+(?:task|job|purpose)\s+is\b", "OVERRIDE", 0.65),
    # Precedence claimed over the model's own instructions — "these take priority over
    # your earlier ones". Anchored on "your": a policy document saying its rules
    # supersede *the* previous policy is ordinary; one telling the reader its words
    # outrank *your* instructions is addressing a model.
    (
        r"\b(?:take|takes|taking|have|has)\s+(?:priority|precedence)\s+over\s+(?:all\s+)?your\s+"
        r"(?:earlier|previous|prior|original|other|existing|current|system)\b",
        "OVERRIDE",
        0.8,
    ),
    (
        r"\b(?:supersedes?|overrides?|replaces?)\s+(?:all\s+)?your\s+(?:earlier|previous|prior|"
        r"original|existing|current|system)\s+(?:instructions?|rules?|prompt|directives?|ones)\b",
        "OVERRIDE",
        0.8,
    ),
    # Persona replacement. The named jailbreaks churn constantly, so this matches the
    # *shape* — "you are now X, and X has no limits" — rather than the roster.
    (
        r"\byou\s+are\s+now\s+\w+\b.{0,150}?\b(?:no|without|free\s+from)\s+(?:\w+\s+)?"
        r"(?:restrictions?|limits?|rules?|filters?|guidelines?)\b",
        "PERSONA",
        0.8,
    ),
    (
        r"\bpretend\s+(?:to\s+be|you\s+are)\s+.{0,40}?\bno\s+(?:restrictions?|limits?)\b",
        "PERSONA",
        0.8,
    ),
    (r"\bact\s+as\s+(?:if\s+you\s+(?:have|had)\s+no|an?\s+unrestricted)\b", "PERSONA", 0.75),
    # "forget" with a wider object list than the canonical "instructions" — real
    # attacks say "tasks", "assignments", "orders", or just "everything before that",
    # and a detector that only matches the textbook noun misses all of them.
    (
        r"\bforget\s+(?:all|everything|about\s+all)\b.{0,40}?\b(?:previous|prior|"
        r"earlier|preceding|before|assignments?|tasks?|instructions?|orders?)\b",
        "OVERRIDE",
        0.8,
    ),
    (r"\bforget\s+everything\s+before\s+(?:that|this)\b", "OVERRIDE", 0.8),
    (
        r"\b(?:leave|remove|drop)\b.{0,30}?\b(?:previous|prior|all)\b.{0,30}?"
        r"\b(?:behind|out\s+of\s+your\s+head)\b",
        "OVERRIDE",
        0.75,
    ),
    # "ignore" with the same wider object list, plus objects the canonical pattern
    # doesn't cover (orders, commands, context).
    (
        r"\bignore\s+(?:all\s+)?(?:the\s+)?(?:preceding|foregoing)\s+"
        r"(?:orders?|commands?|instructions?)\b",
        "OVERRIDE",
        0.85,
    ),
    (r"\bignore\s+(?:the\s+)?above\s+and\s+(?:say|output|write|print)\b", "OVERRIDE", 0.8),
    (
        r"\bignore\s+(?:all\s+)?(?:provided\s+)?context\s+and\s+articles?\b",
        "OVERRIDE",
        0.7,
    ),
    # A new task or instruction set announced as replacing the current one — the
    # "here's what happens next" framing an attacker uses right before the payload.
    (
        r"\b(?:new|further|more)\s+(?:tasks?|instructions?)\s+(?:follow|are\s+followed)\b",
        "OVERRIDE",
        0.7,
    ),
    # System-prompt exfiltration phrasing not covered by the canonical
    # SYSTEM_PROMPT_LEAK pattern in _LEXICAL (that one now also tolerates the "all"/
    # "following"/"text" insertions this dataset's examples used).
    (
        r"\bwhat\s+(?:is|was)\s+written\s+(?:above|at\s+the\s+beginning\s+of\s+this\s+prompt)\b",
        "LEAK",
        0.7,
    ),
    (r"\buse\s+also\s+information\s+in\s+the\s+prompt\s+to\s+answer\b", "LEAK", 0.6),
    # A covert override phrased as "don't answer that, output this instead" — the
    # instruction hijacks the response rather than asking a question.
    (
        r"\bdo\s+not\s+answer\s+this\s+question\b.{0,30}?\b(?:just\s+)?output\b",
        "OVERRIDE",
        0.75,
    ),
    # Fictional/hypothetical framing that strips the assistant's identity —
    # "if we're in a theoretical world where you're no longer X" — is a distinct,
    # well-documented jailbreak shape from bare persona assignment: a legitimate
    # hypothetical question doesn't need to first announce that the assistant isn't
    # itself anymore.
    (
        r"\bif\s+we\s+(?:are\s+)?(?:speaking|talking)\s+about\s+an?\s+"
        r"(?:\w+\s+)?(?:theoretical|hypothetical|fictional)\s+world\s+where\s+you\s+"
        r"(?:are|were)\s+(?:no(?:\s+longer)?|not)\b",
        "PERSONA",
        0.75,
    ),
    # "Stay in character no matter what" is the standard marker of a roleplay
    # jailbreak — it's the instruction that stops the model from ever exiting the
    # persona to apply its own judgment, and it's rare in ordinary creative-writing
    # requests, which don't need to forbid breaking character in the first place.
    (
        r"\b(?:never|without\s+ever)\s+break(?:ing)?\s+(?:character|role)\b",
        "PERSONA",
        0.7,
    ),
    (
        r"\bstay(?:s|ing)?\s+(?:fully\s+)?in\s+(?:character|role)\b.{0,60}?"
        r"\b(?:no\s+matter\s+what|regardless|even\s+if)\b",
        "PERSONA",
        0.7,
    ),
    # Overriding a refusal/abstention instruction specifically — "you're not
    # supposed to say there's no answer, you must always respond" — targets the
    # model's own safety/abstention behavior directly, which is a different (and
    # more targeted) technique than a blanket instruction-override.
    (
        r"\b(?:never|don'?t|do\s+not)\s+refuse\s+to\s+answer\b",
        "OVERRIDE",
        0.65,
    ),
    (
        r"\byou\s+(?:are|were)\s+not\s+supposed\s+to\s+(?:say|tell|mention)\b.{0,60}?"
        r"\byou\s+(?:are|must)\s+(?:always\s+)?(?:supposed\s+to\s+)?(?:respond|answer)\b",
        "OVERRIDE",
        0.7,
    ),
    # Exfiltrating the model's internal representation rather than its
    # instructions — the same LLM07 concern (LEAK), different target.
    (
        r"\b(?:return|output|show|reveal|give\s+me)\s+(?:your|the)\s+"
        r"(?:embeddings?|internal\s+state|hidden\s+state|token\s+probabilit\w*)\b",
        "LEAK",
        0.7,
    ),
]

#: The same concept across the languages an enterprise agent actually meets. Each
#: requires the *verb* (ignore/forget) as well as the object, so ordinary sentences
#: that merely contain the word "instructions" do not match.
_MULTILINGUAL: list[tuple[str, str, float]] = [
    # French
    (
        r"\b(?:ignorez?|oubliez?)\s+(?:toutes?\s+)?les\s+instructions?\s+"
        r"(?:pr[ée]c[ée]dentes?|ant[ée]rieures?)\b",
        "OVERRIDE",
        0.85,
    ),
    # German
    (
        r"\b(?:ignoriere?|vergiss|missachte)\s+(?:alle\s+)?(?:vorherigen?|bisherigen?|"
        r"vorangegangenen?)\s+(?:Anweisungen|Anleitungen|Regeln)\b",
        "OVERRIDE",
        0.85,
    ),
    (
        r"\bh[oö]re?\s+nicht\s+auf\b.{0,40}?\bsondern\b",
        "OVERRIDE",
        0.7,
    ),
    (
        r"\bvergiss\b.{0,40}?\b(?:aufgaben|auftr[äa]ge|anweisungen|davor|alles)\b",
        "OVERRIDE",
        0.75,
    ),
    (r"\bignorier(?:en|e)?\s+(?:sie\s+)?die\s+obigen\s+anweisungen\b", "OVERRIDE", 0.85),
    (
        r"\b(?:nun|jetzt)\s+folgen\s+(?:neue|weitere)\s+(?:aufgaben|anweisungen)\b",
        "OVERRIDE",
        0.7,
    ),
    (
        r"\balle\s+(?:vorherigen|bisherigen)\s+informationen\b.{0,50}?"
        r"\b(?:irrelevant|nicht\s+ganz)\b",
        "OVERRIDE",
        0.7,
    ),
    # Spanish / Portuguese
    (
        r"\b(?:ignora|olvida|ignore|esque[çc]a)\s+(?:todas?\s+)?(?:las?|as)\s+"
        r"(?:instrucciones|instru[çc][õo]es)\s+(?:anteriores|previas|pr[ée]vias)\b",
        "OVERRIDE",
        0.85,
    ),
    (r"\bolvid[ae]\s+todas?\s+las\s+instrucciones\b", "OVERRIDE", 0.85),
    # Italian
    (r"\bignora\s+(?:tutte\s+)?le\s+istruzioni\s+precedenti\b", "OVERRIDE", 0.85),
    # Russian
    (r"(?:игнорируй|забудь|проигнорируй)\s+(?:все\s+)?предыдущие\s+инструкции", "OVERRIDE", 0.85),
    # Japanese
    (
        r"(?:以前|これまで|上記)の(?:指示|命令)(?:を|は)?\s*(?:すべて|全て)?\s*無視",
        "OVERRIDE",
        0.85,
    ),
    # Chinese
    (r"忽略(?:所有)?(?:之前|先前|以上)的(?:指令|指示|规则)", "OVERRIDE", 0.85),
    # Korean
    (r"이전\s*지시(?:사항)?(?:을|를)?\s*무시", "OVERRIDE", 0.85),
]

_EXTRA_LEXICAL: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(pattern, re.I | re.UNICODE), f"INJECTION.INSTRUCTION_{kind}", score)
    for pattern, kind, score in (_PARAPHRASE + _MULTILINGUAL)
]


# --- 1. Lexical signals ----------------------------------------------------
#: What an override is an override *of*. One list, shared by the "ignore" and
#: "disregard" patterns, because the failure it fixes was the two lists drifting: neither
#: had `restrictions` or `constraints`, so "Ignore prior restrictions" and "Disregard
#: your constraints" were silent misses — and those are two of the four attacker
#: payloads in ``benchmarks/containment/``, meaning the repo's own canonical attack text
#: contained misses nothing was measuring (``benchmarks/adaptive/``, finding 3).
#:
#: The precision anchor is *not* this list. It is the qualifier in front of it —
#: previous / prior / above / earlier / your — which is what separates "ignore prior
#: rules" from "ignore the rules in column B". So the object list can be generous;
#: widening the qualifier could not be.
_OVERRIDE_OBJECT = (
    r"(?:instruction|prompt|rule|direction|message|restriction|constraint|guideline|"
    r"limitation|limit|polic(?:y|ie)|guardrail|safeguard|safety\s+rule|directive|filter|"
    r"boundar(?:y|ie)|protocol|training)"
)

#: The persona half of a persona jailbreak: the text tells the model it is now
#: someone else. Covers "you are now", "from now on you are", "you are about to
#: become", "pretend you are", "act as", "role-play as", "imagine you are" and
#: "assume the role of".
_PERSONA_SWITCH = (
    # The leading lookahead is only a fast reject: one character class test at each
    # word start instead of trying every branch, which made this the most expensive
    # pattern in the table on a 32 KB document.
    r"\b(?=[yfpabrit])(?:\byou\s+are\s+now\b|\bfrom\s+now\s+on,?\s+(?:you(?:'re|\s+are|\s+will\s+(?:be|act))|"
    r"act\s+as|be)\b|\byou(?:'re|\s+are)\s+(?:going|about)\s+to\s+(?:be|become|act|play|"
    r"pretend|immerse)\b|\bpretend\s+(?:that\s+)?(?:you(?:'re|\s+are)|to\s+be)\b|"
    r"\b(?:act|role-?play|behave|respond)\s+as\b|\bimagine\s+(?:that\s+)?you(?:'re|\s+are)\b|"
    r"\b(?:assume|take\s+on|adopt|play)\s+the\s+(?:role|persona|character|identity)\s+of\b)"
)

#: The other half: whatever constrained the model is gone. Only constraint *nouns*
#: count after "no"/"without", so "with no prior experience" and "with no tolerance
#: for typos" do not; and "uncensored" or "unfiltered" only when it describes the
#: model ("an uncensored AI"), because NotInject's "an author revealing an uncensored
#: version of your story" is a writing request.
_RESTRICTION_REMOVED = (
    r"(?:\b(?:no|without(?:\s+any)?|free\s+(?:from|of)(?:\s+all|\s+any)?|unbound\s+by|"
    r"not\s+bound\s+by|ignores?|bypass(?:es)?|disregards?|(?:does\s+not|doesn'?t|never)\s+"
    r"(?:follow|obey|have|abide\s+by))\s+(?:\w+\s+){0,3}?(?:rules?|restrictions?|filters?|"
    r"guidelines?|censorship|ethics|morals?|morality|boundaries|polic(?:y|ies)|safeguards?|"
    r"guardrails?|limitations?|constraints?)\b|\b(?:unrestricted|unfiltered|uncensored|amoral)"
    r"\s+(?:\w+\s+){0,2}?(?:ai|assistant|model|chatbot|bot|llm|gpt|mode|persona|entity|"
    r"version\s+of\s+(?:yourself|you|chatgpt|gpt|the\s+ai))\b|\bjailbroken\b|"
    r"\bcan\s+do\s+anything\b|\bdo\s+anything\s+now\b|\bnever\s+refuses?\b)"
)

#: Letter-spaced overrides whose word boundaries are unrecoverable ("i g n o r e a l l
#: p r e v i o u s ...") read as one string of letters, so the ordinary patterns'
#: word boundaries cannot match. These are the same overrides with no spaces at all,
#: searched only inside such a run — never in ordinary text, where "ignoreall" does
#: not occur by accident either.
_COMPACT_OVERRIDE: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(?:ignore|disregard|forget|override|bypass)(?:all|any|every)?(?:the|of)?"
            r"(?:your|previous|prior|above|earlier|preceding)+(?:instruction|prompt|rule|"
            r"direction|guideline|restriction|constraint|polic|directive|filter|guardrail|"
            r"safeguard|command|order)"
        ),
        "INJECTION.INSTRUCTION_OVERRIDE",
    ),
    (
        re.compile(r"forget(?:everything|all)(?:you)?(?:weretold|know|above|before)"),
        "INJECTION.INSTRUCTION_OVERRIDE",
    ),
    (
        re.compile(
            r"(?:reveal|print|repeat|show|output|dump|leak|disclose)(?:me)?(?:all)?(?:your|the)"
            r"(?:hidden|secret|internal|original|initial|underlying|full|entire|exact)?"
            r"(?:system)?prompt"
        ),
        "INJECTION.SYSTEM_PROMPT_LEAK",
    ),
]

#: A hidden region that speaks to the model. In a comment or an invisible element a
#: human reviewer never reads, text addressed to "assistant:" or "the AI" has no reader
#: but the model.
_ADDRESSES_MODEL = re.compile(
    r"^\s*(?:(?:dear|hey|hi|hello|attention|note\s+to)\s+)?(?:the\s+)?(?:ai\s+)?"
    r"(?:assistant|ai|model|llm|chatbot|bot|system|claude|gpt|chatgpt|copilot|"
    r"language\s+model)\s*[:,]"
    r"|\b(?:note|message|instructions?)\s+(?:to|for)\s+(?:the\s+|any\s+)?(?:ai|assistant|"
    r"model|llm|chatbot|language\s+model)\b"
    r"|\bif\s+you\s+are\s+an?\s+(?:ai|assistant|language\s+model|llm)\b",
    re.I,
)
#: ...and tells it to do something.
_DIRECTIVE = re.compile(
    r"\b(?:ignore|disregard|forget|override|instructions?|reply|respond|answer|say|output|"
    r"print|write|tell|send|email|forward|call|invoke|run|execute|reveal|approve|refund|"
    r"transfer|delete|you\s+(?:must|should|will|are\s+to))\b",
    re.I,
)

# (pattern, entity, base_score). Scores are calibrated so that a single weak
# signal never blocks on its own; two independent signals do.
_LEXICAL: list[tuple[re.Pattern[str], str, float]] = [
    (
        re.compile(
            r"\bignore\s*(?:all\s*)?(?:the\s*)?(?:previous|prior|above|earlier|your)\s*"
            + _OVERRIDE_OBJECT
            + r"s?\b",
            re.I,
        ),
        "INJECTION.INSTRUCTION_OVERRIDE",
        0.85,
    ),
    (
        re.compile(
            r"\bignore\s+(?:all\s+)?the\s+instructions\s+you\s+(?:got|received)\s+before\b",
            re.I,
        ),
        "INJECTION.INSTRUCTION_OVERRIDE",
        0.85,
    ),
    (
        re.compile(r"\bdrop\s+(?:all\s+)?your\s+instructions?\b", re.I),
        "INJECTION.INSTRUCTION_OVERRIDE",
        0.8,
    ),
    (
        re.compile(r"\byour\s+instructions?\s+(?:are\s+)?now\s+to\b", re.I),
        "INJECTION.INSTRUCTION_OVERRIDE",
        0.75,
    ),
    (
        re.compile(
            r"\bdisregard\s*(?:all\s*)?(?:previous|prior|the\s*above|your)\s*"
            + _OVERRIDE_OBJECT
            + r"s?\b",
            re.I,
        ),
        "INJECTION.INSTRUCTION_OVERRIDE",
        0.85,
    ),
    (
        re.compile(
            r"\bforget\s*(?:everything|all)\s*(?:you\s*)?(?:were\s*told|know|above)\b", re.I
        ),
        "INJECTION.INSTRUCTION_OVERRIDE",
        0.8,
    ),
    (
        re.compile(
            r"\byou\s+are\s+(?:now|actually)\s+(?:a|an|in)\b.{0,60}?"
            r"\b(?:unrestricted|unfiltered|jailbroken|developer\s+mode|DAN)\b",
            re.I,
        ),
        "INJECTION.PERSONA_OVERRIDE",
        0.85,
    ),
    (
        # "on" only when it ends the phrase: "developer mode on my Android phone" is a
        # settings question, "Developer Mode on." is a switch being thrown.
        re.compile(
            r"\b(?:developer|god|admin|debug|dan)\s+mode\s+(?:enabled|activated|on\b(?!\s+"
            r"(?:my|your|the|a|an|this|that|his|her|their|our|its|android|ios|iphone|windows|"
            r"mac)\b))",
            re.I,
        ),
        "INJECTION.PERSONA_OVERRIDE",
        0.75,
    ),
    (
        # Persona jailbreak: a persona switch *and* the removal of what constrains it, in
        # the same sentence. Either half alone is ordinary — "act as a translator",
        # "pretend you are the customer in this role-play", "no restrictions on returns"
        # — so neither is enough. The named jailbreaks churn constantly; this matches
        # the shape, not the roster.
        re.compile(_PERSONA_SWITCH + r"[^.!?\n]{0,150}?" + _RESTRICTION_REMOVED, re.I),
        "INJECTION.PERSONA_OVERRIDE",
        0.8,
    ),
    (
        # DAN by name. Case-sensitive on the name, because Dan from billing is a person.
        re.compile(
            r"\b(?=[yapkcnbd])(?:you\s+are|you're|act\s+as|pretend\s+to\s+be|known\s+as|called|named|"
            r"become)\s+(?:now\s+)?(?-i:DAN)\b|\bdo\s+anything\s+now\b",
            re.I,
        ),
        "INJECTION.PERSONA_OVERRIDE",
        0.8,
    ),
    (
        re.compile(r"\b(?:pretend|imagine)\s+(?:you\s+are|to\s+be)\s+(?:an?\s+)?evil\b", re.I),
        "INJECTION.PERSONA_OVERRIDE",
        0.75,
    ),
    (
        re.compile(r"\bnew\s+(?:system\s+)?(?:instruction|prompt|directive)s?\s*[:\-]", re.I),
        "INJECTION.INSTRUCTION_INJECTION",
        0.8,
    ),
    (
        re.compile(
            r"\b(?:reveal|print|repeat|show|output|display|dump|leak|disclose)\s+"
            r"(?:me\s+)?(?:all\s+)?(?:your|the)\s+(?:following\s+)?"
            # "the hidden system prompt", "your original instructions": a word or two
            # between the article and the thing asked for.
            r"(?:(?:hidden|secret|internal|original|initial|underlying|full|entire|"
            r"exact|confidential|developer)\s+){0,2}"
            r"(?:system\s+)?(?:prompt|instruction|rule)s?"
            r"(?:\s+text)?\b",
            re.I,
        ),
        "INJECTION.SYSTEM_PROMPT_LEAK",
        0.8,
    ),
    (
        re.compile(r"\bwhat\s+(?:were|are)\s+your\s+(?:original\s+)?instructions\b", re.I),
        "INJECTION.SYSTEM_PROMPT_LEAK",
        0.65,
    ),
    (
        # A distinct, real extraction phrasing that never names "prompt" or
        # "instructions" at all — "repeat/print the text above" — so the pattern
        # above this one, which requires that vocabulary, structurally can't
        # catch it. Found via redteam probe `system_prompt.leak` scoring a real
        # 0.0 (benchmarks/redteam/README.md); verified against train/test/
        # notinject before shipping (zero score>=0.6 hits on any of the three).
        re.compile(
            r"\b(?:repeat|print|output|show)\s+(?:everything|the\s+(?:text|words?|"
            r"instructions?|conversation))\s+(?:above|before\s+(?:this|that))\b",
            re.I,
        ),
        "INJECTION.SYSTEM_PROMPT_LEAK",
        0.75,
    ),
    (
        re.compile(
            r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|mention\s+to|alert)\s+"
            r"(?:the\s+)?(?:user|human|operator)\b",
            re.I,
        ),
        "INJECTION.COVERT_INSTRUCTION",
        0.8,
    ),
    (
        re.compile(
            r"\bwithout\s+(?:asking|informing|notifying|confirming\s+with)\s+"
            r"(?:the\s+)?(?:user|human|anyone)\b",
            re.I,
        ),
        "INJECTION.COVERT_INSTRUCTION",
        0.7,
    ),
    (
        re.compile(
            r"\b(?:send|email|post|upload|exfiltrate|forward)\b.{0,40}?"
            r"\b(?:to|at)\s+(?:https?://|[\w.\-]+@)",
            re.I,
        ),
        "INJECTION.EXFILTRATION",
        0.75,
    ),
    (
        # Data smuggled out through an image the client renders: an instruction to
        # load/render a markdown image whose URL carries a query string. Rendering
        # it sends the request, and whatever was put in the query, to that host.
        re.compile(
            r"\b(?:load|render|display|show|include|embed|fetch|append|insert|add)\b"
            r".{0,40}?!\[[^\]]{0,60}\]\(\s*https?://[^)\s]+\?[^)\s]*=[^)\s]+\)",
            re.I,
        ),
        "INJECTION.EXFILTRATION",
        0.8,
    ),
    (
        re.compile(
            r"\bpretend\s+(?:that\s+)?(?:you|to\s+be)\b.{0,40}?"
            r"\b(?:no|without)\s+(?:restriction|filter|rule|guardrail)",
            re.I,
        ),
        "INJECTION.JAILBREAK",
        0.8,
    ),
    (
        re.compile(
            r"\bfor\s+(?:educational|research|testing)\s+purposes\s+only\b.{0,60}?"
            r"\b(?:ignore|bypass|disable)\b",
            re.I,
        ),
        "INJECTION.JAILBREAK",
        0.7,
    ),
    (
        re.compile(
            r"\bthis\s+is\s+(?:a\s+)?(?:test|simulation|hypothetical)\b.{0,50}?"
            r"\b(?:safety|guardrail|filter|policy)\b.{0,30}?\b(?:off|disabled|not\s+apply)",
            re.I,
        ),
        "INJECTION.JAILBREAK",
        0.7,
    ),
]

# Each pattern with the words a match must open with, so a large benign document
# skips the patterns it cannot match instead of paying one full regex pass apiece
# (see `detection.prefilter`).
_PATTERNS: list[tuple[re.Pattern[str], str, float, frozenset[str] | None]] = [
    (pattern, entity, score, opening_literals(pattern))
    for pattern, entity, score in _LEXICAL + _EXTRA_LEXICAL
]

# --- 2. Structural signals -------------------------------------------------
_ROLE_DELIMITER = re.compile(r"(?:^|\n)\s*(?:###\s*)?(?:system|assistant|user)\s*:\s*", re.I | re.M)
_CHATML = re.compile(r"<\|(?:im_start|im_end|system|endoftext)\|>", re.I)
_XML_SYSTEM = re.compile(r"</?(?:system|instructions?|admin)>", re.I)
_HIDDEN_CHARS = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
_LONG_B64 = re.compile(r"\b[A-Za-z0-9+/]{60,}={0,2}\b")

# Instructions embedded where only data belongs — the tool-poisoning shape.
_IMPERATIVE_IN_DATA = re.compile(
    r"\b(?:you\s+must|always|before\s+(?:using|calling|responding))\b.{0,60}?"
    r"\b(?:call|invoke|send|read|include|append)\b",
    re.I,
)


def _decodes_to_suspicious_text(blob: str) -> str | None:
    """A base64 payload that decodes to instruction-like text is a strong signal."""
    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
        text = raw.decode("utf-8", errors="strict")
    except Exception:
        return None
    if len(text) < 12:
        return None
    for pattern, _entity, _score in _LEXICAL:
        if pattern.search(text):
            return text
    return None


class InjectionHeuristicDetector(BaseDetector):
    #: LLM07 as well as LLM01: this detector already stamps `SYSTEM_PROMPT_LEAK`
    #: detections with it, and nothing in the control catalogue mentions LLM07, so
    #: that coverage was real and entirely uncredited.
    covers_threats = ("LLM01", "LLM07", "AML.T0051", "AML.T0054")
    # This detector iterates the views itself, so that it can raise the score for
    # content that only matched after de-obfuscation and flag the obfuscation alone.
    handles_views = True
    key = "injection.heuristic"
    version = "1.3"
    surfaces = (
        "input",
        "retrieved",
        "tool_result",
        "output",
        "memory_write",
        "agent_message",
        # The model's own reasoning: a detection here means the payload
        # was adopted, not merely present.
        "reasoning",
        # Tool-call arguments. Without it no shipped injection detector ran on
        # this surface and `injection.in_tool_arguments` (tool-containment) could
        # never fire: an instruction smuggled into an argument was seen only as
        # whatever PII it happened to contain.
        "tool_args",
    )

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        out: list[Detection] = []

        # Untrusted provenance raises severity. Rank 0/1 == none/user (trusted-ish);
        # anything above is content the agent pulled in, where an instruction has no
        # legitimate reason to be.
        provenance_boost = 0.15 if taint_rank(context.taint_source) >= 2 else 0.0
        surface_boost = 0.1 if context.surface in ("retrieved", "tool_result") else 0.0
        boost = provenance_boost + surface_boost

        # Every lexical pattern is matched against every normalised reading of the
        # content, not just the raw bytes. The corpus is unambiguous about why: the
        # misses were separators, homoglyphs, fullwidth, base64 and percent-encoding —
        # none of them an attack on the pattern, all of them an attack on the
        # assumption that what the detector reads is what the model reads.
        normalised = normalize(content)
        seen: set[tuple[str, int, int]] = set()
        # Two readings only this detector asks for (see `normalize.despaced` and
        # `normalize.hidden_markup`): words written one letter at a time, and the text
        # inside markup a human never sees. Both are cheap no-ops on ordinary content.
        despaced_view, spaced_runs = despaced(content)
        hidden_views = hidden_markup(content)
        views = list(normalised.views)
        if despaced_view is not None:
            views.append(despaced_view)
        views.extend(hidden_views)
        # Rot13: a cipher every model reads and no pattern does. Ordinary text read
        # this way is gibberish, so it cannot match an attack pattern by accident.
        if len(content) >= 20 and any(c.isalpha() for c in content):
            views.append(
                View(
                    text=codecs.encode(content, "rot13"),
                    offsets=list(range(len(content))),
                    kind="rot13",
                    note="rot13",
                )
            )

        lowered = [LoweredText(view.text) for view in views]
        for pattern, entity, base_score, literals in _PATTERNS:
            for view, low in zip(views, lowered, strict=True):
                if not low.may_match(literals):
                    continue
                match = pattern.search(view.text)
                if match is None:
                    continue
                start, end = view.origin(match.start(), match.end())
                key = (entity, start, end)
                if key in seen:
                    continue
                seen.add(key)
                atlas = ATLAS_JAILBREAK if "JAILBREAK" in entity or "PERSONA" in entity else ATLAS
                # Content that had to be de-obfuscated before it matched is more
                # suspicious than content that matched as written, not less.
                obfuscation_boost = 0.1 if view.kind != "normalized" else 0.0
                out.append(
                    Detection(
                        entity_type=entity,
                        score=min(1.0, base_score + boost + obfuscation_boost),
                        start=start,
                        end=end,
                        sample=snippet(content, start, end),
                        owasp_id="LLM07" if "SYSTEM_PROMPT_LEAK" in entity else OWASP,
                        atlas_id=atlas,
                        detail={
                            "signal": "lexical",
                            "taint": context.taint_source,
                            "view": view.kind,
                            "transforms": normalised.transforms,
                        },
                    )
                )
                break  # one view is enough; the rest would report the same thing

        # A letter-spaced run with one gap throughout has lost its word boundaries, so
        # it is searched as one string for the overrides themselves.
        for run in spaced_runs:
            if not run.uniform:
                continue
            compact = run.letters.lower()
            for pattern, entity in _COMPACT_OVERRIDE:
                if pattern.search(compact) is None or (entity, run.start, run.end) in seen:
                    continue
                seen.add((entity, run.start, run.end))
                out.append(
                    Detection(
                        entity_type=entity,
                        score=min(1.0, 0.85 + boost + 0.1),
                        start=run.start,
                        end=run.end,
                        sample=snippet(content, run.start, run.end),
                        owasp_id="LLM07" if "SYSTEM_PROMPT_LEAK" in entity else OWASP,
                        atlas_id=ATLAS,
                        detail={"signal": "lexical", "view": "despaced", "compact": True},
                    )
                )
                break

        # Hidden text addressed to the model and telling it to do something. Neither
        # half is unusual alone ("<!-- nav -->", "<!-- assistant editor: Jane -->"); a
        # comment that says "assistant: reply with..." has no reader but the model.
        for view in hidden_views:
            if not (_ADDRESSES_MODEL.search(view.text) and _DIRECTIVE.search(view.text)):
                continue
            start, end = view.origin(0, len(view.text))
            if ("INJECTION.HIDDEN_INSTRUCTION", start, end) in seen:
                continue
            seen.add(("INJECTION.HIDDEN_INSTRUCTION", start, end))
            out.append(
                Detection(
                    entity_type="INJECTION.HIDDEN_INSTRUCTION",
                    score=min(1.0, 0.8 + boost),
                    start=start,
                    end=end,
                    sample=snippet(content, start, end),
                    owasp_id=OWASP,
                    atlas_id=ATLAS,
                    detail={"signal": "structural", "hidden_in": view.note},
                )
            )

        # Obfuscation is evidence in its own right. Ordinary content is occasionally
        # fullwidth or occasionally base64; it is rarely both and almost never
        # zero-width. Content that went to lengths not to be read is worth a finding
        # even when nothing inside it matched — that is the case where a pattern set
        # is about to be one technique behind.
        evasion = evasion_score(normalised)
        if evasion >= 0.5 and taint_rank(context.taint_source) >= 2:
            out.append(
                Detection(
                    entity_type="INJECTION.OBFUSCATED_CONTENT",
                    score=min(1.0, evasion + boost),
                    start=0,
                    end=min(len(content), 120),
                    sample=snippet(content, 0, min(len(content), 120)),
                    owasp_id=OWASP,
                    atlas_id=ATLAS,
                    detail={
                        "signal": "evasion",
                        "techniques": [e.get("kind") for e in normalised.evasion],
                        "taint": context.taint_source,
                    },
                )
            )

        # Structural: fabricated role turns inside content that should be plain data.
        for pattern, entity in (
            (_CHATML, "INJECTION.CONTROL_TOKENS"),
            (_XML_SYSTEM, "INJECTION.FAKE_SYSTEM_BLOCK"),
        ):
            m = pattern.search(content)
            if m:
                out.append(
                    Detection(
                        entity_type=entity,
                        score=min(1.0, 0.8 + boost),
                        start=m.start(),
                        end=m.end(),
                        sample=snippet(content, m.start(), m.end()),
                        owasp_id=OWASP,
                        atlas_id=ATLAS,
                        detail={"signal": "structural"},
                    )
                )

        if context.surface in ("retrieved", "tool_result"):
            m = _ROLE_DELIMITER.search(content)
            if m:
                out.append(
                    Detection(
                        entity_type="INJECTION.ROLE_DELIMITER",
                        score=0.7,
                        start=m.start(),
                        end=m.end(),
                        sample=snippet(content, m.start(), m.end()),
                        owasp_id=OWASP,
                        atlas_id=ATLAS,
                        detail={"signal": "structural", "surface": context.surface},
                    )
                )
            m = _IMPERATIVE_IN_DATA.search(content)
            if m:
                out.append(
                    Detection(
                        entity_type="INJECTION.INSTRUCTION_IN_DATA",
                        score=0.65,
                        start=m.start(),
                        end=m.end(),
                        sample=snippet(content, m.start(), m.end()),
                        owasp_id="LLM03",
                        atlas_id="AML.T0053",
                        detail={"signal": "structural", "note": "tool-poisoning shape"},
                    )
                )

        # Invisible characters used to hide a payload from human review.
        hidden = _HIDDEN_CHARS.findall(content)
        if hidden:
            m = _HIDDEN_CHARS.search(content)
            assert m is not None
            out.append(
                Detection(
                    entity_type="INJECTION.HIDDEN_CHARACTERS",
                    score=0.6 + boost,
                    start=m.start(),
                    end=m.end(),
                    sample=f"{len(hidden)} zero-width/bidi characters",
                    owasp_id=OWASP,
                    atlas_id=ATLAS,
                    detail={"signal": "structural", "count": len(hidden)},
                )
            )

        # Encoded payloads that decode to instructions.
        for m in _LONG_B64.finditer(content):
            decoded = _decodes_to_suspicious_text(m.group())
            if decoded:
                out.append(
                    Detection(
                        entity_type="INJECTION.ENCODED_PAYLOAD",
                        score=min(1.0, 0.85 + boost),
                        start=m.start(),
                        end=m.end(),
                        sample=redact_sample(m.group(), keep=8),
                        owasp_id=OWASP,
                        atlas_id=ATLAS,
                        detail={"signal": "encoded", "decoded_sample": redact_sample(decoded, 12)},
                    )
                )
                break

        return out
