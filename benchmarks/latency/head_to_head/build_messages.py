"""Fixed message set shared by every system.

main: per map with agents, up to 10 runnable (non-skipped, non-empty) build_suite items,
      picked round-robin across (type, control) groups (seed 0)
      pool sampled to <=1000 (seed 0).
long: build_suite messages are all <230 chars, so for the length split 150 synthetic longer
      inputs are added (75 at 200-600 chars, 75 at 600-2400): several suite messages from one
      repo joined as a ticket/history document, like a tool result an agent would read.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from agentfox.capabilities.onboarding.attacks import build_suite

maps = Path(sys.argv[1])
out = Path(sys.argv[2])
rnd = random.Random(0)
pool, by_repo = [], {}
for f in sorted(maps.glob("*.json")):
    m = json.loads(f.read_text())
    if not m["structure"].get("agents"):
        continue
    suite = [a for a in build_suite(m["structure"]) if not a.skip and a.message]
    groups = {}
    for a in suite:
        groups.setdefault((a.type, bool(a.control)), []).append(a)
    picked = []
    while len(picked) < 10 and any(groups.values()):
        for k in sorted(groups):
            if groups[k] and len(picked) < 10:
                picked.append(groups[k].pop(rnd.randrange(len(groups[k]))))
    for a in picked:
        pool.append(
            {
                "set": "main",
                "repo": f.stem,
                "type": a.type,
                "control": bool(a.control),
                "message": a.message,
            }
        )
    by_repo[f.stem] = [a for g in groups.values() for a in g] + picked
main = rnd.sample(pool, min(1000, len(pool)))
longs = []
repos = sorted(r for r in by_repo if len(by_repo[r]) >= 20)
for i in range(150):
    lo, hi = (200, 600) if i < 75 else (600, 2400)
    target = rnd.randint(lo + 20, hi - 20)
    items = by_repo[rnd.choice(repos)][:]
    rnd.shuffle(items)
    parts, n_attack = [], 0
    text = "Ticket history (most recent first):\n"
    for a in items:
        nxt = text + f"- [{len(parts) + 1}] customer wrote: {a.message}\n"
        if len(nxt) > target and parts:
            break
        text = nxt
        parts.append(a)
        n_attack += not a.control
    text = text[: hi - 1]
    longs.append(
        {
            "set": "long",
            "repo": "synthetic",
            "type": "document",
            "control": n_attack == 0,
            "message": text,
        }
    )
msgs = main + longs
for i, s in enumerate(msgs):
    s["msg_id"] = i
    s["chars"] = len(s["message"])
out.write_text(json.dumps(msgs, indent=1))
print("pool", len(pool), "main", len(main), "long", len(longs))
