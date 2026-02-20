"""
Dramatiq middleware for OpenTelemetry distributed tracing.
Integrates Dramatiq workers with the existing OTLP tracing infrastructure.
"""

from opentelemetry import trace
from opentelemetry.context import attach, detach, set_value
from opentelemetry.propagate import extract, inject
from opentelemetry.propagators.textmap import CarrierT, Getter, Setter
from opentelemetry.trace import SpanKind, Status, StatusCode
from typing import Optional, List, Dict, Any
import dramatiq
from dramatiq.middleware import Middleware
from loguru import logger


class DramatiqCarrierGetter(Getter[CarrierT]):
    """Getter for extracting trace context from Dramatiq message headers."""

    def get(self, carrier: CarrierT, key: str) -> Optional[List[str]]:
        if isinstance(carrier, dict):
            value = carrier.get(key)
            if value is None:
                return None
            if isinstance(value, list):
                return value
            return [str(value)]
        return None

    def keys(self, carrier: CarrierT) -> List[str]:
        if isinstance(carrier, dict):
            return list(carrier.keys())
        return []


class DramatiqCarrierSetter(Setter[CarrierT]):
    """Setter for injecting trace context into Dramatiq message headers."""

    def set(self, carrier: CarrierT, key: str, value: str) -> None:
        if isinstance(carrier, dict):
            carrier[key] = value


class OpenTelemetryMiddleware(Middleware):
    """
    Dramatiq middleware that creates spans for message processing.

    Features:
    - Creates a span for each message processed
    - Propagates trace context through message headers
    - Records errors as span exceptions
    - Adds message metadata as span attributes
    """

    def __init__(self, service_name: str = "wp-k8s-service-worker"):
        self.tracer = trace.get_tracer(__name__)
        self.getter = DramatiqCarrierGetter()
        self.setter = DramatiqCarrierSetter()
        self.service_name = service_name
        logger.info(f"OpenTelemetry middleware initialized for {service_name}")

    def after_process_boot(self, broker: dramatiq.Broker) -> None:
        """Called when the worker process starts."""
        logger.info(f"Dramatiq worker booted with OpenTelemetry tracing")

    def before_process_message(
        self, broker: dramatiq.Broker, message: dramatiq.Message
    ) -> None:
        """Called before processing a message - starts a span."""
        actor_name = message.actor_name

        # Extract trace context from message headers
        ctx = extract(message.options, getter=self.getter)
        token = attach(ctx)
        message._ctx_token = token

        # Create span for message processing
        span = self.tracer.start_span(
            name=f"{actor_name} process",
            kind=SpanKind.CONSUMER,
            context=ctx,
            attributes={
                "dramatiq.actor": actor_name,
                "dramatiq.message_id": message.message_id,
                "dramatiq.queue": message.queue_name,
            },
        )

        # Store span in message for later retrieval
        message._span = span

        # Set span as current in context
        attach(trace.set_span_in_context(span))

        logger.debug(
            f"Started span for message {message.message_id} (actor: {actor_name})"
        )

    def after_process_message(
        self,
        broker: dramatiq.Broker,
        message: dramatiq.Message,
        *,
        result: Any = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Called after processing a message - ends the span."""
        span = getattr(message, "_span", None)
        ctx_token = getattr(message, "_ctx_token", None)

        if span is None:
            return

        try:
            if exception is not None:
                # Record exception
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(exception)
                span.set_attribute("dramatiq.error", str(exception))
                logger.error(f"Message {message.message_id} failed: {exception}")
            else:
                # Mark as successful
                span.set_status(Status(StatusCode.OK))
                logger.debug(f"Message {message.message_id} processed successfully")

            # Add result metadata if available
            if result is not None:
                span.set_attribute("dramatiq.has_result", True)

        finally:
            # End span
            span.end()

            # Detach context
            if ctx_token is not None:
                detach(ctx_token)

    def after_enqueue(
        self, broker: dramatiq.Broker, message: dramatiq.Message, delay: Optional[int]
    ) -> None:
        """Called after a message is enqueued - injects trace context."""
        # Get current span (from the request that triggered the enqueue)
        current_span = trace.get_current_span()

        if current_span.is_recording():
            # Inject trace context into message options
            inject(message.options, setter=self.setter)
            logger.debug(f"Injected trace context into message {message.message_id}")


class DramatiqTracing:
    """
    Helper class to configure Dramatiq with OpenTelemetry tracing.

    Usage:
        from dramatiq_otlp_middleware import DramatiqTracing

        DramatiqTracing.setup()
        dramatiq.set_broker(broker)
    """

    @staticmethod
    def setup(service_name: str = "wp-k8s-service-worker") -> None:
        """
        Setup Dramatiq with OpenTelemetry middleware.

        Args:
            service_name: Name of the service for tracing
        """
        broker = dramatiq.get_broker()

        # Add OpenTelemetry middleware
        otel_middleware = OpenTelemetryMiddleware(service_name=service_name)
        broker.add_middleware(otel_middleware)

        logger.info(f"Dramatiq tracing enabled for service: {service_name}")
