# Deploying the control-plane UI on Fly.io

The same single web service as [`render.yaml`](render.yaml), from the same image, on Fly.
The UI is a pure client of the API, so there is no database here. Everything around this
deploy (the shared secrets, the GitHub OAuth app, the playground's allowed origins) is
the same as for Render and is described in [`README-dashboard.md`](README-dashboard.md).
This page covers only what is specific to Fly.

The config is [`fly.dashboard.toml`](fly.dashboard.toml). It is not at the repository
root, and the image builds from `./dashboard`, so the commands below pass both paths
explicitly.

> We have not run this deploy on a live Fly account. The image build and the server's
> start-up were checked locally with Docker. Check Fly's current pricing for what a
> machine with `min_machines_running = 1` costs.

## 0. Before you start

- Install `flyctl` (`curl -L https://fly.io/install.sh | sh`) and sign in: `fly auth login`.
- Have the API deployed and its `AGENTFOX_SERVICE_AUTH_SECRET` to hand (step 1 of
  [`README-dashboard.md`](README-dashboard.md)).
- Have a GitHub OAuth app (step 3 there). You fix its callback URL after the deploy,
  once Fly has given you a hostname.

## 1. Create the app without deploying it

From the repository root:

```bash
fly launch --no-deploy --copy-config --config deploy/fly.dashboard.toml --name <your-app-name>
```

App names are global on Fly, so `nometria-dashboard` in the config is probably taken.
Pick your own with `--name`, and make sure `app =` in the config says the same, since the
later commands read the app name from there. `--copy-config` keeps the settings in the
file instead of generating new ones.

Check the `[env]` block before the first deploy:

| Variable | Value |
|---|---|
| `AGENTFOX_API_URL` | The API this UI drives, with no trailing slash. The default points at the hosted API. |
| `HOSTNAME` | `0.0.0.0`. Leave it as it is: see the note under step 3. |
| `PORT` | `3000`, matching `internal_port`. |

## 2. Set the secrets

Three values, none of which belong in the config file:

| Secret | Where it comes from |
|---|---|
| `GITHUB_CLIENT_ID` | The GitHub OAuth app: Settings → Developer settings → OAuth Apps. |
| `GITHUB_CLIENT_SECRET` | The same app: *Generate a new client secret*. |
| `AGENTFOX_SERVICE_AUTH_SECRET` | Must be byte-identical to the API's value. It authenticates the one privileged call that provisions a new account, so a mismatch makes sign-in fail at the provisioning step. |

```bash
fly secrets set --stage --config deploy/fly.dashboard.toml \
  GITHUB_CLIENT_ID=... GITHUB_CLIENT_SECRET=... AGENTFOX_SERVICE_AUTH_SECRET=...
```

`--stage` stores them without starting a deploy: there is no image yet, and the first
deploy in step 3 picks them up.

## 3. Deploy

From the repository root:

```bash
fly deploy ./dashboard \
  --config "$PWD/deploy/fly.dashboard.toml" \
  --dockerfile "$PWD/deploy/Dockerfile.dashboard"
```

The first argument is the build context. `Dockerfile.dashboard` copies `package.json` and
the app from the directory it is built in, so that directory must be `./dashboard`: built
from the repository root, it finds no `package.json`. The config and Dockerfile are given
as absolute paths so they do not depend on how `flyctl` resolves a relative path once a
working directory is set.

**Why `HOSTNAME=0.0.0.0`.** Next's standalone server listens on `$HOSTNAME`. A platform
that sets `HOSTNAME` to the machine's name makes the server listen only on whatever that
name resolves to, which need not be the address the platform's proxy connects to. On Render
this meant every request returned 502 while the logs showed a clean start. Setting it to
`0.0.0.0` makes the server listen on every interface, whatever the platform puts there.

The health check requests `/login`, the only page that renders without a session cookie:
`/` redirects, and every other path redirects to `/login`.

When the deploy finishes, `fly status --config deploy/fly.dashboard.toml` shows the
hostname: `https://<your-app-name>.fly.dev`.

## 4. After the first deploy

These are the same steps as for Render, with the Fly hostname:

1. **GitHub OAuth app:** set the authorization callback URL to
   `https://<your-app-name>.fly.dev/api/auth/github/callback`. It must match exactly,
   scheme and path included. A mismatch is the most common cause of a failed sign-in
   ([step 3](README-dashboard.md#3-point-github-at-the-new-hostname)).
2. **The playground:** add `https://<your-app-name>.fly.dev` to the API's
   `AGENTFOX_PLAYGROUND_CORS_ORIGIN`, then redeploy the API. The value is
   comma-separated: append to it, never replace it, or another host's playground stops
   working ([step 4](README-dashboard.md#4-let-the-browser-reach-the-playground)).
3. **Verify:** `curl -s -o /dev/null -w "%{http_code}\n" https://<your-app-name>.fly.dev/login`
   should print `200`. Then sign in from a private window
   ([step 5](README-dashboard.md#5-verify-the-whole-path)).

## Machines

The config keeps one machine running (`min_machines_running = 1`), so the first visitor
does not wait for a cold start. Fly suspends any extra machines when they are idle
(`auto_stop_machines = "suspend"`) and starts them on demand. Set the minimum to `0` to pay
nothing while idle, at the cost of a slow first request.
