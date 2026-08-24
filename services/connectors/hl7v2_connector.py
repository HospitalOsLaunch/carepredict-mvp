"""HL7v2 connector entrypoint.

Implementation is completed in pass 1 step 3.
"""

from __future__ import annotations

SUPPORTED_MESSAGE_TYPES: set[str] = {"ADT^A01", "ADT^A03", "ORM^O01", "ORU^R01"}


def is_supported_message(message_type: str) -> bool:
    """Return whether an HL7v2 message type is in pass 1 scope."""
    return message_type in SUPPORTED_MESSAGE_TYPES
