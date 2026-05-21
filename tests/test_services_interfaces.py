"""
Verifies that concrete provider implementations satisfy their ABCs,
and that the module-level _provider instances are correctly typed.
"""

import inspect
from app.services.interfaces import IdentityProvider, MailboxProvider
from app.services.pocketid import PocketIDIdentityProvider, _provider as pid_provider
from app.services.migadu import MigaduMailboxProvider, _provider as migadu_provider


# ---------------------------------------------------------------------------
# ABC conformance: instantiation + isinstance
# ---------------------------------------------------------------------------

def test_pocketid_provider_is_instance_of_identity_provider():
    assert isinstance(PocketIDIdentityProvider(), IdentityProvider)

def test_migadu_provider_is_instance_of_mailbox_provider():
    assert isinstance(MigaduMailboxProvider(), MailboxProvider)

def test_module_level_pid_provider_is_identity_provider():
    assert isinstance(pid_provider, IdentityProvider)

def test_module_level_migadu_provider_is_mailbox_provider():
    assert isinstance(migadu_provider, MailboxProvider)


# ---------------------------------------------------------------------------
# Method presence: every abstract method in the ABC must be implemented
# ---------------------------------------------------------------------------

def _abstract_methods(cls) -> set[str]:
    return {
        name
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction)
        if getattr(method, "__isabstractmethod__", False)
    }

def _concrete_methods(cls) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
    }

def test_pocketid_implements_all_identity_provider_methods():
    missing = _abstract_methods(IdentityProvider) - _concrete_methods(PocketIDIdentityProvider)
    assert not missing, f"PocketIDIdentityProvider is missing: {missing}"

def test_migadu_implements_all_mailbox_provider_methods():
    missing = _abstract_methods(MailboxProvider) - _concrete_methods(MigaduMailboxProvider)
    assert not missing, f"MigaduMailboxProvider is missing: {missing}"


# ---------------------------------------------------------------------------
# Module-level wrappers: every abstract method has a matching module-level function
# ---------------------------------------------------------------------------

def test_pocketid_module_exposes_wrapper_for_every_interface_method():
    import app.services.pocketid as pid_module
    missing = [
        name for name in _abstract_methods(IdentityProvider)
        if not callable(getattr(pid_module, name, None))
    ]
    assert not missing, f"pocketid module is missing wrappers for: {missing}"

def test_migadu_module_exposes_wrapper_for_every_interface_method():
    import app.services.migadu as migadu_module
    missing = [
        name for name in _abstract_methods(MailboxProvider)
        if not callable(getattr(migadu_module, name, None))
    ]
    assert not missing, f"migadu module is missing wrappers for: {missing}"


# ---------------------------------------------------------------------------
# Signature compatibility: wrapper functions match the interface signatures
# ---------------------------------------------------------------------------

def _sig(fn) -> inspect.Signature:
    return inspect.signature(fn)

def test_pocketid_wrapper_signatures_match_interface():
    import app.services.pocketid as pid_module
    for name in _abstract_methods(IdentityProvider):
        interface_fn = getattr(IdentityProvider, name)
        wrapper_fn = getattr(pid_module, name)
        interface_params = set(_sig(interface_fn).parameters) - {"self"}
        wrapper_params = set(_sig(wrapper_fn).parameters)
        assert interface_params == wrapper_params, (
            f"pocketid.{name}: interface params {interface_params} "
            f"!= wrapper params {wrapper_params}"
        )

def test_migadu_wrapper_signatures_match_interface():
    import app.services.migadu as migadu_module
    for name in _abstract_methods(MailboxProvider):
        interface_fn = getattr(MailboxProvider, name)
        wrapper_fn = getattr(migadu_module, name)
        interface_params = set(_sig(interface_fn).parameters) - {"self"}
        wrapper_params = set(_sig(wrapper_fn).parameters)
        assert interface_params == wrapper_params, (
            f"migadu.{name}: interface params {interface_params} "
            f"!= wrapper params {wrapper_params}"
        )
