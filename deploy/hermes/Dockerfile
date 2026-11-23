# Hermes Agent with the AgentFox plugin's one dependency (the agentfox Python package).
#
# Built from PyPI rather than on the official nousresearch/hermes-agent image: that
# image's Python environment is sealed, and Hermes installs a plugin's dependencies only
# for catalog and Git installs. This pair is the combination the kit was tested with.
FROM python:3.12-slim

ARG HERMES_VERSION=0.19.0
ARG AGENTFOX_VERSION=0.5.4

RUN apt-get update && apt-get install -y --no-install-recommends git procps curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "hermes-agent==${HERMES_VERSION}" "agentfox==${AGENTFOX_VERSION}" \
    && useradd --create-home --uid 10000 hermes \
    # Created here so the compose volumes start out owned by hermes, not root.
    && install -d -o hermes -g hermes /home/hermes/.hermes/plugins /home/hermes/work

USER hermes
WORKDIR /home/hermes/work
ENV HERMES_HOME=/home/hermes/.hermes
ENTRYPOINT ["hermes"]
