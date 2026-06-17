"""
Role-Based Access Control (RBAC) utilities.
Roles: admin > editor > viewer
"""
from fastapi import Depends, HTTPException, status

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.models.user import UserRole
from app.repositories.user_repo import UserRepository

ROLE_HIERARCHY = {
    UserRole.admin: 3,
    UserRole.editor: 2,
    UserRole.viewer: 1,
}


def require_role(minimum_role: UserRole):
    """FastAPI dependency factory — raises 403 if user's role is below minimum."""
    async def _check(user_id: CurrentUserIdDep, db: DbDep):
        repo = UserRepository(db)
        user = await repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if ROLE_HIERARCHY.get(user.role, 0) < ROLE_HIERARCHY[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum_role.value} role or higher",
            )
        return user

    return _check


RequireAdmin = Depends(require_role(UserRole.admin))
RequireEditor = Depends(require_role(UserRole.editor))
RequireViewer = Depends(require_role(UserRole.viewer))
