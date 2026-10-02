"""The learned rung: a small local classifier fitted to labelled history.

Granite Guardian and the cached prompt-injection models judge generic harm
categories, which is not the question here — no general safety model knows
whether "when shall I send the offer paperwork" states a hiring decision under
*this* policy. What does know that is a model fitted to this policy's own
labelled examples.

MiniLM (87MB, Apache-2.0, already cached) for sentence embeddings, plus
logistic regression in numpy. No new dependencies: sentence-transformers and
sklearn are not installed here, and adding extras to this project has broken
the suite before.

The honest question is not whether it fits the corpus but whether it survives
a shape it has never seen, so it is scored two ways:

    random        held-out cases, templates seen in training — the optimistic
                  read, and the right one for attack shapes already in your logs
    unseen shape  leave-one-template-out — every test case is a kind of answer
                  the model was never trained on, which is the pessimistic read
                  and the one that matters for a novel attack
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from jev_domains import DOMAINS  # noqa: E402

CACHE = pathlib.Path(__file__).parent / "jev_embeddings.npz"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def embed(texts: list[str]) -> np.ndarray:
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL)
    mod = AutoModel.from_pretrained(MODEL).eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            b = tok(
                texts[i : i + 64],
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            )
            h = mod(**b).last_hidden_state
            m = b["attention_mask"].unsqueeze(-1).float()
            v = (h * m).sum(1) / m.sum(1).clamp(min=1e-9)
            out.append(torch.nn.functional.normalize(v, dim=1).numpy())
    return np.vstack(out).astype(np.float32)


def fit(x: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 400) -> np.ndarray:
    """Plain L2 logistic regression, Newton-free; enough for 384 dims."""
    xb = np.hstack([x, np.ones((len(x), 1), dtype=np.float32)])
    w = np.zeros(xb.shape[1], dtype=np.float64)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-xb @ w))
        g = xb.T @ (p - y) / len(y) + l2 * np.r_[w[:-1], 0.0] / len(y)
        w -= 2.0 * g
    return w


def predict(w: np.ndarray, x: np.ndarray) -> np.ndarray:
    xb = np.hstack([x, np.ones((len(x), 1), dtype=np.float32)])
    return 1.0 / (1.0 + np.exp(-xb @ w))


L2_GRID = (3.0, 1.0, 0.3, 0.1, 0.03, 0.01, 0.003, 0.001)


def fit_tuned(x: np.ndarray, y: np.ndarray, seed: int = 0) -> np.ndarray:
    """Pick L2 on an inner split rather than by hand.

    A hand-picked 1.0 underfits these embeddings badly enough to look like a
    representation failure (72% on data it was *trained* on), so the strength
    has to be chosen, not assumed.
    """
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(x))
    best, best_acc = L2_GRID[0], -1.0
    for l2 in L2_GRID:
        acc = 0.0
        for f in range(3):
            te = order[f::3]
            tr = np.setdiff1d(order, te)
            if len(np.unique(y[tr])) < 2:
                continue
            acc += float(np.mean((predict(fit(x[tr], y[tr], l2=l2), x[te]) >= 0.5) == (y[te] == 1)))
        if acc > best_acc:
            best, best_acc = l2, acc
    return fit(x, y, l2=best)


def case_text(domain, case: dict) -> str:
    """Only the fields the agent produced; the policy is constant per domain."""
    st = case["state"]
    return " | ".join(f"{k}: {v}" for k, v in sorted(st.items()))


def main() -> int:
    texts, meta = [], []
    for domain in DOMAINS.values():
        for c in domain.cases:
            texts.append(case_text(domain, c))
            meta.append((domain.key, c["id"], c["template"], c["expect"] == "flag"))

    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=True)
        if list(z["ids"]) == [m[1] for m in meta]:
            emb = z["emb"]
            print(f"  embeddings from cache  {emb.shape}")
        else:
            emb = None
    else:
        emb = None
    if emb is None:
        print(f"  embedding {len(texts)} cases with {MODEL} ...")
        emb = embed(texts)
        np.savez(CACHE, emb=emb, ids=np.array([m[1] for m in meta], dtype=object))
        print(f"  embeddings {emb.shape} -> {CACHE.name}")

    results: dict = {}
    print("\n" + "=" * 78)
    print("Learned rung, scored per domain")
    print("=" * 78)
    print(f"  {'domain':15} {'random split':>14} {'unseen shape':>14}")
    for domain in DOMAINS.values():
        idx = np.array([i for i, m in enumerate(meta) if m[0] == domain.key])
        x, y = emb[idx], np.array([meta[i][3] for i in idx], dtype=np.float64)
        tpl = np.array([meta[i][2] for i in idx])
        ids = [meta[i][1] for i in idx]

        # random split, 5-fold
        rng = np.random.default_rng(0)
        order = rng.permutation(len(idx))
        p_rand = np.zeros(len(idx))
        for f in range(5):
            te = order[f::5]
            tr = np.setdiff1d(order, te)
            p_rand[te] = predict(fit_tuned(x[tr], y[tr]), x[te])

        # leave-one-template-out
        p_tpl = np.zeros(len(idx))
        for t in np.unique(tpl):
            te = np.where(tpl == t)[0]
            tr = np.where(tpl != t)[0]
            p_tpl[te] = predict(fit_tuned(x[tr], y[tr]), x[te])

        acc_r = 100 * np.mean((p_rand >= 0.5) == (y == 1))
        acc_t = 100 * np.mean((p_tpl >= 0.5) == (y == 1))
        print(f"  {domain.key:15} {acc_r:>13.1f}% {acc_t:>13.1f}%")
        results[domain.key] = {
            cid: {"random": float(a), "unseen": float(b)}
            for cid, a, b in zip(ids, p_rand, p_tpl, strict=True)
        }

    dest = pathlib.Path(__file__).parent / "jev_learned_results.json"
    dest.write_text(json.dumps(results, indent=1, sort_keys=True))
    print(f"\n-> {dest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
