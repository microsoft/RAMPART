# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Driver implementations.

Re-exports StaticDriver and provides the coerce_driver helper
for ergonomic prompt/driver coercion.
"""

from rampart.drivers.static import StaticDriver

__all__ = ["StaticDriver"]
