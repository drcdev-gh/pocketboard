# Organisation Audit

**Status:** done

## Goal

Add a read-only admin page at `/org-audit` that surfaces account mismatches between PocketID and Migadu: PocketID users without a linked Migadu mailbox, and Migadu mailboxes not linked to any PocketID user. This helps IT admins identify orphaned accounts from missed offboarding or unknown provisioning, without performing any automated fixes.

## Background

The organisation overview (`routes/overview.py`) already builds a complete in-memory cache of all PocketID members and their linked accounts, refreshed every 12h via `background_refresh_loop`. During that same cycle, `MigaduProvider` fetches and caches the full list of Migadu mailboxes (`_mailboxes`). The audit page can read both data structures without any new API calls on page load.

The `linkedAccounts` field on each cached member (list of `{system, identifier, confidence, match_reason}` dicts) already tells us whether a PocketID user has a Migadu match. The gap — mailboxes with no PocketID counterpart — requires comparing the full `_mailboxes` list against the set of Migadu identifiers matched across all members.

Access follows the same default-deny group pattern as all other restricted pages (see `ORG_OVERVIEW_GROUPS`, `AUDIT_LOG_GROUPS`).

## Scope

- New route `GET /org-audit`
- New env var `ORG_AUDIT_GROUPS` and `org_audit_groups` config property
- New `user_can_org_audit()` permission helper in `templating.py`
- New `all_migadu_mailboxes() -> list[dict]` helper in `services/linked_accounts/__init__.py` exposing the cached provider data
- New template `templates/org_audit.html` with two mismatch tables
- Nav link in `base.html` guarded by `user_can_org_audit`
- Register new router in `main.py`

## Out of scope

- No actions, deletions, or automated fixes from this page
- No whitelist/ignore mechanism for aliases or mailing lists (separate future ticket)
- Extending the audit to other linked account providers such as Mattermost (separate future ticket — but the structure of the route and template should make adding further provider sections straightforward)
- No new database tables

## Proposed approach

1. **`config.py`**: Add `org_audit_groups_raw = os.environ.get("ORG_AUDIT_GROUPS", "")` and an `org_audit_groups` property, mirroring `org_overview_groups`.
2. **`templating.py`**: Add `user_can_org_audit()` and register it as a template global.
3. **`services/linked_accounts/__init__.py`**: Add `all_migadu_mailboxes()` — iterates `_providers`, finds the `MigaduProvider` instance, returns its `_mailboxes` list.
4. **`routes/org_audit.py`**: New `APIRouter` with `GET /org-audit`. On request, reads `overview._cache` and `linked_accounts.all_migadu_mailboxes()` and computes:
   - `pocketid_no_migadu`: flat list of active (non-disabled) members with no `linkedAccounts` entry where `system == "Migadu"`
   - `migadu_no_pocketid`: mailboxes from `all_migadu_mailboxes()` whose `address` is not in the set of Migadu identifiers matched across all cached members
5. **`main.py`**: Include the new router.
6. **`templates/org_audit.html`**: Extends `base.html`. Two sections — one table per mismatch type. Displays member name/email and mailbox address respectively. Shows a warning banner if the cache is cold or linked account fetch errors are present.

## Related tickets

- Future: whitelist/ignore mechanism for aliases and mailing lists that will never have a PocketID account (not yet filed)
- Future: extend audit to additional linked account providers such as Mattermost (not yet filed)

## Acceptance criteria

- [ ] `/org-audit` returns 403 for users not in `ORG_AUDIT_GROUPS`; default-deny when env var is unset
- [ ] Page lists all active (non-disabled) PocketID users not matched to any Migadu mailbox in the current cache
- [ ] Page lists all Migadu mailboxes not matched to any PocketID user in the current cache
- [ ] No external API calls are made on page load — all data comes from the existing in-memory cache
- [ ] A notice is shown when the cache is cold or linked account fetch errors are present
- [ ] Nav link to `/org-audit` is shown only to users with `ORG_AUDIT_GROUPS` membership
- [ ] Tests cover: access control (403/200), correct mismatch computation for both directions, empty-state rendering
