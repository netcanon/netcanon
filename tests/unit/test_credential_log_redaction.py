"""
Regression tests for SEC-2 / SEC-7 (2026-07-03 review): the storage loaders
decrypt credentials into an in-memory dict *before* ``model_validate``, so a
subsequent pydantic ``ValidationError`` captures the freshly-decrypted secret
in its per-error ``input``.  ``scrub_exc_for_log`` must format such an error
without echoing that input, and both stores must route their corrupt-file
error path through it.

NOTE (verify-first): on the currently-resolved pydantic (2.13) ``str(exc)``
does not render the captured input, so the *default* log line already happens
not to leak.  But ``exc.errors()`` DOES carry it, and the supported range
(``pydantic>=2.0.0,<3``) admits older 2.x versions whose ``str`` rendered it —
so this is defence-in-depth at a decrypt-then-log site, guaranteed independent
of the pydantic version / formatting path.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from netcanon.models.device_profile import DeviceProfile
from netcanon.security.migration import scrub_exc_for_log
from netcanon.storage.device_profile_store import FileDeviceProfileStore

pytestmark = pytest.mark.unit

_SECRET = "PLAINTEXT-SECRET-DO-NOT-LOG"


def _validation_error_carrying(secret: str) -> ValidationError:
    """A ValidationError whose captured input holds *secret*.

    A missing required field makes pydantic capture the whole input dict as
    that error's ``input`` — the model-level case the store hits after
    decrypting credentials into the dict.
    """
    class _M(BaseModel):
        name: str
        password: str

    try:
        _M.model_validate({"password": secret})  # 'name' missing
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")  # pragma: no cover


class TestScrubExcForLog:
    def test_secret_is_present_in_the_raw_error_object(self):
        """Premise: the exposure is real — the error object carries the
        secret in its errors()[*]['input'] (version-independent)."""
        exc = _validation_error_carrying(_SECRET)
        assert any(_SECRET in str(e.get("input")) for e in exc.errors())

    def test_scrubbed_form_drops_the_input_but_keeps_locations(self):
        exc = _validation_error_carrying(_SECRET)
        scrubbed = scrub_exc_for_log(exc)
        assert _SECRET not in scrubbed
        assert "name" in scrubbed          # field location preserved
        assert "missing" in scrubbed       # error type preserved
        assert "validation error(s)" in scrubbed

    def test_non_validation_error_passes_through_unchanged(self):
        exc = ValueError("plain boom")
        assert scrub_exc_for_log(exc) == "plain boom"


class TestDeviceProfileStoreDoesNotLogDecryptedCreds:
    def test_corrupt_file_error_log_omits_decrypted_credential(
        self, tmp_path: Path, caplog
    ):
        store = FileDeviceProfileStore(tmp_path)
        p = DeviceProfile(
            name="sw", type_key="Cisco", host="10.0.0.1", port=22,
            username="admin", password=_SECRET, enable_password="ENABLE-XYZ",
        )
        store.save(p)  # writes the credential ENCRYPTED to disk

        # Sanity: the on-disk file must not contain the plaintext.
        jf = tmp_path / f"{p.id}.json"
        assert _SECRET not in jf.read_text(encoding="utf-8")

        # Corrupt the file so model_validate fails AFTER the loader has
        # decrypted the credential back into the in-memory dict: drop a
        # required field + supply a bad port.
        data = json.loads(jf.read_text(encoding="utf-8"))
        data.pop("name", None)
        data["port"] = "not-an-int"
        jf.write_text(json.dumps(data), encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            loaded = store.load_all()

        assert p.id not in loaded  # the corrupt profile is skipped, not loaded
        log_text = "\n".join(r.getMessage() for r in caplog.records)
        # The decrypted credential must never reach the log.
        assert _SECRET not in log_text
        assert "ENABLE-XYZ" not in log_text
        # And the error path went through the scrubber (its distinctive
        # "validation error(s) [" form, not pydantic's default str).
        assert "CORRUPT FILE SKIPPED" in log_text
        assert "validation error(s) [" in log_text
