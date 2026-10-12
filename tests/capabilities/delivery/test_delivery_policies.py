"""Delivery policies: each family fires on the failure it targets and stays silent elsewhere.

The silent cases matter as much as the firing ones. A policy that intervenes on a
task it was not written for costs a turn at best, and at worst talks a correct
agent out of a correct answer.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities import delivery
from agentfox.capabilities.delivery import Call, SessionState, Stop

SERVICE_TASK = (
    "Write a gRPC key-value server in server.py. The server should be running and "
    "listening on port 5328 when you are done."
)
RECOVERY_TASK = "The SQLite database at /data/app.db is corrupted. Recover as many rows as you can."
DEPLOY_TASK = "Set up a bare git repository with a post-receive hook that deploys to /var/www/html."
REPLACE_TASK = (
    "Replace every API key in the repo with the placeholder <REDACTED>. Do not modify "
    "anything else."
)
ENUM_TASK = "Find all winning moves for white in this position and write them one per line."
BAR_TASK = "Compress the program so the source is under 4 KB and still prints the same output."
PLAIN_TASK = "Fix the off-by-one error in utils.py and add a unit test for it."


def _session(task: str) -> SessionState:
    state = SessionState()
    delivery.on_task(state, task)
    return state


def shell(command: str, **kw) -> Call:
    return Call("shell", {"command": command, **kw})


def ran(state: SessionState, *calls: Call) -> None:
    """Each call as the hook sees it: checked before it runs, recorded after."""
    for call in calls:
        delivery.before_call(state, call)
        delivery.after_call(state, call)


# ---------------------------------------------------------------------------
# Eligibility: read the task once, name no task
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task, policy",
    [
        (SERVICE_TASK, "delivery.service_persistence"),
        (RECOVERY_TASK, "delivery.evidence_preservation"),
        (DEPLOY_TASK, "delivery.deployment_preservation"),
        (REPLACE_TASK, "delivery.exact_replacement"),
        (ENUM_TASK, "delivery.enumerate_all"),
        (BAR_TASK, "delivery.measured_acceptance"),
    ],
)
def test_each_family_is_eligible_on_its_own_task(task, policy):
    assert policy in _session(task).eligible


def test_an_ordinary_task_makes_nothing_eligible():
    assert _session(PLAIN_TASK).eligible == []


def test_an_ordinary_task_never_intervenes():
    state = _session(PLAIN_TASK)
    for cmd in ("sqlite3 app.db .dump", "git reset --hard", "python server.py"):
        assert delivery.before_call(state, shell(cmd)) is None
        delivery.after_call(state, shell(cmd))
    assert delivery.at_stop(state, Stop()) is None


# ---------------------------------------------------------------------------
# 1. Service persistence
# ---------------------------------------------------------------------------


def test_service_launched_in_session_and_probed_there_is_sent_back():
    state = _session(SERVICE_TASK)
    ran(state, shell("python3 server.py &"), shell("grpcurl -plaintext localhost:5328 list"))
    nudge = delivery.at_stop(state, Stop())
    assert nudge and nudge.rules == ("delivery.service_persistence",)
    assert "detached" in nudge.text


def test_a_harness_background_task_is_not_detached():
    state = _session(SERVICE_TASK)
    ran(
        state,
        shell("setsid python3 server.py", run_in_background=True),
        shell("curl localhost:5328"),
    )
    assert delivery.at_stop(state, Stop()) is not None


def test_detached_launch_then_a_later_probe_lets_the_agent_stop():
    state = _session(SERVICE_TASK)
    ran(
        state,
        shell("setsid nohup python3 server.py > /tmp/s.log 2>&1 < /dev/null &"),
        shell("curl -s localhost:5328"),
    )
    assert delivery.at_stop(state, Stop()) is None


def test_a_probe_chained_into_the_launch_does_not_count():
    state = _session(SERVICE_TASK)
    ran(state, shell("setsid nohup python3 server.py > l 2>&1 & sleep 1; curl localhost:5328"))
    assert delivery.at_stop(state, Stop()) is not None


def test_relaunching_attached_after_a_detached_launch_is_caught():
    state = _session(SERVICE_TASK)
    ran(
        state,
        shell("setsid nohup python3 server.py > l 2>&1 &"),
        shell("curl localhost:5328"),
        shell("python3 server.py"),
    )
    assert delivery.at_stop(state, Stop()) is not None


def test_service_nudge_fires_once():
    state = _session(SERVICE_TASK)
    ran(state, shell("python3 server.py &"))
    assert delivery.at_stop(state, Stop()) is not None
    assert delivery.at_stop(state, Stop(reentered=True)) is None


def test_a_probe_that_reached_the_background_task_is_not_trusted():
    """Seen live on macOS: `setsid` is missing, the relaunch failed into its log, and
    the probe passed against the background task that then died with the session."""
    state = _session(SERVICE_TASK)
    ran(state, shell("python3 -m http.server 8000", run_in_background=True))
    first = delivery.at_stop(state, Stop(background_tasks=("python3 -m http.server 8000",)))
    assert first and "disown" in first.text
    ran(
        state,
        shell("setsid nohup python3 -m http.server 8000 > l 2>&1 < /dev/null &"),
        shell("curl -s localhost:8000"),
    )
    still = Stop(reentered=True, background_tasks=("python3 -m http.server 8000",))
    second = delivery.at_stop(state, still)
    assert second and "still running" in second.text
    assert delivery.at_stop(state, still) is None  # and never a third time


def test_background_task_gone_and_detached_probe_passes():
    state = _session(SERVICE_TASK)
    ran(state, shell("python3 -m http.server 8000", run_in_background=True))
    assert delivery.at_stop(state, Stop(background_tasks=("bg",))) is not None
    ran(state, shell("nohup python3 -m http.server 8000 > l 2>&1 < /dev/null & disown"))
    ran(state, shell("curl -s localhost:8000"))
    assert delivery.at_stop(state, Stop(reentered=True)) is None


def test_no_launch_no_nudge():
    state = _session(SERVICE_TASK)
    ran(state, shell("pip install grpcio"))
    assert delivery.at_stop(state, Stop()) is None


# ---------------------------------------------------------------------------
# 2. Evidence preservation
# ---------------------------------------------------------------------------


def test_opening_the_only_copy_is_refused():
    state = _session(RECOVERY_TASK)
    nudge = delivery.before_call(state, shell("sqlite3 /data/app.db '.tables'"))
    assert nudge and nudge.action == "deny"
    assert nudge.rules == ("delivery.evidence_preservation",)


def test_python_connect_is_refused_too():
    state = _session(RECOVERY_TASK)
    cmd = "python3 -c \"import sqlite3; sqlite3.connect('/data/app.db').execute('select 1')\""
    assert delivery.before_call(state, shell(cmd)) is not None


def test_read_only_access_is_allowed():
    state = _session(RECOVERY_TASK)
    assert delivery.before_call(state, shell("sqlite3 -readonly /data/app.db .tables")) is None
    assert delivery.before_call(state, shell("xxd /data/app.db | head")) is None


def test_copying_only_the_main_file_is_not_enough_for_a_database():
    state = _session(RECOVERY_TASK)
    ran(state, shell("cp /data/app.db /tmp/app.db"))
    assert delivery.before_call(state, shell("sqlite3 /data/app.db .tables")) is not None


def test_a_copy_with_sidecars_unlocks_the_open():
    state = _session(RECOVERY_TASK)
    ran(state, shell("cp -a /data /tmp/evidence"))
    assert delivery.before_call(state, shell("sqlite3 /tmp/evidence/app.db .tables")) is None


def test_the_refusal_repeats_but_cannot_deadlock():
    state = _session(RECOVERY_TASK)
    cmd = shell("sqlite3 /data/app.db .tables")
    refusals = [delivery.before_call(state, cmd) for _ in range(5)]
    assert sum(r is not None for r in refusals) == 3


# ---------------------------------------------------------------------------
# 3. Deployment preservation
# ---------------------------------------------------------------------------


def test_cleanup_after_a_verified_deploy_is_refused():
    state = _session(DEPLOY_TASK)
    ran(state, shell("git push origin master"), shell("curl -s localhost:8080/hello.html"))
    nudge = delivery.before_call(state, shell("git reset --hard HEAD~1"))
    assert nudge and nudge.action == "deny"
    assert delivery.before_call(state, shell("rm -rf /var/www/html")) is not None


def test_cleanup_before_any_deploy_check_is_left_alone():
    state = _session(DEPLOY_TASK)
    assert delivery.before_call(state, shell("git reset --hard")) is None


def test_harmless_cleanup_after_deploy_is_left_alone():
    state = _session(DEPLOY_TASK)
    ran(state, shell("git push origin master"))
    assert delivery.before_call(state, shell("rm -rf /tmp/scratch")) is None


# ---------------------------------------------------------------------------
# 4. Exact replacement
# ---------------------------------------------------------------------------


def test_first_write_gets_the_allowlist_instruction_once():
    state = _session(REPLACE_TASK)
    write = Call("file.edit", {"file_path": "a.py"})
    first = delivery.before_call(state, write)
    assert first and first.action == "instruct"
    delivery.after_call(state, write)
    assert delivery.before_call(state, write) is None


def test_stop_without_a_diff_check_after_the_last_write():
    state = _session(REPLACE_TASK)
    ran(state, Call("file.edit", {"file_path": "a.py"}))
    nudge = delivery.at_stop(state, Stop())
    assert nudge and "credential" in nudge.text


def test_stop_after_a_diff_check_is_allowed():
    state = _session(REPLACE_TASK)
    ran(state, Call("file.edit", {"file_path": "a.py"}), shell("git diff --stat"))
    assert delivery.at_stop(state, Stop()) is None


def test_a_write_after_the_check_needs_another_check():
    state = _session(REPLACE_TASK)
    ran(
        state,
        Call("file.edit", {"file_path": "a.py"}),
        shell("git diff"),
        shell("sed -i 's/x/y/' b.py"),
    )
    assert delivery.at_stop(state, Stop()) is not None


# ---------------------------------------------------------------------------
# 5 and 6. Enumeration, measured bar
# ---------------------------------------------------------------------------


def test_enumeration_instructs_once():
    state = _session(ENUM_TASK)
    assert delivery.at_stop(state, Stop()) is not None
    assert delivery.at_stop(state, Stop()) is None


def test_bar_without_a_measurement_after_the_last_write():
    state = _session(BAR_TASK)
    ran(state, Call("file.write", {"file_path": "p.c"}))
    assert delivery.at_stop(state, Stop()) is not None


def test_bar_measured_after_the_last_write():
    state = _session(BAR_TASK)
    ran(state, Call("file.write", {"file_path": "p.c"}), shell("wc -c p.c"))
    assert delivery.at_stop(state, Stop()) is None


# ---------------------------------------------------------------------------
# Several families due at one stop
# ---------------------------------------------------------------------------


def test_due_instructions_are_combined_into_one_stop():
    state = _session(SERVICE_TASK + " " + BAR_TASK)
    ran(state, Call("file.write", {"file_path": "server.py"}), shell("python3 server.py &"))
    nudge = delivery.at_stop(state, Stop())
    assert nudge and set(nudge.rules) == {
        "delivery.service_persistence",
        "delivery.measured_acceptance",
    }
    assert nudge.text.startswith("Before finishing")


# ---------------------------------------------------------------------------
# State survives between hook processes
# ---------------------------------------------------------------------------


def test_state_round_trips_and_a_corrupt_file_starts_over(tmp_path):
    state = _session(SERVICE_TASK)
    ran(state, shell("python3 server.py &"))
    delivery.save(tmp_path, "sess/../1", state)
    assert delivery.load(tmp_path, "sess/../1") == state
    assert list(tmp_path.iterdir())[0].parent == tmp_path  # the id cannot escape the root

    (tmp_path / "bad.json").write_text("{not json")
    assert delivery.load(tmp_path, "bad") == SessionState()
