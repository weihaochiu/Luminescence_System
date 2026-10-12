"""Compatibility import for the relocated standalone tester."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module('standalone.light_linearity_tester.messages')
