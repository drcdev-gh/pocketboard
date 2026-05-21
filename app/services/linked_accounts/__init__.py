"""
Linked accounts registry.

Usage:
    await linked_accounts.refresh()          # called once per cache cycle
    accounts = await linked_accounts.for_member(member_dict)
    errors   = linked_accounts.get_fetch_errors()
"""

from dataclasses import asdict

from app.services.linked_accounts.base import LinkedAccount, _CONFIDENCE_ORDER
from app.services.linked_accounts.providers.audit_log import AuditLogProvider
from app.services.linked_accounts.providers.migadu import MigaduProvider
from app.services.linked_accounts.providers.mattermost import MattermostProvider

_providers = [AuditLogProvider(), MigaduProvider(), MattermostProvider()]
_fetch_errors: list[str] = []


async def refresh() -> None:
    """Bulk-fetch all enabled providers. Failures are collected, not raised."""
    global _fetch_errors
    errors: list[str] = []
    for p in _providers:
        if p.enabled:
            try:
                await p.fetch_all()
            except Exception as exc:
                errors.append(f"{p.name}: {exc}")
    _fetch_errors = errors


def get_fetch_errors() -> list[str]:
    return list(_fetch_errors)


async def for_member(member: dict) -> list[LinkedAccount]:
    """
    Return deduplicated linked accounts for one PocketID member dict.
    When two providers find the same identifier, the higher-confidence entry wins.
    Individual provider match failures are silently skipped.
    """
    results: list[LinkedAccount] = []
    seen: dict[str, int] = {}  # identifier → index in results

    for p in _providers:
        if not p.enabled:
            continue
        known_identifiers = set(seen.keys())
        try:
            new_accounts = await p.match(member, known_identifiers)
        except Exception:
            continue
        for acct in new_accounts:
            if acct.identifier in seen:
                idx = seen[acct.identifier]
                existing = results[idx]
                if _CONFIDENCE_ORDER[acct.confidence] < _CONFIDENCE_ORDER[existing.confidence]:
                    results[idx] = acct
            else:
                seen[acct.identifier] = len(results)
                results.append(acct)

    return results


def as_serializable(accounts: list[LinkedAccount]) -> list[dict]:
    return [asdict(a) for a in accounts]
