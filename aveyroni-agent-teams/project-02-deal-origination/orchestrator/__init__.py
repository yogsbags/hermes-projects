"""Aveyroni origination orchestrator.

Hermes runs the controller, the fit scorer, the evidence reviewer, and the
research workers. Parsing, deduplication, validation, and storage stay in code.
"""

from orchestrator.service import Orchestrator

__all__ = ["Orchestrator"]
