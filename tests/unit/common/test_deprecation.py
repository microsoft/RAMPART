# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import pytest

from rampart.common.deprecation import emit_deprecation_warning


class TestEmitDeprecationWarning:
    def test_emits_deprecation_warning_for_string_items(self) -> None:
        with pytest.warns(
            DeprecationWarning,
            match="old thing is deprecated and will be removed in 1.0.0",
        ):
            emit_deprecation_warning(
                old_item="old thing",
                new_item="new thing",
                removed_in="1.0.0",
            )

    def test_message_names_the_replacement(self) -> None:
        with pytest.warns(DeprecationWarning, match="Use new thing instead") as record:
            emit_deprecation_warning(
                old_item="old thing",
                new_item="new thing",
                removed_in="1.0.0",
            )
        assert "removed in 1.0.0" in str(record[0].message)

    def test_uses_qualified_name_for_callables(self) -> None:
        def some_old_func() -> None: ...

        def some_new_func() -> None: ...

        with pytest.warns(DeprecationWarning, match="some_old_func") as record:
            emit_deprecation_warning(
                old_item=some_old_func,
                new_item=some_new_func,
                removed_in="2.0.0",
            )
        message = str(record[0].message)
        assert some_old_func.__qualname__ in message
        assert some_new_func.__qualname__ in message
        assert "2.0.0" in message
