"""Put ``scripts/`` on the path so ``figure`` imports from tests.

The figure package deliberately lives under ``scripts`` because it is loaded by
Blender's ``-P``, which runs the entry point as ``__main__`` and leaves sibling
modules unimportable. pytest's rootdir is the repo root, so without this the
package would be unimportable from tests and every figure test would need a
sys.path dance of its own.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
