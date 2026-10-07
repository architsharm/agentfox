# customer-support

The support desk: its tools with their declared impact (a ticket update that fires the
helpdesk's notification mail declares the `email.send` it triggers), the triage agent
and its least-privilege grants (`fixtures/world.yaml`, part of the demo world), and
golden cases for the containment the desk relies on.

**Risk.** An attachment or a help article steers the agent into emailing a customer
record out, or into rewriting tickets with text it read elsewhere.

```bash
agentfox policy packs test customer-support
```
