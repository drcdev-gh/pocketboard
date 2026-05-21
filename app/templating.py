import hashlib
import json
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from app.config import config

templates = Jinja2Templates(directory="app/templates")

def _css_version() -> str:
    try:
        with open("app/static/style.css", "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:10]
    except Exception:
        return "1"

templates.env.globals["css_version"] = _css_version()


def user_can_audit(user: dict) -> bool:
    groups = config.audit_log_groups
    if not groups:
        return False  # default deny — must be explicitly configured
    return bool(set(user.get("groups", [])) & set(groups))


def user_can_clear_audit(user: dict) -> bool:
    groups = config.audit_log_clear_groups
    if not groups:
        return False
    return bool(set(user.get("groups", [])) & set(groups))


def user_can_overview(user: dict) -> bool:
    groups = config.org_overview_groups
    if not groups:
        return False
    return bool(set(user.get("groups", [])) & set(groups))


def user_can_edit_template(user: dict) -> bool:
    groups = config.email_template_groups
    if not groups:
        return False
    return bool(set(user.get("groups", [])) & set(groups))


def user_can_offboard(user: dict) -> bool:
    mappings = config.offboarding_mappings
    if not mappings:
        return False
    return bool(set(user.get("groups", [])) & set(mappings.keys()))


def _tojson_attr(value: object) -> Markup:
    """JSON-encode a value and HTML-escape double quotes so it's safe in double-quoted HTML attributes."""
    return Markup(json.dumps(value).replace('"', "&quot;"))


templates.env.filters["tojson_attr"] = _tojson_attr
templates.env.globals["pocketid_base_url"] = config.pocketid_base_url
templates.env.globals["user_can_audit"] = user_can_audit
templates.env.globals["user_can_clear_audit"] = user_can_clear_audit
templates.env.globals["user_can_overview"] = user_can_overview
templates.env.globals["user_can_edit_template"] = user_can_edit_template
templates.env.globals["user_can_offboard"] = user_can_offboard
