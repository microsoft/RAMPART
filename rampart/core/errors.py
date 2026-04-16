# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Framework exceptions for RAMPART.

The framework defines one exception that surfaces and adapters should raise
for transient infrastructure failures.
"""


class InfrastructureError(Exception):
    """Raised by surfaces and adapters for transient infrastructure failures.

    When a surface cannot write to SharePoint (503, rate limit, timeout),
    or an adapter cannot reach the agent API, it should raise this
    exception. BaseExecution.execute_async catches it and produces a Result
    with SafetyStatus.ERROR.

    Teams should raise InfrastructureError (or a subclass) for any
    failure that is:
        1. Transient: likely to succeed on retry.
        2. External: caused by infrastructure outside the framework's control.
        3. Non-diagnostic: does not indicate anything about agent safety.

    Use ``raise InfrastructureError(...) from original_exception`` to
    preserve the causal chain via Python's native ``__cause__`` attribute.
    """
