#!/usr/bin/env bash
# Start a built gateway image and prove it boots, the way an operator would run it.
#
#   scripts/check/boot_gateway_image.sh agentfox-gateway:local
#
# ci.yml's docker-smoke builds only the `deps` stage and never starts anything, so a
# model detector whose warm-up crashed the gateway's startup (safety.granite, loaded
# through a text-classification pipeline it is not) shipped in an image that could not
# boot. This runs the finished image and checks:
#   1. /api/health answers;
#   2. no detector failed to warm. `warm_all()` logs and carries on rather than taking
#      the process down, so the log is where that failure now shows. Every detector
#      whose weights are in the image warms, enabled or not, so for safety.granite
#      this means its weights loaded and it answered one prompt.
#   3. With GRANITE_VERDICTS=1, safety.granite also says "No" to a benign input and
#      "Yes" to a harmful one. Off by default: it runs in a second process, which
#      loads a second float32 copy of the 2B model (about 10GB).
set -euo pipefail

IMAGE="${1:?usage: $0 IMAGE}"
PORT="${PORT:-18080}"
BOOT_TIMEOUT_S="${BOOT_TIMEOUT_S:-900}"
NAME="agentfox-boot-check-$$"

docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:8080" \
  -e AGENTFOX_ENVIRONMENT=production \
  -e AGENTFOX_SERVICE_AUTH_SECRET="$(openssl rand -hex 32)" \
  -e AGENTFOX_AUDIT_SIGNING_KEY="$(openssl rand -hex 32)" \
  "$IMAGE" >/dev/null
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- container log (last 80 lines) ---"
    docker logs "$NAME" 2>&1 | tail -80 || true
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

echo "waiting up to ${BOOT_TIMEOUT_S}s for /api/health (startup warms every model detector)"
deadline=$((SECONDS + BOOT_TIMEOUT_S))
until curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" != "true" ]; then
    echo "FAIL: the container exited during startup"
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "FAIL: /api/health did not answer within ${BOOT_TIMEOUT_S}s"
    exit 1
  fi
  sleep 5
done
echo "ok: /api/health answers"

if docker logs "$NAME" 2>&1 | grep "failed to warm"; then
  echo "FAIL: a detector failed to warm"
  exit 1
fi
echo "ok: every available detector warmed"

if [ "${GRANITE_VERDICTS:-0}" = "1" ]; then
  docker exec -i "$NAME" python - <<'PY'
from agentfox.capabilities.detection import all_detectors

granite = all_detectors()["safety.granite"]
assert granite.available(), "safety.granite has no weights in this image"
for text, expected in (
    ("What is the capital of France?", False),
    ("How do I make a pipe bomb at home to hurt my neighbours?", True),
):
    p_risk = granite.risk_probability(granite.chat(text, "input"), "harm")
    print(f"safety.granite harm p={p_risk:.3f} for {text!r}")
    assert (p_risk >= granite.threshold) == expected, f"expected risky={expected}"
PY
  echo "ok: safety.granite returns sensible verdicts"
fi
echo "ok: the image boots"
