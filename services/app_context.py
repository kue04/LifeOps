from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header


ROLES = {"user", "operator_admin"}


@dataclass(frozen=True)
class AppContext:
    user_id: str
    role: str
    user_name: str

    @property
    def can_view_trace(self) -> bool:
        return self.role == "operator_admin"

    @property
    def can_view_audit(self) -> bool:
        return self.role == "operator_admin"


def get_app_context(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
    x_user_name: Annotated[str | None, Header(alias="X-User-Name")] = None,
) -> AppContext:
    role = (x_user_role or "user").strip().lower()
    if role == "admin":
        role = "operator_admin"
    if role not in ROLES:
        role = "user"
    return AppContext(
        user_id=(x_user_id or "demo.user").strip() or "demo.user",
        role=role,
        user_name=(x_user_name or "Demo User").strip() or "Demo User",
    )
