"""Explicit disposable recording selection; never resets a match on application boot."""
from pathlib import Path
import os
import httpx


def load_product_demo():
    if url := os.getenv('DEMO_RECORDING_URL'):
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    return (Path(__file__).parents[2] / 'fixtures/product-demo.json').read_bytes()
