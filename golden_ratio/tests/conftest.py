import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from golden_ratio.config import AlgorithmConfig


@pytest.fixture
def cfg():
    return AlgorithmConfig()
