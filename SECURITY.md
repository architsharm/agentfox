# Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's private reporting instead: the **Security** tab of this repository, then
**Report a vulnerability**. That creates a private advisory only the maintainers can see,
and it is the fastest route to a fix.

Tell us what you did, what happened, and what you expected. A failing request, a policy
file, or a short script is worth more than a description.

## What is in scope

This project's own code: the enforcement path, the policy engine, the audit chain and its
verifier, the gateway and its authentication, the tenant isolation in `src/agentfox/core/tenancy.py`,
and the public playground at the hosted demo.

Two things are explicitly **not** vulnerabilities, because the project already says so in
public and measures them:

- **A prompt injection that a detector misses.** Detection is a speed bump here, not a
  defence. Held-out injection recall is published in the README, and an adaptive attacker
  gets most caught attacks through eventually. That is the documented starting point.
- **An attack that gets through when the declarations are wrong.** Containment is only as
  good as the tool declarations and capability grants behind it. A tool declared read-only
  that moves money is not contained, and the product says so.

What *is* a vulnerability: getting an action through that the declarations should have
refused, reading or writing another tenant's data, forging or breaking the audit chain
without the verifier noticing, escalating a token's permissions, or making the control
plane fail open without recording it.

## What to expect

We aim to acknowledge a report within a few working days. This is a small project, so
please be patient with a fix timeline, and tell us if you plan to publish.
