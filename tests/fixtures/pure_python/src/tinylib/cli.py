"""CLI entry point."""

import sys
from .core import hash_data


def main() -> int:
    """Main entry point."""
    if len(sys.argv) > 1:
        print(hash_data(sys.argv[1]))
    return 0
