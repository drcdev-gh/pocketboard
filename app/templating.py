from fastapi.templating import Jinja2Templates
from app.config import config

templates = Jinja2Templates(directory="app/templates")


def _user_can_audit(user: dict) -> bool:
    groups = config.audit_log_groups
    if not groups:
        return True
    return bool(set(user.get("groups", [])) & set(groups))


templates.env.globals["user_can_audit"] = _user_can_audit
