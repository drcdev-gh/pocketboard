import os
import re
from typing import Dict, List


class Config:
    def __init__(self):
        self.demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

        self.identity_provider = os.environ.get("IDENTITY_PROVIDER", "pocketid")
        self.identity_base_url = os.environ["IDENTITY_BASE_URL"].rstrip("/")
        self.identity_api_key = os.environ["IDENTITY_API_KEY"]
        self.identity_client_id = os.environ["IDENTITY_CLIENT_ID"]
        self.identity_client_secret = os.environ["IDENTITY_CLIENT_SECRET"]

        self.mailbox_provider = os.environ.get("MAILBOX_PROVIDER", "migadu")
        self.mailbox_api_user = os.environ["MAILBOX_API_USER"]
        self.mailbox_api_key = os.environ["MAILBOX_API_KEY"]
        self.mailbox_domain = os.environ["MAILBOX_DOMAIN"]

        self.smtp_host = os.environ.get("SMTP_HOST", "smtp.migadu.com")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ["SMTP_USER"]
        self.smtp_password = os.environ["SMTP_PASSWORD"]
        self.smtp_from = os.environ.get("SMTP_FROM", os.environ["SMTP_USER"])
        self.smtp_from_name = os.environ.get("SMTP_FROM_NAME", "Organisation Onboarding")

        self.app_secret_key = os.environ["APP_SECRET_KEY"]
        self.app_base_url = os.environ["APP_BASE_URL"].rstrip("/")

        self.rate_limit_per_user_per_day = int(os.environ.get("RATE_LIMIT_PER_USER_PER_DAY", "10"))
        self.rate_limit_global_per_day = int(os.environ.get("RATE_LIMIT_GLOBAL_PER_DAY", "100"))

        self.offboarding_rate_limit_per_user_per_day = int(os.environ.get("OFFBOARDING_RATE_LIMIT_PER_USER_PER_DAY", "5"))
        self.offboarding_rate_limit_global_per_day = int(os.environ.get("OFFBOARDING_RATE_LIMIT_GLOBAL_PER_DAY", "20"))

        # e.g. "168h" (7 days); PocketID accepts Go duration strings
        self.invite_ttl = os.environ.get("INVITE_TTL", "168h")
        self.invite_usage_limit = int(os.environ.get("INVITE_USAGE_LIMIT", "1"))

        self.group_mappings_raw = os.environ.get("GROUP_MAPPINGS", "")
        self.audit_log_groups_raw = os.environ.get("AUDIT_LOG_GROUPS", "")
        self.audit_log_clear_groups_raw = os.environ.get("AUDIT_LOG_CLEAR_GROUPS", "")
        self.org_overview_groups_raw = os.environ.get("ORG_OVERVIEW_GROUPS", "")
        self.default_selected_groups_raw = os.environ.get("DEFAULT_SELECTED_GROUPS", "")
        self.email_template_groups_raw = os.environ.get("EMAIL_TEMPLATE_GROUPS", "")
        self.badge_mappings_raw = os.environ.get("BADGE_MAPPINGS", "")
        self.webhook_url = os.environ.get("WEBHOOK_URL", "")

        self.mattermost_url = os.environ.get("MATTERMOST_URL", "").rstrip("/")
        self.mattermost_token = os.environ.get("MATTERMOST_TOKEN", "")
        self.linked_accounts_it_email = os.environ.get("LINKED_ACCOUNTS_IT_EMAIL", "")
        self.offboarding_mappings_raw = os.environ.get("OFFBOARDING_MAPPINGS", "")
        self.org_audit_groups_raw = os.environ.get("ORG_AUDIT_GROUPS", "")

    @property
    def badge_mappings(self) -> Dict[str, str]:
        """Parse BADGE_MAPPINGS: 'Group Name=BADGE;Another=BADGE2' → {group: badge}"""
        result: Dict[str, str] = {}
        if not self.badge_mappings_raw:
            return result
        for entry in self.badge_mappings_raw.split(";"):
            entry = entry.strip()
            if "=" not in entry:
                continue
            group, badge = entry.split("=", 1)
            result[group.strip()] = badge.strip()
        return result

    @property
    def email_template_groups(self) -> List[str]:
        if not self.email_template_groups_raw:
            return []
        return [g.strip() for g in self.email_template_groups_raw.split(",") if g.strip()]

    @property
    def invite_ttl_seconds(self) -> int:
        """Parse Go duration string (e.g. '168h', '30m', '1h30m') into seconds."""
        total = sum(
            int(v) * {"h": 3600, "m": 60, "s": 1}[u]
            for v, u in re.findall(r"(\d+)([hms])", self.invite_ttl)
        )
        return total or 7 * 86400  # fallback: 7 days

    @property
    def audit_log_groups(self) -> List[str]:
        if not self.audit_log_groups_raw:
            return []
        return [g.strip() for g in self.audit_log_groups_raw.split(",") if g.strip()]

    @property
    def default_selected_groups(self) -> List[str]:
        if not self.default_selected_groups_raw:
            return []
        return [g.strip() for g in self.default_selected_groups_raw.split(",") if g.strip()]

    @property
    def org_overview_groups(self) -> List[str]:
        if not self.org_overview_groups_raw:
            return []
        return [g.strip() for g in self.org_overview_groups_raw.split(",") if g.strip()]

    @property
    def org_audit_groups(self) -> List[str]:
        if not self.org_audit_groups_raw:
            return []
        return [g.strip() for g in self.org_audit_groups_raw.split(",") if g.strip()]

    @property
    def audit_log_clear_groups(self) -> List[str]:
        if not self.audit_log_clear_groups_raw:
            return []
        return [g.strip() for g in self.audit_log_clear_groups_raw.split(",") if g.strip()]

    @staticmethod
    def _parse_mappings(raw: str) -> Dict[str, List[str]]:
        """Parse 'CallerGroup=Target1,Target2;OtherGroup=Target3' into a dict."""
        result: Dict[str, List[str]] = {}
        if not raw:
            return result
        for entry in raw.split(";"):
            entry = entry.strip()
            if "=" not in entry:
                continue
            caller_group, targets = entry.split("=", 1)
            result[caller_group.strip()] = [t.strip() for t in targets.split(",") if t.strip()]
        return result

    @staticmethod
    def _allowed_from_mappings(
        mappings: Dict[str, List[str]],
        user_groups: List[str],
    ) -> List[str]:
        """Return deduplicated target list for the given caller groups, in definition order."""
        user_group_set = set(user_groups)
        seen: set = set()
        allowed: List[str] = []
        for caller_group, targets in mappings.items():
            if caller_group in user_group_set:
                for target in targets:
                    if target not in seen:
                        seen.add(target)
                        allowed.append(target)
        return allowed

    @property
    def group_mappings(self) -> Dict[str, List[str]]:
        return self._parse_mappings(self.group_mappings_raw)

    @property
    def offboarding_mappings(self) -> Dict[str, List[str]]:
        return self._parse_mappings(self.offboarding_mappings_raw)

    def allowed_target_groups(self, user_groups: List[str]) -> List[str]:
        return self._allowed_from_mappings(self.group_mappings, user_groups)

    def allowed_offboarding_targets(self, user_groups: List[str]) -> List[str]:
        return self._allowed_from_mappings(self.offboarding_mappings, user_groups)


config = Config()
