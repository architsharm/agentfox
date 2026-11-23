# OpenClaw with the AgentFox plugin built in, for hosts that cannot mount files: the
# Render blueprint (deploy/openclaw/render.yaml) builds this. Locally, compose.yml mounts
# the same plugin and openclaw.json into the stock image instead.
#
#   docker build -f deploy/openclaw/Dockerfile .      # from the repository root
ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest

FROM node:22-alpine AS plugin
WORKDIR /plugin
COPY sdk/openclaw/package.json sdk/openclaw/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY sdk/openclaw/ ./
RUN npm run build
# Render hands over the gateway's address as host:port, and OpenClaw's ${VAR}
# substitution has no defaults or prefixes, so the scheme is written in here.
COPY deploy/openclaw/openclaw.json /config/openclaw.json
RUN sed -i 's#${AGENTFOX_URL}#http://${AGENTFOX_HOSTPORT}#g' /config/openclaw.json \
 && grep -qF 'http://${AGENTFOX_HOSTPORT}/v1' /config/openclaw.json

FROM ${OPENCLAW_IMAGE}
COPY --from=plugin /plugin/package.json /plugin/openclaw.plugin.json /opt/agentfox-openclaw/
COPY --from=plugin /plugin/dist /opt/agentfox-openclaw/dist
COPY --from=plugin --chown=node:node /config /opt/openclaw-config
ENV OPENCLAW_CONFIG_PATH=/opt/openclaw-config/openclaw.json
# Same command as compose.yml, kept as a plain gateway invocation: the image's
# entrypoint only runs its state repair for that form, not for a shell wrapper.
CMD ["node", "dist/index.js", "gateway", "--bind", "lan", "--port", "18789"]
