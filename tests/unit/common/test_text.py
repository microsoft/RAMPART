# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio

import pytest

from rampart.common.text import safe_str, safe_str_list, strip_ansi


class TestStripAnsi:
    def test_preserves_plain_text(self) -> None:
        assert strip_ansi("hello world") == "hello world"

    def test_removes_color_codes(self) -> None:
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_removes_cursor_movement(self) -> None:
        assert strip_ansi("\x1b[2Ahidden") == "hidden"

    def test_removes_clear_screen(self) -> None:
        assert strip_ansi("\x1b[2J\x1b[Hinjected") == "injected"

    def test_removes_osc_hyperlink_bel_terminated(self) -> None:
        text = "\x1b]8;;http://example.com\x07link\x1b]8;;\x07"
        assert strip_ansi(text) == "link"

    def test_removes_osc_window_title_st_terminated(self) -> None:
        text = "before\x1b]0;malicious title\x1b\\after"
        assert strip_ansi(text) == "beforeafter"

    def test_removes_dcs_block(self) -> None:
        assert strip_ansi("\x1bPdevice-control\x1b\\tail") == "tail"

    def test_removes_eight_bit_csi(self) -> None:
        assert strip_ansi("\x9b31mred") == "red"

    def test_removes_lone_c1_control(self) -> None:
        assert strip_ansi("a\x84b") == "ab"

    def test_preserves_whitespace_controls(self) -> None:
        assert strip_ansi("a\tb\nc\rd") == "a\tb\nc\rd"

    def test_strips_residual_c0_controls(self) -> None:
        assert strip_ansi("a\x00b\x07c") == "abc"

    def test_does_not_touch_bracket_text_without_escape(self) -> None:
        text = "not an escape [0m or [31m here"
        assert strip_ansi(text) == text

    def test_strips_chained_sequences(self) -> None:
        assert strip_ansi("\x1b[1m\x1b[31mbold red\x1b[0m\x1b[0m") == "bold red"


class TestSafeStr:
    def test_passes_a_string_through(self) -> None:
        assert safe_str(value="already text") == "already text"

    def test_coerces_a_non_string(self) -> None:
        assert safe_str(value=42) == "42"

    def test_a_raising_repr_costs_only_itself(self) -> None:
        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        assert safe_str(value=Boom()) == "<unprintable value>"

    def test_a_raising_repr_does_not_escape(self) -> None:
        class Boom:
            def __str__(self) -> str:
                raise ValueError("boom")

            def __repr__(self) -> str:
                raise ValueError("boom")

        assert safe_str(value=Boom()) == "<unprintable value>"

    @pytest.mark.parametrize(
        "control_flow",
        [asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit],
    )
    def test_does_not_swallow_control_flow(
        self,
        control_flow: type[BaseException],
    ) -> None:
        # These are BaseException, not Exception. Catching them would break
        # cancellation in an async framework.
        class Raises:
            def __str__(self) -> str:
                raise control_flow

        with pytest.raises(control_flow):
            safe_str(value=Raises())


class TestSafeStrList:
    def test_passes_a_list_of_strings_through(self) -> None:
        assert safe_str_list(value=["a", "b"]) == ["a", "b"]

    def test_coerces_each_item(self) -> None:
        assert safe_str_list(value=[1, None]) == ["1", "None"]

    def test_a_string_is_one_reason_not_many_characters(self) -> None:
        assert safe_str_list(value="abc") == ["abc"]

    def test_a_non_iterable_gives_nothing(self) -> None:
        assert safe_str_list(value=42) == []

    def test_a_raising_bool_gives_nothing(self) -> None:
        class Boom:
            def __bool__(self) -> bool:
                raise RuntimeError("boom")

            def __iter__(self) -> object:
                raise RuntimeError("boom")

        assert safe_str_list(value=Boom()) == []

    def test_a_raising_item_costs_only_itself(self) -> None:
        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        assert safe_str_list(value=[Boom(), "kept"]) == [
            "<unprintable value>",
            "kept",
        ]
