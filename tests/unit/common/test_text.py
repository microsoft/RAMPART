# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from rampart.common.text import strip_ansi


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
