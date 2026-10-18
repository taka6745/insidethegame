"""Explicit disposable recording selection; never resets a match on application boot."""
from pathlib import Path


def load_product_demo():
    return (Path(__file__).parents[2] / 'fixtures/product-demo.json').read_bytes()
