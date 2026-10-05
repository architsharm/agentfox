"""What the repository scanner reads, and what it says when it read nothing.

Two findings are pinned here.

**A clean result has to be earned.** Pointed at a TypeScript repository the scanner
opened the three JSON config files it recognised, matched nothing, and printed "No
model calls found". For a security product that is the worst available failure: it is
not a missed detection, it is a claim of safety made after reading none of the source.
A scan that reads no file in a language it understands must now say exactly that.

**TypeScript and JavaScript are read.** The JS pass is regex, not a parse, and is
written for precision: a false "you are ungoverned" is a lie in the same way a false
"clean" is. The negative tests below are therefore as load-bearing as the positive
ones.

What these tests do not prove: that the scanner finds every model call in a real
TypeScript repository. They cover the call shapes listed in `discovery.py` and the
documented exclusions. Recall against arbitrary code is not asserted anywhere here,
and the scanner under-reports by design when an SDK is imported in a different file
from the call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentfox.discovery.repo import SUPPORTED_LANGUAGES, ScanReport, scan

REPO = Path(__file__).resolve().parents[1]


def _sites(report: ScanReport, kind: str) -> list[str]:
    return [f"{s.file}:{s.line}" for s in report.sites if s.kind == kind]


@pytest.fixture
def repo(tmp_path):
    """An empty scan root of its own.

    Not `tmp_path` itself: `conftest.isolated_db` puts the test's SQLite file there,
    and those .db files would show up in the scan's own skipped-extension counts.
    """
    root = tmp_path / "repo"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# A scan that read nothing says so
# ---------------------------------------------------------------------------


def test_a_repo_in_an_unsupported_language_is_reported_as_inconclusive(repo):
    (repo / "main.go").write_text("package main\nfunc main() {}\n")
    (repo / "app.rb").write_text("puts 'hi'\n")

    report = scan(repo)

    assert report.inconclusive is True
    assert report.code_files_scanned == 0
    assert report.skipped_suffixes == {".go": 1, ".rb": 1}


def test_an_inconclusive_scan_never_claims_no_model_calls_were_found(repo):
    """The exact string the deployed scanner printed after reading nothing."""
    (repo / "main.go").write_text("package main\n")

    step = scan(repo).next_step()

    assert "No model calls found" not in step
    assert "says nothing about" in step
    assert SUPPORTED_LANGUAGES in step
    assert ".go" in step


def test_config_files_alone_do_not_count_as_having_read_the_source(repo):
    """The deployed failure exactly: three JSON files opened, source never looked at.

    A config file is read for secrets and MCP declarations, not for model calls, so
    opening one is not evidence that the repository was examined.
    """
    (repo / "package.json").write_text('{"name": "x"}')
    (repo / "tsconfig.json").write_text("{}")

    report = scan(repo)

    assert report.files_scanned == 2
    assert report.code_files_scanned == 0
    assert report.inconclusive is True


def test_a_supported_file_with_nothing_in_it_is_a_real_clean_result(repo):
    """The other side of the same line: having read source and found nothing is a
    finding, and is allowed to say so."""
    (repo / "util.py").write_text("x = 1\n")

    report = scan(repo)

    assert report.inconclusive is False
    assert "No model calls found" in report.next_step()
    assert SUPPORTED_LANGUAGES in report.next_step()


def test_a_report_not_built_by_a_walk_is_not_called_inconclusive():
    """`discovery_openapi.scan_spec` builds a report from a spec, never a directory.
    It has no source-coverage claim to make either way, so it makes none."""
    assert ScanReport(root=".").code_files_scanned is None
    assert ScanReport(root=".").inconclusive is False


def test_the_json_report_carries_the_caveat_the_counts_need(repo):
    (repo / "main.go").write_text("package main\n")

    payload = scan(repo).to_json()

    assert payload["inconclusive"] is True
    assert payload["code_files_scanned"] == 0
    assert payload["skipped_suffixes"] == {".go": 1}
    assert payload["supported_languages"] == SUPPORTED_LANGUAGES
    # coverage still reads 1.0 on an empty denominator, which is why `inconclusive`
    # travels with it.
    assert payload["coverage"] == 1.0


# ---------------------------------------------------------------------------
# TypeScript / JavaScript detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "source", "provider"),
    [
        (
            "openai.ts",
            'import OpenAI from "openai";\n'
            "const c = new OpenAI();\n"
            'const r = await c.chat.completions.create({ model: "gpt-4o", messages });\n',
            "openai",
        ),
        (
            "openai-responses.ts",
            'import OpenAI from "openai";\n'
            'const r = await client.responses.create({ model: "gpt-4o", input: "hi" });\n',
            "openai",
        ),
        (
            "anthropic.ts",
            'import Anthropic from "@anthropic-ai/sdk";\n'
            "const c = new Anthropic();\n"
            'const m = await c.messages.create({ model: "claude-sonnet-4", max_tokens: 8 });\n',
            "anthropic",
        ),
        (
            "langchain.js",
            'const { ChatOpenAI } = require("@langchain/openai");\n'
            'const model = new ChatOpenAI({ model: "gpt-4o" });\n',
            "langchain",
        ),
        (
            "vercel.tsx",
            'import { generateText } from "ai";\n'
            'import { openai } from "@ai-sdk/openai";\n'
            'const { text } = await generateText({ model: openai("gpt-4o"), prompt: "hi" });\n',
            "vercel-ai",
        ),
        (
            "vercel-stream.mjs",
            'import { streamText } from "ai";\nconst s = streamText({ model, prompt: "hi" });\n',
            "vercel-ai",
        ),
    ],
)
def test_javascript_model_calls_are_found(repo, filename, source, provider):
    (repo / filename).write_text(source)

    report = scan(repo)

    assert len(report.model_calls) == 1, report.to_json()["sites"]
    assert report.model_calls[0].provider == provider
    assert report.model_calls[0].file == filename
    assert report.inconclusive is False


def test_a_langgraph_agent_definition_is_found(repo):
    (repo / "graph.ts").write_text(
        'import { StateGraph } from "@langchain/langgraph";\n'
        "const graph = new StateGraph({ channels });\n"
    )

    report = scan(repo)

    assert len(report.agent_definitions) == 1
    assert report.frameworks == ["LangGraph"]
    # A graph is governable even with no direct provider call in the file — the same
    # reason `_AGENT_DEFINITIONS` exists for CrewAI and LangGraph in Python.
    assert report.ungoverned


def test_typescript_frameworks_are_named_even_when_no_call_is_found(repo):
    (repo / "app.tsx").write_text('import Anthropic from "@anthropic-ai/sdk";\nexport {};\n')

    report = scan(repo)

    assert report.frameworks == ["Anthropic SDK"]
    assert report.model_calls == []


def test_only_one_site_is_recorded_for_a_nested_call_shape(repo):
    """`.chat.completions.create` also matches `.completions.create`; the more
    specific pattern wins so the same call is not counted twice."""
    (repo / "x.ts").write_text(
        'import OpenAI from "openai";\nawait c.chat.completions.create({ messages });\n'
    )

    assert len(scan(repo).model_calls) == 1


# -- precision --------------------------------------------------------------


def test_a_langchain_invoke_is_not_reported_as_a_model_call(repo):
    """In LangChain JS every runnable has `.invoke()`, prompt templates and output
    parsers included. Matching it would report a prompt template as a model call."""
    (repo / "chain.ts").write_text(
        'import { ChatPromptTemplate } from "@langchain/core/prompts";\n'
        "const prompt = ChatPromptTemplate.fromMessages([]);\n"
        'const out = await prompt.invoke({ q: "hi" });\n'
        'const res = await chain.invoke({ q: "hi" });\n'
    )

    assert scan(repo).model_calls == []


def test_a_same_named_local_function_is_not_reported(repo):
    """`generateText` only means the Vercel AI SDK in a file that imported it."""
    (repo / "text.ts").write_text(
        "export function generateText(x: string) { return x; }\n"
        'const y = generateText("nothing to do with a model");\n'
    )

    assert scan(repo).model_calls == []


def test_an_orm_call_that_looks_like_anthropic_is_not_reported(repo):
    """`db.messages.create(...)` is a database write. Without an Anthropic import in
    the file the shape does not mean what it looks like."""
    (repo / "db.ts").write_text(
        'import { db } from "./client";\nawait db.messages.create({ body: "hello" });\n'
    )

    assert scan(repo).model_calls == []


def test_a_commented_out_call_is_not_reported(repo):
    (repo / "old.ts").write_text(
        'import OpenAI from "openai";\n'
        "// const r = await c.chat.completions.create({ messages });\n"
        " * await c.chat.completions.create({ messages });\n"
    )

    assert scan(repo).model_calls == []


def test_a_vercel_tool_declaration_is_found_and_a_bare_one_is_not(repo):
    (repo / "with.ts").write_text(
        'import { tool } from "ai";\nconst t = tool({ description: "x" });\n'
    )
    (repo / "without.ts").write_text('const t = tool({ description: "x" });\n')

    files = _sites(scan(repo), "tool")

    assert files == ["with.ts:2"]


# ---------------------------------------------------------------------------
# Against this repository's own code, which is what the audit used
# ---------------------------------------------------------------------------


def test_the_dashboard_is_read_and_honestly_reported_as_having_no_model_calls():
    """dashboard/ is TypeScript that does not call a model. Before this it was
    "No model calls found" after reading 3 of 210 files; the difference is that the
    source is now actually read."""
    report = scan(REPO / "dashboard")

    assert report.code_files_scanned is not None and report.code_files_scanned > 50
    assert report.inconclusive is False
    assert report.model_calls == []
    assert report.agent_definitions == []
    assert "Next.js" in report.frameworks


def test_the_demo_directory_still_reports_its_python_agents():
    """demo/ is Python that does call models through CrewAI and LangChain. The
    TypeScript pass must not have disturbed the Python one."""
    report = scan(REPO / "demo")

    assert report.inconclusive is False
    assert report.agent_definitions, "demo/ defines CrewAI and LangGraph agents"
    assert {"CrewAI", "LangChain"} <= set(report.frameworks)
    assert [s for s in report.sites if s.kind == "tool"]


def test_a_spec_scans_next_step_quotes_no_file_count():
    """`discovery_openapi.scan_spec` never walked a directory, so there is no source
    file count to quote and no language coverage to claim."""
    from agentfox.discovery.openapi import scan_spec

    step = scan_spec({"openapi": "3.0.0", "paths": {}}).next_step()

    assert "None source file" not in step
    assert step.startswith("No model calls found.")


def test_a_call_shown_in_a_string_or_comment_is_not_a_call(tmp_path):
    """A docs page that prints `client.chat.completions.create(...)` in a template
    string calls no model. Only code counts; an expression inside `${...}` is code."""
    (tmp_path / "page.tsx").write_text(
        "import OpenAI from 'openai';\n"
        "const example = `client.chat.completions.create({ model: 'gpt-4o' })`;\n"
        'const quoted = "openai.chat.completions.create(";\n'
        "// openai.chat.completions.create(\n"
        "/* openai.chat.completions.create( */\n"
        "const real = await client.chat.completions.create({ model: 'gpt-4o' });\n"
        "const inner = `${await client.chat.completions.create({ model: 'x' })}`;\n"
    )
    report = scan(tmp_path)
    assert sorted(s.line for s in report.model_calls) == [6, 7]


def test_a_call_shown_in_jsx_code_text_is_not_a_call(tmp_path):
    (tmp_path / "page.tsx").write_text(
        "import OpenAI from 'openai';\n"
        "export const P = () => <p>A plain\n"
        "  <code>client.chat.completions.create(...)</code> call.</p>;\n"
        "const real = await client.chat.completions.create({ model: 'gpt-4o' });\n"
    )
    assert [s.line for s in scan(tmp_path).model_calls] == [4]
