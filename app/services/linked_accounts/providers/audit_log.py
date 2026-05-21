from app.database import get_db
from app.services.linked_accounts.base import LinkedAccount, LinkedAccountsProvider


class AuditLogProvider(LinkedAccountsProvider):
    @property
    def name(self) -> str:
        return "AuditLog"

    @property
    def enabled(self) -> bool:
        return True

    async def fetch_all(self) -> None:
        pass  # DB is always current; no bulk fetch needed

    async def match(
        self,
        member: dict,
        known_identifiers: set[str],
    ) -> list[LinkedAccount]:
        email = (member.get("email") or "").strip()
        if not email:
            return []
        async with get_db() as db:
            async with db.execute(
                """SELECT DISTINCT org_email FROM audit_log
                   WHERE invitee_email = ?
                     AND status NOT IN ('log_cleared', 'template_changed')
                     AND org_email != ''""",
                (email,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            LinkedAccount(
                system="Migadu",
                identifier=row[0],
                confidence="confirmed",
                match_reason="audit log",
            )
            for row in rows
            if row[0] and row[0] not in known_identifiers
        ]
