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
        <code>NOMETRIA_ALLOW_EGRESS=false</code> and the <code>echo</code> provider, so
        it runs end to end with no model and no API key. Point it at a model when you
        want one.
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
        and tracked at <code>:edge</code> on <code>main</code>.{" "}
        <code>docker compose build</code> builds from source instead. That takes a
        while: the gateway image pre-fetches 1–2GB of detector weights so the running
        container never needs network access for them.
      </p>
      <p>
        <code>deploy/docker-compose.yml</code> is commented line by line, including the
        values you must change before a real deployment.{" "}
        <code>NOMETRIA_AUDIT_SIGNING_KEY</code> above all: the audit chain is only as
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
        Set <code>NOMETRIA_DATABASE_URL</code> for Postgres. <code>agentfox admin db upgrade</code>{" "}
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
