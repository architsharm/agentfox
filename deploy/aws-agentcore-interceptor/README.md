# AgentFox interceptor for Amazon Bedrock AgentCore Gateway

An AgentCore Gateway can run a Lambda on every MCP request before it reaches a target.
This one sends each `tools/call` to AgentFox (`POST /v1/guard/tool_call`) as a call of
one agent. A blocked or held call is answered by the gateway and never reaches the
target; an allowed call passes through unchanged.

## Deploy

1. In AgentFox, register the agent and issue it a key (the agent's Identity page, or
   `POST /api/identities/{id}/credentials`). Store the key in Secrets Manager as a
   plain-text secret.
2. Deploy the function:

   ```bash
   sam deploy --guided \
     --parameter-overrides AgentFoxUrl=https://api.example.com AgentFoxAgent=claims-agent \
       AgentFoxKeySecretName=agentfox/claims-agent
   ```

3. Attach it to the gateway as the REQUEST interceptor:

   ```yaml
   InterceptorConfigurations:
     - Interceptor: { Lambda: { Arn: <InterceptorArn output> } }
       InterceptionPoints: [REQUEST]
       InputConfiguration: { PassRequestHeaders: true }
   ```

   or `aws bedrock-agentcore-control update-gateway ... --interceptor-configurations`.
   Give the gateway's role `lambda:InvokeFunction` on the function.

`PassRequestHeaders: true` lets the interceptor read `Mcp-Session-Id`, so calls in one
MCP session are grouped as one session in AgentFox. It also passes the client's
`Authorization` header to the Lambda, which this function never logs or forwards.

## What the agent sees

- **Blocked:** by default the gateway answers with status 403 and a JSON-RPC error
  ("This action was not done: it is not allowed by this organisation's policy").
  `BlockStyle=tool_error` returns a tool result with `isError: true` instead, which
  the model reads like any tool output and can explain to the user. AWS documents the
  403 shape only through community examples; check it against your client.
- **Held for approval:** refused the same way, naming the approval id. The gateway
  cannot wait for a person, so the agent retries after approval.
- **Undecided** (AgentFox unreachable or slower than `AGENTFOX_TIMEOUT_S`): refused
  with `FailMode=closed` (the default), allowed with `FailMode=open`.

Tool names reach AgentFox without the gateway's `<target>___` prefix, so a policy
names the tool as the target defines it.
