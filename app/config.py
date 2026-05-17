import os
from typing import Dict, List


class Config:
    def __init__(self):
        self.pocketid_base_url = os.environ["POCKETID_BASE_URL"].rstrip("/")
        self.pocketid_api_key = os.environ["POCKETID_API_KEY"]
        self.pocketid_client_id = os.environ["POCKETID_CLIENT_ID"]
        self.pocketid_client_secret = os.environ["POCKETID_CLIENT_SECRET"]

        self.migadu_api_email = os.environ["MIGADU_API_EMAIL"]
        self.migadu_api_key = os.environ["MIGADU_API_KEY"]
        self.migadu_domain = os.environ["MIGADU_DOMAIN"]

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

        # e.g. "168h" (7 days); PocketID accepts Go duration strings
        self.invite_ttl = os.environ.get("INVITE_TTL", "168h")
        self.invite_usage_limit = int(os.environ.get("INVITE_USAGE_LIMIT", "1"))

        self.group_mappings_raw = os.environ.get("GROUP_MAPPINGS", "")
        self.onboarding_template = os.environ.get("ONBOARDING_TEMPLATE", "")
        self.audit_log_groups_raw = os.environ.get("AUDIT_LOG_GROUPS", "")
        self.audit_log_clear_groups_raw = os.environ.get("AUDIT_LOG_CLEAR_GROUPS", "")

    @property
    def audit_log_groups(self) -> List[str]:
        if not self.audit_log_groups_raw:
            return []
        return [g.strip() for g in self.audit_log_groups_raw.split(",") if g.strip()]

    @property
    def audit_log_clear_groups(self) -> List[str]:
        if not self.audit_log_clear_groups_raw:
            return []
        return [g.strip() for g in self.audit_log_clear_groups_raw.split(",") if g.strip()]

    @property
    def group_mappings(self) -> Dict[str, List[str]]:
        """
        Parse GROUP_MAPPINGS env var.
        Format: caller_group1=target1,target2;caller_group2=target3,target4
        """
        result: Dict[str, List[str]] = {}
        if not self.group_mappings_raw:
            return result
        for entry in self.group_mappings_raw.split(";"):
            entry = entry.strip()
            if "=" not in entry:
                continue
            caller_group, targets = entry.split("=", 1)
            result[caller_group.strip()] = [t.strip() for t in targets.split(",") if t.strip()]
        return result

    def allowed_target_groups(self, user_groups: List[str]) -> List[str]:
        """Return union of all target groups allowed for the given user groups."""
        mappings = self.group_mappings
        allowed: set = set()
        for g in user_groups:
            allowed.update(mappings.get(g, []))
        return sorted(allowed)


config = Config()
