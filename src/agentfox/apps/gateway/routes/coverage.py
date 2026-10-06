"""Coverage by threat — the security engineer's view of the same data.

Its own router rather than a path under `/api/compliance`, and that is the whole
argument in one line. A compliance framework is something you attest to; a threat
model is something you are attacked by. They share a shape and they are read by
different people, at different frequencies, to decide different things. Filing OWASP
as the sixth tab of the compliance page put the security engineer's primary lens
inside the GRC person's screen.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agentfox.apps.gateway.deps import current_user, db
from agentfox.capabilities.discovery.threats import coverage as threat_coverage
from agentfox.core.models import User

router = APIRouter(prefix="/api/coverage", tags=["coverage"])


@router.get("/threats")
def threats(
    window_days: int = Query(30, ge=1, le=365),
    session: Session = Depends(db),
    _user: User = Depends(current_user),
) -> dict[str, Any]:
    """Every published threat, and what this deployment actually does about it.

    Readable by every role. The question "are we covered against prompt injection"
    is not a privileged one, and a posture that only its owner can see is a posture
    nobody checks.
    """
    return threat_coverage(session, window_days=window_days)
