"""Coverage tests for dynamic model defaults."""

from __future__ import annotations

import diffsan.contracts.models as models_module


class _FakeLocalNow:
    def __init__(self, *, tzinfo, offset: str, tz_name: str) -> None:
        self.tzinfo = tzinfo
        self._offset = offset
        self._tz_name = tz_name

    def astimezone(self):
        return self

    def strftime(self, fmt: str) -> str:
        if fmt == "%z":
            return self._offset
        if fmt == "%Z":
            return self._tz_name
        raise AssertionError(f"unexpected format: {fmt}")


class _FakeDateTime:
    _value = None

    @classmethod
    def now(cls):
        return cls._value


def test_default_note_timezone_prefers_zoneinfo_key(monkeypatch) -> None:
    class _Tz:
        key = "Asia/Tokyo"

    _FakeDateTime._value = _FakeLocalNow(tzinfo=_Tz(), offset="+0900", tz_name="JST")
    monkeypatch.setattr(models_module, "datetime", _FakeDateTime)

    assert models_module._default_note_timezone() == "Asia/Tokyo"


def test_default_note_timezone_falls_back_to_offset(monkeypatch) -> None:
    class _Tz:
        key = None

    _FakeDateTime._value = _FakeLocalNow(tzinfo=_Tz(), offset="-0530", tz_name="")
    monkeypatch.setattr(models_module, "datetime", _FakeDateTime)

    assert models_module._default_note_timezone() == "-05:30"


def test_default_note_timezone_falls_back_to_name(monkeypatch) -> None:
    class _Tz:
        key = ""

    _FakeDateTime._value = _FakeLocalNow(tzinfo=_Tz(), offset="", tz_name="PST")
    monkeypatch.setattr(models_module, "datetime", _FakeDateTime)

    assert models_module._default_note_timezone() == "PST"


def test_default_note_timezone_falls_back_to_utc(monkeypatch) -> None:
    _FakeDateTime._value = _FakeLocalNow(tzinfo=None, offset="", tz_name="")
    monkeypatch.setattr(models_module, "datetime", _FakeDateTime)

    assert models_module._default_note_timezone() == "UTC"
