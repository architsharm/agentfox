"""The Jev client. One request, many questions, sorted keys.

Three facts from measurement shape this file.

**Latency is flat in question count.** 8 questions took 416ms and 512 took
524ms, with 512/512 correct at the top end. So the client batches everything
into one call and never splits; splitting buys nothing and costs a round
trip each time.

**Key order changes answers.** The same question over the same values
returned a median 0.53 with one key order and 0.98 on eight consecutive runs
with another. Python dict order is insertion order, so a refactor that built
state in a different sequence would silently move verdicts. Every payload is
serialised with ``sort_keys=True``.

**Input is ~$0.042 per million tokens and output is free**, so the 9,323
tokens that 512 questions cost is about four millionths of a dollar. Asking
more narrow questions is the right move economically as well as for accuracy.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

#: Measured: 512 questions answered correctly in one request. The cap here is
#: well under what the service accepted, because a batch this size is already
#: more policies than any single decision should turn on, and a smaller cap
#: keeps one bad caller from making a 10,000-question request.
MAX_QUESTIONS = 512


class JevUnavailable(RuntimeError):
    """The service did not answer. Never a verdict — the caller decides."""


@dataclass(slots=True)
class JevAnswer:
    question_id: str
    type: str
    value: Any
    #: For noul this is |2p-1|; the API returns confidence only for the
    #: other two. A noul near 0.5 means "similar probability either way",
    #: not "medium intensity".
    confidence: float


@dataclass(slots=True)
class JevResult:
    answers: dict[str, JevAnswer] = field(default_factory=dict)
    model: str = ""
    input_tokens: int = 0
    duration_ms: float = 0.0


class JevClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        endpoint: str = ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 10.0,
    ) -> None:
        self._key = api_key or os.environ.get("JEV_API_KEY", "")
        self._endpoint = endpoint
        self._model = model
        self._timeout = timeout_s

    def available(self) -> bool:
        return bool(self._key) and self._egress_allowed()

    @staticmethod
    def _egress_allowed() -> bool:
        """Zero egress by default, same gate every other outbound caller uses.

        Defence in depth rather than the main control: `JudgmentGateway` is
        what product code should call, because it also redacts. This check
        exists so that a direct `JevClient` call — the mistake this codebase
        already made once with presidio's model download — cannot quietly
        reach the network with `allow_egress` off.
        """
        try:
            from agentfox.core.config import get_settings

            return bool(get_settings().allow_egress)
        except Exception:  # noqa: BLE001 - no settings, assume the safe answer
            return False

    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> JevResult:
        if not questions:
            return JevResult()
        if not self._key:
            raise JevUnavailable("no JEV_API_KEY configured")
        if not self._egress_allowed():
            raise JevUnavailable(
                "allow_egress is off; judgment would have sent state off-box. "
                "Use JudgmentGateway, or set allow_egress to opt in explicitly."
            )
        if len(questions) > MAX_QUESTIONS:
            raise ValueError(f"{len(questions)} questions exceeds the {MAX_QUESTIONS} cap")
        body = {"model": self._model, "state": state, "questions": questions}
        # sort_keys is load-bearing. See the module docstring.
        data = json.dumps(body, sort_keys=True, default=str).encode()
        req = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise JevUnavailable(f"HTTP {exc.code}: {exc.read().decode()[:200]}") from exc
        except Exception as exc:  # noqa: BLE001 - network, timeout, decode
            raise JevUnavailable(f"{type(exc).__name__}: {exc}") from exc

        out = JevResult(
            model=payload.get("model", ""),
            input_tokens=(payload.get("usage") or {}).get("input_tokens", 0),
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        for qid, a in (payload.get("answers") or {}).items():
            kind = a.get("type", "")
            if kind == "noul":
                p = float(a["noul"])
                out.answers[qid] = JevAnswer(qid, kind, p, abs(2 * p - 1))
            elif kind == "choice":
                out.answers[qid] = JevAnswer(
                    qid, kind, a["choice"], float(a.get("confidence", 0.0))
                )
            elif kind == "score":
                out.answers[qid] = JevAnswer(
                    qid, kind, float(a["score"]), float(a.get("confidence", 0.0))
                )
        return out
