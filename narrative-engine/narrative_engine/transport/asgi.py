"""Raw ASGI helpers shared by the engine's admin routes."""
import hmac
import json


def bearer(admin_token):
    """The expected Authorization header, or None when no token is set (local stack)."""
    return f"Bearer {admin_token}".encode() if admin_token else None


def authorized(scope, expected):
    return not expected or hmac.compare_digest(dict(scope["headers"]).get(b"authorization", b""), expected)


async def respond(send, status, body):
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})


async def read_body(receive):
    body, more = b"", True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = message.get("more_body", False)
    return body
