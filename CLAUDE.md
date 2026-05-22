# Pocketboard — Claude instructions

## Start of every session

1. Read `docs/architecture.md` — it is the authoritative module/schema/flow reference.
2. If the user mentions a specific feature or ticket, read the relevant file in `docs/tickets/` before looking at source code.

## Running tests

Tests require Docker:

```bash
~/.docker/bin/docker compose -f docker-compose.test.yml run --rm test
```

Never use system Python (`/opt/homebrew/bin/python3`) for tests or package operations — dependencies are only installed inside the container.

## Ticket workflow

Tickets live in `docs/tickets/NNN-slug.md`. Use `/new-ticket` to create one interactively.

- Status values: `open` | `in-progress` | `done`
- Number tickets sequentially (pad to 3 digits: `001`, `002`, …)
- Keep the file after implementation — update status to `done`

When asked to implement a ticket:
1. Read `docs/architecture.md`
2. Read the ticket file
3. Read only the source files the ticket touches — avoid broad exploration
4. Implement and test
5. Review the code, specifically with a focus on security
6. Review the code for GDPR relevancy and prompt the user for potentially needed changes
7. Do a final review, check that the test coverage is good and commit

## Commit style

- Imperative subject line, present tense ("Add …", "Fix …", "Remove …")
- Body explains *why*, not *what*
- Always add `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

## Code conventions

- No comments unless the *why* is non-obvious
- No docstrings
- Async throughout (aiosqlite, httpx, aiosmtplib)
- New background tasks: add to `main.py` lifespan, follow the pattern in `services/reminders.py`
- New routes: add router to `main.py`, permission check via `templating.py` helper
- DB migrations: add `ALTER TABLE` block in `database.py:init_db`, guarded by column existence check
- Tests: mirror the patterns in `tests/` — async fixtures with `monkeypatch` on `DB_PATH`, `TestClient` for routes
