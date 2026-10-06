# syntax=docker/dockerfile:1.7
# AgentFox control plane — gateway + API.
#
# All four permissive-licence classifier/embedding models (Granite Guardian, PIGuard,
# the protectai ensemble backstop, and the embedding-similarity detector — all
# Apache-2.0/MIT) are baked in and pre-fetched at build time below. The
# licence-gated Llama Guard 3-8B tier is baked in only when a token is supplied, and
# never in the published image (Appendix A.4: non-OSI licence, acceptable-use
# policy, >700M-MAU clause — legal review required before commercial deployment,
# which is why it stays behind AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1 at runtime
# and behind an explicit build secret here, never a plain ENV, so the token can't leak
# into an image layer or `docker history`).
#
# This makes the image materially bigger (~1-2GB of model weights) and the build
# requires network egress. A Hugging Face token that has accepted Meta's Llama
# licence is needed only for the optional Llama Guard tier; the opt-in steps are in
# deploy/docker-compose.yml's header.
# The running container itself still makes no outbound calls for any of this: weights
# are read from the image, never fetched at request time (NFR-4/NFR-9).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/var/agentfox/hf-cache

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq5 \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
# alembic.ini and migrations/ are force-included into the wheel (see
# pyproject.toml), so the build fails outright without them — "Forced include
# not found: /app/alembic.ini". They also have to be here on their own merit:
# this image's own CMD comment sends schema upgrades through `agentfox admin db
# upgrade`, and until the wheel carried the migration scripts that command
# could not run inside the container at all.
#
# Before `src`, deliberately: migrations change far less often, so the install
# layer stays cached across ordinary source edits.
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

# `postgres`/`otel` for the compose stack, `classifiers` (transformers + torch) for
# every model-based detector below.
RUN pip install --upgrade pip && pip install ".[postgres,otel,classifiers]"

# CI builds and stops here (`docker build --target deps`, no secret, no GPU-scale
# download) — enough to catch what actually broke production once already (finding
# 1.1, docs/design/production-readiness-review.md §1.1: COPY paths pointing at directories that
# don't exist in the repo). A real smoke test, not just Dockerfile syntax: this stage
# fails the same way an operator's build would if `src ./src` or the extras install
# ever stopped matching what the app needs to import.
FROM base AS deps
RUN python -c "from nometria.gateway.app import create_app; create_app(); print('image smoke: OK')"

FROM deps AS weights
RUN mkdir -p /var/agentfox/hf-cache

# Permissive tier — Apache-2.0/MIT, no licence gate, no secret needed.
#
# granite-guardian-3.0-2b declares architectures: ["GraniteForCausalLM"], so
# AutoModelForSequenceClassification raises "Unrecognized configuration class
# GraniteConfig for this kind of AutoModel" and takes the whole layer with it. The
# other three genuinely are sequence-classification or embedding models.
#
# This had never built. ci.yml's docker-smoke targets `deps`, one stage earlier, so
# nothing in CI ever reached this line — it surfaced the first time a workflow tried
# to publish the finished image.
RUN python -c "\
from transformers import AutoModelForSequenceClassification, AutoModelForCausalLM, AutoTokenizer, AutoModel; \
AutoTokenizer.from_pretrained('ibm-granite/granite-guardian-3.0-2b'); \
AutoModelForCausalLM.from_pretrained('ibm-granite/granite-guardian-3.0-2b'); \
AutoTokenizer.from_pretrained('leolee99/PIGuard', trust_remote_code=True); \
AutoModelForSequenceClassification.from_pretrained('leolee99/PIGuard', trust_remote_code=True); \
AutoTokenizer.from_pretrained('protectai/deberta-v3-base-prompt-injection-v2'); \
AutoModelForSequenceClassification.from_pretrained('protectai/deberta-v3-base-prompt-injection-v2'); \
AutoTokenizer.from_pretrained('sentence-transformers/all-MiniLM-L6-v2'); \
AutoModel.from_pretrained('sentence-transformers/all-MiniLM-L6-v2'); \
print('permissive-tier weights cached')"

# Restricted tier — meta-llama/Llama-Guard-3-8B is a *gated* HF repo: this only
# succeeds once the account behind the token has clicked "accept" on Meta's licence
# for this model at https://huggingface.co/meta-llama/Llama-Guard-3-8B. The secret is
# mounted only for this one step (least privilege) and is never written to a layer —
# BuildKit secret mounts don't persist in the final image or `docker history`.
# Build with: DOCKER_BUILDKIT=1 docker build --secret id=hf_token,env=HF_TOKEN ...
# (docker compose: see deploy/docker-compose.yml's `secrets:` block).
# Skipped, not failed, when no token is mounted. Two reasons. A build without a
# token is the normal case — anyone building this image who has not accepted Meta's
# licence, including the public image workflow, which must never bake gated weights
# into something we publish. And an empty secret does not fail cleanly: huggingface_hub
# sends `Authorization: Bearer ` and httpx rejects it as an illegal header value,
# so the build died on a confusing protocol error rather than a missing credential.
# `safety.restricted` then loads its weights at runtime, or stays unavailable.
RUN --mount=type=secret,id=hf_token \
    sh -eu -c 'HF_TOKEN="$(cat /run/secrets/hf_token 2>/dev/null || true)"; \
    if [ -z "$HF_TOKEN" ]; then \
      echo "no hf_token mounted - skipping the licence-gated restricted tier"; \
      exit 0; \
    fi; \
    export HF_TOKEN; \
    python -c "import os; from huggingface_hub import login; login(token=os.environ[\"HF_TOKEN\"]); from transformers import AutoModelForCausalLM, AutoTokenizer; AutoTokenizer.from_pretrained(\"meta-llama/Llama-Guard-3-8B\"); AutoModelForCausalLM.from_pretrained(\"meta-llama/Llama-Guard-3-8B\"); print(\"restricted-tier weights cached\")"'

# /var/agentfox/evidence is where deploy/docker-compose.yml and render.yaml point
# AGENTFOX_EVIDENCE_DIR, so it has to exist and belong to the runtime user.
RUN useradd --create-home --uid 10001 agentfox \
 && mkdir -p /var/agentfox/evidence \
 && chown -R agentfox:agentfox /var/agentfox /app
USER agentfox

EXPOSE 8080

# Serve, and nothing else. This used to run `agentfox admin seed` on every boot "so the stack
# is demonstrable immediately", which wrote demo agents, policies, users and traffic
# into whatever database the container was pointed at — production included, on every
# restart. The schema is created on startup (`init_db`); schema *upgrades* on an
# existing database go through `agentfox admin db upgrade` (Alembic).
#
# The first operator, with no demo data:
#   docker compose exec gateway agentfox admin users create you@example.com --role owner --token
# Demo data, deliberately and only where you want it:
#   docker compose exec gateway agentfox admin seed
#
# The app refuses to start outside AGENTFOX_ENVIRONMENT=development while
# AGENTFOX_SERVICE_AUTH_SECRET or AGENTFOX_AUDIT_SIGNING_KEY is unset or a published
# placeholder: both are in this repository, so neither would be a secret.
CMD ["uvicorn", "agentfox.apps.gateway.app:app", "--host", "0.0.0.0", "--port", "8080"]
