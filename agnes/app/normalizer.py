"""
Normalization layer.

Wraps llm.canonicalize() with an in-memory cache so every SKU is only
normalized once per process. (In prod this would be a DB table.)
"""
from typing import Dict
from .llm import canonicalize

_cache: Dict[str, Dict] = {}


def normalize(sku: str) -> Dict:
    if sku in _cache:
        return _cache[sku]
    res = canonicalize(sku)
    _cache[sku] = res
    return res


def clear_cache():
    _cache.clear()
