"""Aura Mail AI - Cloud Email Providers Package."""

from backend.providers.base import (
    BaseEmailProvider,
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    encode_composite_id,
    decode_composite_id
)
from backend.providers.demo import DemoProvider

__all__ = [
    "BaseEmailProvider",
    "ProviderType",
    "AccountIdentity",
    "ProviderOperationResult",
    "encode_composite_id",
    "decode_composite_id",
    "DemoProvider"
]
