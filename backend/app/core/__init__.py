"""Core app wiring: container and logging."""
from .container import Container, get_container
from .logging_config import configure_logging

__all__ = ["Container", "get_container", "configure_logging"]
