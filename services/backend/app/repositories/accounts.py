from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select, text, update
from sqlalchemy.orm import Session

from app.core.domain import Role
from app.db.models import AdminInvitation, AppUser, AuditLog, TeacherApplication, UserSession, WsTicket


class AccountsRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_user(self, username: str, *, lock: bool = False) -> AppUser | None:
        query = select(AppUser).where(AppUser.username == username)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def find_users(self, usernames: set[str]) -> list[AppUser]:
        return list(self.session.scalars(select(AppUser).where(AppUser.username.in_(usernames))).all())

    def approval_statuses(self, user_ids: list[UUID]) -> dict[UUID, str]:
        return dict(self.session.execute(
            select(TeacherApplication.user_id, TeacherApplication.status)
            .where(TeacherApplication.user_id.in_(user_ids))
        ).all())

    def lock_users(self, user_ids: list[UUID]) -> dict[UUID, AppUser]:
        rows = self.session.scalars(
            select(AppUser).where(AppUser.id.in_(user_ids)).order_by(AppUser.id)
            .with_for_update().execution_options(populate_existing=True)
        ).all()
        return {user.id: user for user in rows}

    def identity_by_hash(self, token_hash: str):
        return self.session.execute(
            select(UserSession, AppUser, TeacherApplication.status)
            .join(AppUser, AppUser.id == UserSession.user_id)
            .outerjoin(TeacherApplication, TeacherApplication.user_id == AppUser.id)
            .where(UserSession.token_hash == token_hash)
        ).one_or_none()

    def identity(self, session_id: UUID, user_id: UUID) -> UserSession | None:
        return self.session.scalar(
            select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
        )

    def application_for(self, user_id: UUID) -> TeacherApplication | None:
        return self.session.scalar(select(TeacherApplication).where(TeacherApplication.user_id == user_id))

    def application(self, application_id: UUID, *, lock: bool = False) -> TeacherApplication | None:
        query = select(TeacherApplication).where(TeacherApplication.id == application_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def users(self):
        return self.session.execute(
            select(AppUser, TeacherApplication.status)
            .outerjoin(TeacherApplication, TeacherApplication.user_id == AppUser.id)
            .order_by(AppUser.created_at, AppUser.id)
        ).all()

    def applications(self) -> list[TeacherApplication]:
        return list(self.session.scalars(
            select(TeacherApplication).order_by(TeacherApplication.submitted_at.desc(), TeacherApplication.id.desc())
        ).all())

    def add_user(self, **values) -> AppUser:
        user = AppUser(**values)
        self.session.add(user)
        self.session.flush()
        return user

    def add_application(self, user_id: UUID) -> None:
        self.session.add(TeacherApplication(user_id=user_id))
        self.session.flush()

    def add_identity(self, **values) -> UserSession:
        identity = UserSession(**values)
        self.session.add(identity)
        self.session.flush()
        return identity

    def revoke(self, user_id: UUID, now: datetime, *, session_id: UUID | None = None) -> None:
        scope = [UserSession.user_id == user_id]
        if session_id is not None:
            scope.append(UserSession.id == session_id)
        identities = select(UserSession.id).where(*scope)
        self.session.execute(
            update(WsTicket).where(WsTicket.session_id.in_(identities), WsTicket.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        self.session.execute(
            update(UserSession).where(*scope, UserSession.revoked_at.is_(None)).values(revoked_at=now)
        )

    def add_invitation(self, **values) -> AdminInvitation:
        invitation = AdminInvitation(**values)
        self.session.add(invitation)
        self.session.flush()
        return invitation

    def invitation(self, token_hash: str) -> AdminInvitation | None:
        return self.session.scalar(select(AdminInvitation).where(AdminInvitation.token_hash == token_hash).with_for_update())

    def audit(self, action: str, actor_id: UUID | None, target_id: UUID) -> None:
        self.session.add(AuditLog(action=action, actor_id=actor_id, target_id=target_id))

    def lock_bootstrap(self) -> None:
        self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 742031165})

    def has_admin(self) -> bool:
        return bool(self.session.scalar(select(exists().where(AppUser.role == Role.ADMIN))))
