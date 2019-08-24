"""A Hypothesis extension for JSON schemata.

The only public API is `from_schema`; check the docstring for details.
"""

__version__ = "0.9.8"
__all__ = ["from_schema", "UnresolvableReference"]

from ._impl import UnresolvableReference, from_schema
