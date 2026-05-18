import httpx
from app.config import config


async def send(event: str, text: str, data: dict) -> None:
    """Post an audit event to the configured webhook URL.

    Payload structure:
      text  — Mattermost-compatible markdown summary (used by Mattermost incoming webhooks)
      event — machine-readable event name for other systems
      data  — structured event details

    Failures are silently swallowed so they never affect the main flow.
    """
    if not config.webhook_url:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                config.webhook_url,
                json={"text": text, "event": event, "data": data},
                timeout=5,
            )
    except Exception:
        pass
