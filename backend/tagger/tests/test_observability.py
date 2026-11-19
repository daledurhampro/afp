"""
Langfuse v4 observability: span filtering, trace hierarchy, root input/output
and session propagation. Spans go to an in-memory exporter, so nothing is sent
over the network; this does not verify backend ingestion.
"""

import asyncio

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import observability
from observability import extract_job_id, observe, record_output


@pytest.mark.parametrize(
    "event, expected",
    [
        ({"job_id": "job-1"}, "job-1"),
        ('{"job_id": "job-2"}', "job-2"),
        ({"Records": [{"body": "job-3"}]}, "job-3"),
        ({"Records": [{"body": '{"job_id": "job-4"}'}]}, "job-4"),
        ({"instruments": []}, None),
        (None, None),
        ("not json", None),
    ],
)
def test_extract_job_id(event, expected):
    assert extract_job_id(event) == expected


def test_observe_without_langfuse_yields_none():
    with observe({"job_id": "job-1"}) as client:
        assert client is None
    record_output(None, {"ok": True})  # no-op without a client


def _run_fake_agent():
    from agents import Agent, Runner, function_tool, trace
    from agents.items import ModelResponse
    from agents.models.interface import Model
    from agents.usage import Usage
    from openai.types.responses import (
        ResponseFunctionToolCall,
        ResponseOutputMessage,
        ResponseOutputText,
    )

    class FakeModel(Model):
        calls = 0

        async def get_response(self, *args, **kwargs):
            FakeModel.calls += 1
            if FakeModel.calls == 1:
                output = [
                    ResponseFunctionToolCall(
                        type="function_call", call_id="c1", name="lookup", arguments="{}", id="fc1"
                    )
                ]
            else:
                output = [
                    ResponseOutputMessage(
                        id="m1",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
                    )
                ]
            return ModelResponse(
                output=output,
                usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15),
                response_id=None,
            )

        def stream_response(self, *args, **kwargs):
            raise NotImplementedError

    @function_tool
    def lookup() -> str:
        """Look something up."""
        return "data"

    async def run():
        with trace("Test Agent"):
            agent = Agent(name="Tester", instructions="x", model=FakeModel(), tools=[lookup])
            return (await Runner.run(agent, input="task")).final_output

    return asyncio.run(run())


def test_trace_hierarchy_session_and_root_io(monkeypatch):
    import agents
    import langfuse

    exporter = InMemorySpanExporter()
    real_langfuse = langfuse.Langfuse

    def langfuse_with_memory_exporter(**kwargs):
        return real_langfuse(span_exporter=exporter, **kwargs)

    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")
    monkeypatch.setattr(langfuse, "Langfuse", langfuse_with_memory_exporter)
    # Production flush relies on the batch timer firing during FLUSH_WAIT_SECONDS:
    # with Logfire console output on, OTEL's force_flush stops at Logfire's
    # processor before reaching Langfuse's. Shorten both for the test.
    monkeypatch.setenv("LANGFUSE_FLUSH_INTERVAL", "0.2")
    monkeypatch.setattr(observability, "FLUSH_WAIT_SECONDS", 1)
    agents.set_tracing_disabled(False)
    try:
        event = {"job_id": "job-123"}
        with observe(event) as client:
            assert client is not None
            final_output = _run_fake_agent()
            client.create_event(name="Test Event", status_message="OK")
            response = {"statusCode": 200, "final_output": final_output}
            record_output(client, response)
    finally:
        agents.set_tracing_disabled(True)

    spans = exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    names = [s.name for s in spans]

    # Logfire's OpenAI Agents spans survive the v4 default span filter
    assert any(s.instrumentation_scope.name.startswith("logfire.openai_agents") for s in spans)
    assert any("OpenAI Agents trace" in n for n in names), names
    assert any(n.startswith("Function") for n in names), names

    # One root observation and no orphaned spans
    roots = [s for s in spans if s.parent is None]
    assert [r.name for r in roots] == [observability.SERVICE_NAME]
    root = roots[0]
    assert len({s.context.trace_id for s in spans}) == 1
    for s in spans:
        if s.parent is not None:
            assert s.parent.span_id in by_id, f"{s.name} has an unexported parent"

    # Root observation carries the invocation input/output
    assert "job-123" in root.attributes["langfuse.observation.input"]
    assert "final_output" in root.attributes["langfuse.observation.output"]

    # Session ID and trace name propagate to every observation
    for s in spans:
        assert s.attributes.get("session.id") == "job-123", s.name
    assert root.attributes.get("langfuse.trace.name") == observability.SERVICE_NAME
