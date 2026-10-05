import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Self-hosting",
  description: "Render, Docker Compose, or the gateway as a Python app.",
  path: "/docs/self-host",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Self-hosting</h1>
      <p>
        Everything runs on your own infrastructure. There is no licence check, no
        phone-home, and no default egress. A fresh install ships with{" "}
        <code>AGENTFOX_ALLOW_EGRESS=false</code> and the <code>echo</code> provider, so
        it runs end to end with no model and no API key. Point it at a model when you
        want one.
      </p>
      <p>
        Settings are environment variables named <code>AGENTFOX_*</code>. The
        pre-rename <code>NOMETRIA_*</code> names still work, so an existing deployment
        does not need to change; where both are set, <code>AGENTFOX_*</code> wins. The
        dashboard container is the exception and reads only its{" "}
        <code>NOMETRIA_*</code> names, such as <code>NOMETRIA_API_URL</code>.
      </p>

      <h2>Docker Compose</h2>
      <p>The whole stack, including OPA, on one machine. It pulls prebuilt images.</p>
      <pre>
        <code>{`git clone https://github.com/architsharm/agentfox.git && cd agentfox
docker compose -f deploy/docker-compose.yml up -d`}</code>
      </pre>
      <p>
        The dashboard is on port 3000 and the gateway on 8080. Images are{" "}
        <code>ghcr.io/architsharm/agentfox/gateway</code> and{" "}
        <code>ghcr.io/architsharm/agentfox/dashboard</code>, published on every release
        and tracked at <code>:edge</code> on <code>main</code>. Compose pulls{" "}
        <code>:latest</code>, which moves on each release tag.{" "}
        <code>docker compose build</code> builds from source instead. That takes a
        while: the gateway image pre-fetches 1–2GB of permissive-licence detector
        weights so the running container never needs network access for them. The
        licence-gated Llama Guard tier is off by default and never in the published
        image; the compose file&apos;s header has the opt-in steps.
      </p>
      <p>
        <code>deploy/docker-compose.yml</code> is commented line by line, including the
        values you must change before a real deployment.{" "}
        <code>AGENTFOX_AUDIT_SIGNING_KEY</code> above all: the audit chain is only as
        trustworthy as the key that signs it.
      </p>

      <h2>Python, no containers</h2>
      <p>The gateway is an ordinary ASGI app. SQLite is the default.</p>
      <pre>
        <code>{`pip install "agentfox[postgres] @ git+https://github.com/architsharm/agentfox.git"
agentfox init
uvicorn agentfox.gateway.app:app --host 0.0.0.0 --port 8080`}</code>
      </pre>
      <p>
        Set <code>AGENTFOX_DATABASE_URL</code> for Postgres. <code>agentfox admin db upgrade</code>{" "}
        applies migrations.
      </p>

      <h2>Render</h2>
      <p>
        The blueprint in <code>render.yaml</code> provisions Postgres, the gateway, and
        the dashboard. The gateway needs Render&apos;s <code>starter</code> instance
        type rather than <code>free</code>, because the image carries the classifier
        extra. The database and the dashboard run on free.
      </p>

      <h2>After any of them</h2>
      <p>
        Create a GitHub OAuth app and set its callback to{" "}
        <code>https://&lt;your-host&gt;/api/auth/github/callback</code>. The dashboard
        runbook is <code>deploy/README-dashboard.md</code> in the repository. A Fly.io
        config is <code>deploy/fly.dashboard.toml</code>.
      </p>
      <p>
        Model-backed detectors do not download weights while handling a request. A
        detector whose weights are absent reports itself unavailable. Fetch them on
        purpose, then confirm with <code>agentfox doctor</code>:
      </p>
      <pre>
        <code>python -m spacy download en_core_web_lg</code>
      </pre>
      <p>
        That one is for <code>pii.presidio</code>, about 400MB. Granite Guardian, the
        injection classifier, and the embedding detector pull their weights from
        Hugging Face the same way. <code>doctor</code> lists which are present.
      </p>
      <p>
        Connecting an agent to a running gateway is on{" "}
        <Link href="/docs/connect">Where it connects</Link>.
      </p>
    </article>
  );
}
