# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Attack factories.

Attacks test for BAD things.  When the evaluator detects the attack
objective, the result is UNSAFE (safe=False).
"""

from rampart.attacks._factory import Attacks
from rampart.attacks._xpia import XPIAExecution

__all__ = ["Attacks", "XPIAExecution"]
