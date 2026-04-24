# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.errors — framework exceptions."""

from rampart.core.errors import DriverError, InfrastructureError


class TestInfrastructureError:
    def test_is_exception(self):
        assert issubclass(InfrastructureError, Exception)

    def test_message(self):
        err = InfrastructureError("SharePoint returned 503")
        assert str(err) == "SharePoint returned 503"

    def test_cause_chain_preserved(self):
        original = ConnectionError("timeout")
        try:
            raise InfrastructureError("SharePoint unavailable") from original
        except InfrastructureError as exc:
            assert exc.__cause__ is original

    def test_catchable_as_exception(self):
        with_caught = False
        try:
            raise InfrastructureError("test")
        except Exception:
            with_caught = True
        assert with_caught


class TestDriverError:
    def test_is_exception(self):
        assert issubclass(DriverError, Exception)

    def test_message(self):
        err = DriverError("LLM returned garbage")
        assert str(err) == "LLM returned garbage"

    def test_cause_chain_preserved(self):
        original = ValueError("bad json")
        try:
            raise DriverError("parse failed") from original
        except DriverError as exc:
            assert exc.__cause__ is original

    def test_catchable_as_exception(self):
        with_caught = False
        try:
            raise DriverError("test")
        except Exception:
            with_caught = True
        assert with_caught
