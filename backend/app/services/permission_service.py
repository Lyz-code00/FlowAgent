class PermissionDeniedError(PermissionError):
    pass


class PermissionService:
    def __init__(self, *, member_can_create_issue: bool = False) -> None:
        self.member_can_create_issue = member_can_create_issue

    def require(self, *, role: str, permission: str) -> None:
        if role not in {"member", "lead", "admin"}:
            raise PermissionDeniedError(f"unknown role '{role}'")
        if permission == "read":
            return
        if permission == "github_issue_write" and (
            role in {"lead", "admin"}
            or (role == "member" and self.member_can_create_issue)
        ):
            return
        raise PermissionDeniedError(
            f"role '{role}' is not allowed to perform '{permission}'"
        )
