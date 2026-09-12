import hmac

from fastapi import Header, HTTPException, Request, status


async def require_admin(
    request: Request,
    x_flowagent_admin_token: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.admin_api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin API token is not configured",
        )
    if not x_flowagent_admin_token or not hmac.compare_digest(
        x_flowagent_admin_token, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin token",
        )
