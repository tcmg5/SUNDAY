"""Qt needs a platform plugin even to construct widgets; offscreen needs no display."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
