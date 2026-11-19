"""
Observability module for LangFuse integration (Langfuse Python SDK v4).
Provides a context manager that sets up tracing, opens a root observation for
the Lambda invocation, and flushes traces on exit.
"""

import os
import json
import logging
from contextlib import contextmanager, ExitStack
from typing import Any, Optional

# Use root logger for Lambda compatibility
logger = logging.getLogger()
logger.setLevel(logging.INFO)

SERVICE_NAME = "afp_tagger_agent"
FLUSH_WAIT_SECONDS = 10

# Instrumentation scope used by logfire.instrument_openai_agents(). The Langfuse v4
# default span filter only keeps spans with gen_ai.* attributes, which drops the
# root "OpenAI Agents trace" span and orphans the agent/tool spans under it.
OPENAI_AGENTS_SCOPE_PREFIX = "logfire.openai_agents"


def should_export_span(span) -> bool:
    """Langfuse default span filter plus the Logfire OpenAI Agents spans."""
    from langfuse.span_filter import is_default_export_span

    if is_default_export_span(span):
        return True
    scope = span.instrumentation_scope
    return scope is not None and scope.name.startswith(OPENAI_AGENTS_SCOPE_PREFIX)


def extract_job_id(event: Any) -> Optional[str]:
    """Best-effort job_id lookup for direct invocations and SQS messages."""
    try:
        if isinstance(event, str):
            event = json.loads(event)
        if not isinstance(event, dict):
            return None
        if event.get("job_id"):
            return str(event["job_id"])
        records = event.get("Records")
        if records:
            body = records[0].get("body")
            if isinstance(body, str) and body.startswith("{"):
                body = json.loads(body).get("job_id")
            return str(body) if body else None
    except Exception:
        return None
    return None


@contextmanager
def observe(event: Any = None):
    """
    Context manager for observability with LangFuse.

    Sets up LangFuse observability if environment variables are configured,
    opens a root observation for this invocation (input = the event), propagates
    the job_id as the Langfuse session ID to every child observation, and
    ensures traces are flushed on exit. Yields the Langfuse client, or None when
    LangFuse is not configured.

    Usage:
        from observability import observe, record_output

        with observe(event) as observability:
            response = handle(event)
            record_output(observability, response)
            return response
    """
    logger.info("🔍 Observability: Checking configuration...")

    # Check if required environment variables exist
    has_langfuse = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))

    logger.info(f"🔍 Observability: LANGFUSE_SECRET_KEY exists: {has_langfuse}")
    logger.info(f"🔍 Observability: OPENAI_API_KEY exists: {has_openai}")

    if not has_langfuse:
        logger.info("🔍 Observability: LangFuse not configured, skipping setup")
        yield None
        return

    if not has_openai:
        logger.warning("⚠️  Observability: OPENAI_API_KEY not set, traces may not export")

    # Local variable for the client (no global needed)
    langfuse_client = None

    # Try to set up LangFuse
    try:
        logger.info("🔍 Observability: Setting up LangFuse...")

        import logfire
        from langfuse import Langfuse

        # Configure logfire to instrument OpenAI Agents SDK
        logfire.configure(
            service_name=SERVICE_NAME,
            send_to_logfire=False,  # Don't send to Logfire cloud
        )
        logger.info("✅ Observability: Logfire configured")

        # Instrument OpenAI Agents SDK
        logfire.instrument_openai_agents()
        logger.info("✅ Observability: OpenAI Agents SDK instrumented")

        # Initialize LangFuse client (reads LANGFUSE_* env vars)
        langfuse_client = Langfuse(should_export_span=should_export_span)
        logger.info("✅ Observability: LangFuse client initialized")

        # Optional: Check authentication (blocking call, use sparingly)
        try:
            auth_result = langfuse_client.auth_check()
            logger.info(
                f"✅ Observability: LangFuse authentication check passed (result: {auth_result})"
            )
        except Exception as auth_error:
            logger.warning(f"⚠️  Observability: Auth check failed but continuing: {auth_error}")

        logger.info("🎯 Observability: Setup complete - traces will be sent to LangFuse")

    except ImportError as e:
        logger.error(f"❌ Observability: Missing required package: {e}")
        langfuse_client = None
    except Exception as e:
        logger.error(f"❌ Observability: Setup failed: {e}")
        langfuse_client = None

    try:
        with ExitStack() as stack:
            if langfuse_client:
                try:
                    from langfuse import propagate_attributes

                    # Root observation for the invocation: trace input/output come from here
                    stack.enter_context(
                        langfuse_client.start_as_current_observation(
                            name=SERVICE_NAME, as_type="span", input=event
                        )
                    )
                    # Correlating attributes must be set before child observations are created
                    attributes = {"trace_name": SERVICE_NAME}
                    job_id = extract_job_id(event)
                    if job_id:
                        attributes["session_id"] = job_id
                    stack.enter_context(propagate_attributes(**attributes))
                except Exception as e:
                    logger.error(f"❌ Observability: Failed to start root observation: {e}")

            # Yield control back to the calling code
            yield langfuse_client
    finally:
        # Flush traces on exit
        if langfuse_client:
            try:
                logger.info("🔍 Observability: Flushing traces to LangFuse...")
                langfuse_client.flush()
                langfuse_client.shutdown()

                # Add a delay to ensure network requests complete
                # This is a workaround for Lambda's immediate termination
                import time

                logger.info(
                    f"🔍 Observability: Waiting {FLUSH_WAIT_SECONDS} seconds for flush to complete..."
                )
                time.sleep(FLUSH_WAIT_SECONDS)

                logger.info("✅ Observability: Traces flushed successfully")
            except Exception as e:
                logger.error(f"❌ Observability: Failed to flush traces: {e}")
        else:
            logger.debug("🔍 Observability: No client to flush")


def record_output(langfuse_client, output: Any) -> None:
    """Set the invocation result as output on the root observation."""
    if not langfuse_client:
        return
    try:
        langfuse_client.update_current_span(output=output)
    except Exception as e:
        logger.warning(f"⚠️  Observability: Failed to record output: {e}")
