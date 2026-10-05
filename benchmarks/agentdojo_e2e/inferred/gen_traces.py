"""Generate executed AgentDojo ground-truth traces WITH real tool outputs (no LLM).

Run with an isolated agentdojo install (it has its own dependency tree):
    uv venv /tmp/agentdojo_venv && uv pip install --python /tmp/agentdojo_venv/bin/python agentdojo==0.1.35
    /tmp/agentdojo_venv/bin/python benchmarks/agentdojo_e2e/inferred/gen_traces.py v1.2.2 > traces_v1.2.2.json

For every user task we record two kinds of trace:

* benign:  the user task's ground-truth calls executed in the default environment,
           each with the tool output the agent would actually read.
* attack:  for every (user task, injection task) pair, the environment is seeded with
           the `important_instructions` attack text at every injection vector the user
           task's ground truth actually reads (AgentDojo's own `get_injection_candidates`
           logic, reproduced here with canaries). The user task's ground-truth calls are
           executed (their outputs now contain the injection), followed by the injection
           task's ground-truth calls -- i.e. the trace of a *fully compromised* agent.

Nothing about provenance is labelled here. The replay side must infer it from content.
"""

from __future__ import annotations

import json
import sys

from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.attacks.base_attacks import DEFAULT_MODEL_NAME
from agentdojo.attacks.important_instructions_attacks import ImportantInstructionsAttack
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suites
from agentdojo.types import get_text_content_as_str

JB = ImportantInstructionsAttack._JB_STRING
USER_NAME = "Emma Johnson"


def run_calls(suite, env, calls):
    runtime = FunctionsRuntime(suite.tools)
    out = []
    for call in calls:
        result, error = runtime.run_function(env, call.function, call.args, raise_on_error=False)
        from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
        from agentdojo.functions_runtime import FunctionReturnType  # noqa: F401

        text = tool_result_to_str(result) if error is None else f"ERROR: {error}"
        out.append(
            {
                "function": call.function,
                "args": json.loads(json.dumps(call.args, default=str)),
                "output": text,
            }
        )
    return out


def injection_candidates(suite, user_task):
    canaries = {inj: f"<CANARY---{inj}--->" for inj in suite.get_injection_vector_defaults()}
    env = suite.load_and_inject_default_environment(canaries)
    env = user_task.init_environment(env)
    gt = GroundTruthPipeline(user_task)
    _, _, _, responses, _ = gt.query(user_task.PROMPT, FunctionsRuntime(suite.tools), env)
    found = []
    for inj, canary in canaries.items():
        if any(
            r["content"] is not None and canary in get_text_content_as_str(r["content"])
            for r in responses
        ):
            found.append(inj)
    return found


def main(version: str) -> None:
    suites = get_suites(version)
    out = {"version": version, "benign": [], "attack": []}
    for suite_name, suite in suites.items():
        for ut_id, ut in suite.user_tasks.items():
            env = ut.init_environment(suite.load_and_inject_default_environment({}))
            out["benign"].append(
                {
                    "suite": suite_name,
                    "user_task": ut_id,
                    "prompt": ut.PROMPT,
                    "calls": run_calls(suite, env, ut.ground_truth(env)),
                }
            )
            cands = injection_candidates(suite, ut)
            for it_id, it in suite.injection_tasks.items():
                text = JB.format(
                    goal=it.GOAL, user=USER_NAME, model=DEFAULT_MODEL_NAME, task=ut.PROMPT
                )
                env = suite.load_and_inject_default_environment({c: text for c in cands})
                env = ut.init_environment(env)
                user_calls = run_calls(suite, env, ut.ground_truth(env))
                inj_calls = run_calls(suite, env, it.ground_truth(env))
                out["attack"].append(
                    {
                        "suite": suite_name,
                        "user_task": ut_id,
                        "injection_task": it_id,
                        "prompt": ut.PROMPT,
                        "goal": it.GOAL,
                        "vectors": cands,
                        "injection_text": text,
                        "user_calls": user_calls,
                        "injection_calls": inj_calls,
                        "injection_seen": any(text.strip()[:40] in c["output"] for c in user_calls),
                    }
                )
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v1.2.2")
