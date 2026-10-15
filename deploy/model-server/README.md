# Model server

AgentFox's model-backed detectors (the injection classifier and its backstop,
embedding similarity, NLI grounding, Granite Guardian, Llama Guard) need weights, RAM
and, for the guard LLMs, ideally a GPU. A gateway that cannot hold those, such as a
serverless one, can send them here instead:

```
gateway (any host, deploys as often as you like)
   │  HTTPS + bearer token
   ▼
model server (one machine with the weights; changes only when the models do)
```

The gateway runs every model-backed detector through this server, and everything
else in-process. Budgets, degraded reporting and advisory hits work exactly as they
do in-process. A server that is down shows in `agentfox doctor` and the startup log
with its URL. The detectors that need it are then skipped, never silently passed.

## Run it on EC2 (CPU)

The classifier and backstop take about 1.5–2 GB of RAM and 25–50 ms per short prompt
on CPU.

- **Instance:** c7g.large (Graviton, arm64) or c7i.large / c6i.large (x86), each
  2 vCPU and 4 GB. The image is published for both architectures. Avoid burstable
  `t3`/`t4g`: once CPU credits run out, inference slows and requests start timing out.
- **Disk:** at least 30 GB. The image is about 6 GB with its weights.
- **Region:** the same region as the gateway. Vercel's default `iad1` is AWS
  `us-east-1`. Each hop across regions adds tens of milliseconds to a 300 ms budget.
- **Security group:** inbound 443 and 80 (Let's Encrypt), and SSH from your address
  only. 8090 is never exposed.

Then, on the instance:

```bash
# Docker and the compose plugin: https://docs.docker.com/engine/install/
# (Amazon Linux 2023: sudo dnf install -y docker && sudo systemctl enable --now docker)
sudo usermod -aG docker $USER && newgrp docker   # run docker without sudo
git clone https://github.com/architsharm/agentfox && cd agentfox/deploy/model-server
cp .env.example .env    # set MODEL_SERVER_DOMAIN and AGENTFOX_MODEL_SERVER_TOKEN
docker compose pull && docker compose up -d
docker compose logs -f models   # ready once each model logs "warm in …"
curl -H "Authorization: Bearer $TOKEN" https://$MODEL_SERVER_DOMAIN/health
```

Generate the token on the machine and paste it only into `.env` and the gateway's
settings. Not into chat, tickets or shell history you share.

`/health` lists each detector, whether it can run, and the device it runs on.

Then point the gateway at it. On Vercel, these are project environment variables:

```
AGENTFOX_MODEL_SERVER_URL=https://models.example.com
AGENTFOX_MODEL_SERVER_TOKEN=<the same token>
```

Check from the gateway side with `agentfox doctor`. The `detectors` line should list
`injection.classifier` as running.

## Updating

This machine changes only when the models or their detector code change, not on
every gateway deploy:

```bash
docker compose pull && docker compose up -d
```

`.env` starts on `:edge`, which is main. Once it works, pin what you tested so a pull
is always a decision: a commit (`:sha-1a2b3c4`, one is published for every push to
main) or a release (`:0.5.0`). Avoid `:latest`: it moves only on releases. Mismatched versions are tolerated: the gateway sends
a detector name and text, and reads back detections.

## GPU

The guard LLMs are where a GPU pays:

- Granite Guardian takes about 8 s per pass on CPU.
- Llama Guard is 8B parameters.

The published image's torch is CPU-only, so build a CUDA one on the GPU machine:

```bash
docker build -f deploy/Dockerfile \
  --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 \
  -t agentfox-models:cuda .
cd deploy/model-server
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

This needs the NVIDIA driver and `nvidia-container-toolkit` on the host (the AWS
Deep Learning AMIs have both). `/health` should then report `"device": "cuda"`.

Enable the guard detectors on the gateway as usual (`AGENTFOX_ENABLED_DETECTORS`).
Llama Guard also needs `AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1` on the model
server, and its weights built in with a Hugging Face token (see `deploy/Dockerfile`).

## Self-hosted LLMs for the judgment tiers

The `llm` / `local_llm` judgment tiers do not use this server. They call a chat
model through the provider interface, so any OpenAI-compatible server works: vLLM,
TGI, Ollama, or LiteLLM in front of them.

```
AGENTFOX_JUDGMENT_TIERS=["deterministic","local_llm"]
AGENTFOX_JUDGMENT_LLM_PROVIDER=litellm
AGENTFOX_LITELLM_BASE_URL=https://llm.internal.example.com
AGENTFOX_JUDGMENT_LLM_MODEL=<model name the server exposes>
AGENTFOX_TRUSTED_MODEL_HOSTS=["llm.internal.example.com"]
```

`AGENTFOX_TRUSTED_MODEL_HOSTS` matters here. A judgment call to a host not listed in
it is treated as third-party egress, so it is redacted or refused under the egress
settings. Listing a machine you run marks it as part of this deployment. Use exact
host names, and list only machines you control.
