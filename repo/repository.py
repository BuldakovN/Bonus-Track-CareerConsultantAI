from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, delete, event, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


JsonLike = Union[Dict[str, Any], List[Any]]
DEFAULT_SQLITE_FILENAME = "db_app.sqlite3"


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@event.listens_for(Engine, "connect")
def _sqlite_pragma(dbapi_conn, _connection_record) -> None:
    if dbapi_conn.__class__.__module__.startswith("sqlite"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class AppUser(Base):
    """Внутренний пользователь системы (не привязан к конкретному мессенджеру)."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UserIdentity(Base):
    """Связь внешнего аккаунта (Telegram, VK, …) с app_user.id."""

    __tablename__ = "user_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("provider", "external_user_id", name="uq_user_identity_provider_external"),)


class WhoUser(Base):
    """Структурированная личная информация (этапы who / about)."""

    __tablename__ = "who_user"

    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    who_story: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    about_story: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    user_display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    recommended_professions_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class UserDialogState(Base):
    """Текущее состояние диалога (фаза и опциональный JSON контекста)."""

    __tablename__ = "user_dialog_state"

    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    dialog_phase: Mapped[str] = mapped_column(String(32), nullable=False, default="who")
    context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Conversation(Base):
    """История сообщений диалога."""

    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_txt: Mapped[str] = mapped_column(Text, nullable=False)
    message_from: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    dialog_phase: Mapped[str] = mapped_column(String(32), nullable=False, default="who")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UserMetadata(Base):
    """Дополнительные данные (рекомендации, тесты и т.д.) — JSON."""

    __tablename__ = "user_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@dataclass(frozen=True)
class RepositoryConfig:
    db_url: str = f"sqlite:///{DEFAULT_SQLITE_FILENAME}"
    echo: bool = False


class Repository:
    def __init__(self, config: RepositoryConfig = RepositoryConfig()):
        self._engine = create_engine(config.db_url, echo=config.echo, future=True)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, autocommit=False, future=True)

    def create_schema(self) -> None:
        if self._engine.dialect.name == "sqlite":
            self._sqlite_migrate_legacy_if_needed()
        Base.metadata.create_all(self._engine)
        if self._engine.dialect.name == "sqlite":
            self._sqlite_add_who_user_extra_columns()

    def _sqlite_add_who_user_extra_columns(self) -> None:
        """ALTER для уже существующей таблицы who_user (create_all не добавляет колонки)."""
        engine = self._engine
        insp = inspect(engine)
        if not insp.has_table("who_user"):
            return
        col_names = {c["name"] for c in insp.get_columns("who_user")}
        with engine.begin() as conn:
            if "user_display_name" not in col_names:
                conn.execute(text("ALTER TABLE who_user ADD COLUMN user_display_name VARCHAR(256)"))
            if "recommended_professions_json" not in col_names:
                conn.execute(text("ALTER TABLE who_user ADD COLUMN recommended_professions_json TEXT"))

    def _sqlite_migrate_legacy_if_needed(self) -> None:
        """
        Старая схема: user_metadata(user_id TEXT, ...), conversation_history(user_id, ...).
        create_all не меняет существующие таблицы — без миграции INSERT падает (нет app_user_id).
        """
        engine = self._engine
        insp = inspect(engine)
        if not insp.has_table("user_metadata"):
            return
        col_names = {c["name"] for c in insp.get_columns("user_metadata")}
        if "app_user_id" in col_names:
            return
        if "user_id" not in col_names:
            return

        legacy_meta: List[Dict[str, Any]] = []
        with engine.connect() as conn:
            for row in conn.execute(text("SELECT id, user_id, metadata_json, created_at FROM user_metadata")):
                legacy_meta.append(dict(row._mapping))

        legacy_conv: List[Dict[str, Any]] = []
        if insp.has_table("conversation_history"):
            with engine.connect() as conn:
                for row in conn.execute(
                    text(
                        "SELECT user_id, message_txt, message_from, user_state, created_at "
                        "FROM conversation_history"
                    )
                ):
                    legacy_conv.append(dict(row._mapping))

        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE user_metadata RENAME TO user_metadata_legacy"))
            if insp.has_table("conversation_history"):
                conn.execute(text("ALTER TABLE conversation_history RENAME TO conversation_history_legacy"))

        Base.metadata.create_all(engine)

        ext_to_app: Dict[str, int] = {}
        with self._Session() as s:
            for row in s.execute(select(UserIdentity.external_user_id, UserIdentity.app_user_id)):
                ext_to_app[str(row[0])] = int(row[1])

        by_user: Dict[str, List[Dict[str, Any]]] = {}
        for row in legacy_meta:
            uid = str(row["user_id"])
            by_user.setdefault(uid, []).append(row)

        def _parse_dt(val: Any) -> datetime:
            if isinstance(val, datetime):
                return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            if isinstance(val, str):
                try:
                    v = val.replace("Z", "+00:00")
                    return datetime.fromisoformat(v)
                except ValueError:
                    pass
            return utcnow()

        with self._Session() as s:
            conv_only_uids = (
                {str(c["user_id"]) for c in legacy_conv} - set(by_user.keys()) - set(ext_to_app.keys())
            )
            for uid in conv_only_uids:
                au = AppUser(created_at=utcnow())
                s.add(au)
                s.flush()
                s.add(
                    UserIdentity(
                        app_user_id=au.id,
                        provider="telegram",
                        external_user_id=uid,
                        created_at=utcnow(),
                    )
                )
                ext_to_app[uid] = au.id

            for uid, rows in by_user.items():
                rows.sort(key=lambda x: int(x["id"]), reverse=True)
                latest = rows[0]
                raw_json = latest["metadata_json"]
                try:
                    payload = self._load_json(raw_json) if isinstance(raw_json, str) else {}
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                inner = payload.get("user_metadata")
                if not isinstance(inner, dict):
                    inner = {}

                if uid in ext_to_app:
                    aid = ext_to_app[uid]
                else:
                    au = AppUser(created_at=_parse_dt(latest.get("created_at")))
                    s.add(au)
                    s.flush()
                    s.add(
                        UserIdentity(
                            app_user_id=au.id,
                            provider="telegram",
                            external_user_id=uid,
                            created_at=utcnow(),
                        )
                    )
                    aid = au.id
                    ext_to_app[uid] = aid

                has_meta = s.execute(
                    select(UserMetadata.id)
                    .where(UserMetadata.app_user_id == aid)
                    .limit(1)
                ).scalar_one_or_none()
                if has_meta is None:
                    snap = {
                        "user_state": payload.get("user_state", "who"),
                        "user_type": payload.get("user_type"),
                        "user_metadata": {
                            k: v
                            for k, v in inner.items()
                            if k not in ("who_user", "about_user")
                        },
                    }
                    s.add(
                        UserMetadata(
                            app_user_id=aid,
                            metadata_json=self._dump_json(snap),
                            created_at=_parse_dt(latest.get("created_at")),
                        )
                    )

                who_s = inner.get("who_user")
                ab_s = inner.get("about_user")
                utype = payload.get("user_type")
                if who_s is not None or ab_s is not None or utype is not None:
                    existing_w = s.get(WhoUser, aid)
                    if existing_w is None:
                        s.add(
                            WhoUser(
                                app_user_id=aid,
                                who_story=who_s if isinstance(who_s, str) else None,
                                about_story=ab_s if isinstance(ab_s, str) else None,
                                user_type=utype if isinstance(utype, str) else None,
                                updated_at=utcnow(),
                            )
                        )
                    else:
                        if isinstance(who_s, str):
                            existing_w.who_story = who_s
                        if isinstance(ab_s, str):
                            existing_w.about_story = ab_s
                        if isinstance(utype, str):
                            existing_w.user_type = utype
                        existing_w.updated_at = utcnow()

                phase = str(payload.get("user_state") or "who")
                existing_d = s.get(UserDialogState, aid)
                if existing_d is None:
                    s.add(
                        UserDialogState(
                            app_user_id=aid,
                            dialog_phase=phase,
                            context_json=None,
                            updated_at=utcnow(),
                        )
                    )
                else:
                    existing_d.dialog_phase = phase
                    existing_d.updated_at = utcnow()

            for c in legacy_conv:
                uid = str(c["user_id"])
                aid = ext_to_app.get(uid)
                if aid is None:
                    continue
                s.add(
                    Conversation(
                        app_user_id=aid,
                        message_txt=c["message_txt"],
                        message_from=c["message_from"],
                        dialog_phase=str(c.get("user_state") or "who"),
                        created_at=_parse_dt(c.get("created_at")),
                    )
                )
            s.commit()

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS user_metadata_legacy"))
            conn.execute(text("DROP TABLE IF EXISTS conversation_history_legacy"))

    @staticmethod
    def _dump_json(payload: JsonLike) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _load_json(data_json: str) -> JsonLike:
        return json.loads(data_json)

    # ---------- identity / app_user ----------

    def get_app_user_id(self, provider: str, external_user_id: str) -> Optional[int]:
        with self._Session() as s:
            stmt = select(UserIdentity.app_user_id).where(
                UserIdentity.provider == provider,
                UserIdentity.external_user_id == str(external_user_id),
            )
            return s.execute(stmt).scalar_one_or_none()

    def get_or_create_app_user(self, provider: str, external_user_id: str) -> int:
        existing = self.get_app_user_id(provider, external_user_id)
        if existing is not None:
            return existing
        with self._Session() as s:
            stmt = select(UserIdentity.app_user_id).where(
                UserIdentity.provider == provider,
                UserIdentity.external_user_id == str(external_user_id),
            )
            found = s.execute(stmt).scalar_one_or_none()
            if found is not None:
                return found
            au = AppUser()
            s.add(au)
            s.flush()
            s.add(
                UserIdentity(
                    app_user_id=au.id,
                    provider=provider,
                    external_user_id=str(external_user_id),
                )
            )
            s.commit()
            return au.id

    def delete_app_user(self, app_user_id: int) -> None:
        with self._Session() as s:
            s.execute(delete(AppUser).where(AppUser.id == app_user_id))
            s.commit()

    def delete_user_by_identity(self, provider: str, external_user_id: str) -> int:
        aid = self.get_app_user_id(provider, external_user_id)
        if aid is None:
            return 0
        self.delete_app_user(aid)
        return 1

    # ---------- who_user ----------

    def upsert_who_user(
        self,
        app_user_id: int,
        who_story: Optional[str],
        about_story: Optional[str],
        user_type: Optional[str],
        user_display_name: Optional[str] = None,
        update_display_name: bool = False,
        recommended_professions_json: Optional[str] = None,
        update_recommended_professions: bool = False,
    ) -> None:
        now = utcnow()
        with self._Session() as s:
            row = s.get(WhoUser, app_user_id)
            if row is None:
                row = WhoUser(app_user_id=app_user_id)
                s.add(row)
            row.who_story = who_story
            row.about_story = about_story
            row.user_type = user_type
            if update_display_name:
                row.user_display_name = (user_display_name[:256] if user_display_name else None)
            if update_recommended_professions:
                row.recommended_professions_json = recommended_professions_json
            row.updated_at = now
            s.commit()

    def get_who_user(self, app_user_id: int) -> Dict[str, Any]:
        with self._Session() as s:
            row = s.get(WhoUser, app_user_id)
            if row is None:
                return {}
            return {
                "who_story": row.who_story,
                "about_story": row.about_story,
                "user_type": row.user_type,
                "user_display_name": row.user_display_name,
                "recommended_professions_json": row.recommended_professions_json,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

    # ---------- dialog state ----------

    def upsert_dialog_state(
        self,
        app_user_id: int,
        dialog_phase: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = utcnow()
        ctx = self._dump_json(context) if context is not None else None
        with self._Session() as s:
            row = s.get(UserDialogState, app_user_id)
            if row is None:
                row = UserDialogState(app_user_id=app_user_id)
                s.add(row)
            row.dialog_phase = dialog_phase
            row.context_json = ctx
            row.updated_at = now
            s.commit()

    def get_dialog_state(self, app_user_id: int) -> Dict[str, Any]:
        with self._Session() as s:
            row = s.get(UserDialogState, app_user_id)
            if row is None:
                return {}
            ctx = None
            if row.context_json:
                try:
                    ctx = self._load_json(row.context_json)
                except json.JSONDecodeError:
                    ctx = None
            return {
                "dialog_phase": row.dialog_phase,
                "context": ctx,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

    # ---------- conversation ----------

    def get_conversation(self, app_user_id: int) -> List[Dict[str, str]]:
        with self._Session() as s:
            stmt = (
                select(Conversation)
                .where(Conversation.app_user_id == app_user_id)
                .order_by(Conversation.created_at.asc(), Conversation.id.asc())
            )
            rows = s.execute(stmt).scalars().all()
            return [{"role": m.message_from, "text": m.message_txt} for m in rows]

    def replace_conversation(
        self,
        app_user_id: int,
        messages: List[Dict[str, str]],
        dialog_phase: str,
    ) -> None:
        now = utcnow()
        with self._Session() as s:
            s.execute(delete(Conversation).where(Conversation.app_user_id == app_user_id))
            for msg in messages:
                role = msg.get("role", "user")
                text = msg.get("text", "")
                s.add(
                    Conversation(
                        app_user_id=app_user_id,
                        message_txt=text,
                        message_from=role,
                        dialog_phase=dialog_phase,
                        created_at=now,
                    )
                )
            s.commit()

    # ---------- user_metadata (JSON snapshot) ----------

    def save_metadata(self, app_user_id: int, payload: dict) -> int:
        with self._Session() as s:
            row = UserMetadata(
                app_user_id=app_user_id,
                metadata_json=self._dump_json(payload),
                created_at=datetime.now(timezone.utc),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def get_latest_metadata_snapshot(self, app_user_id: int) -> dict:
        """Последний JSON-снимок { user_state, user_type, user_metadata }."""
        with self._Session() as s:
            stmt = (
                select(UserMetadata)
                .where(UserMetadata.app_user_id == app_user_id)
                .order_by(UserMetadata.created_at.desc(), UserMetadata.id.desc())
                .limit(1)
            )
            row = s.execute(stmt).scalar_one_or_none()
            if row is None:
                return {}
            data = self._load_json(row.metadata_json)
            return data if isinstance(data, dict) else {}

    def _clear_app_user_data(self, app_user_id: int) -> None:
        with self._Session() as s:
            s.execute(delete(UserMetadata).where(UserMetadata.app_user_id == app_user_id))
            s.execute(delete(Conversation).where(Conversation.app_user_id == app_user_id))
            s.execute(delete(WhoUser).where(WhoUser.app_user_id == app_user_id))
            s.execute(delete(UserDialogState).where(UserDialogState.app_user_id == app_user_id))
            s.commit()

    def clear_identity_session(self, provider: str, external_user_id: str) -> int:
        """Очистить сессию: сохраняются app_user и привязка identity."""
        aid = self.get_app_user_id(provider, external_user_id)
        if aid is None:
            return 0
        self._clear_app_user_data(aid)
        return 1

    # ---------- high-level session (для CRUD API) ----------

    def get_session_bundle(self, provider: str, external_user_id: str) -> Dict[str, Any]:
        aid = self.get_app_user_id(provider, external_user_id)
        if aid is None:
            return {
                "app_user_id": None,
                "user_state": "who",
                "user_type": None,
                "user_metadata": {},
                "conversation_history": [],
            }

        who = self.get_who_user(aid)
        dstate = self.get_dialog_state(aid)
        snap = self.get_latest_metadata_snapshot(aid)

        inner_meta = dict(snap.get("user_metadata") or {})
        if who.get("who_story") is not None:
            inner_meta["who_user"] = who["who_story"]
        if who.get("about_story") is not None:
            inner_meta["about_user"] = who["about_story"]
        if who.get("user_display_name"):
            inner_meta["user_display_name"] = who["user_display_name"]

        user_state = dstate.get("dialog_phase") or snap.get("user_state") or "who"
        user_type = who.get("user_type")
        if user_type is None:
            user_type = snap.get("user_type")

        return {
            "app_user_id": aid,
            "user_state": user_state,
            "user_type": user_type,
            "user_metadata": inner_meta,
            "conversation_history": self.get_conversation(aid),
        }

    def put_session_bundle(
        self,
        provider: str,
        external_user_id: str,
        user_state: str,
        user_type: Optional[str],
        user_metadata: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
    ) -> int:
        aid = self.get_or_create_app_user(provider, external_user_id)

        who_story = user_metadata.get("who_user")
        about_story = user_metadata.get("about_user")
        display_name = user_metadata.get("user_display_name")
        has_display = "user_display_name" in user_metadata

        arj = user_metadata.get("ai_recommendation_json")
        update_rec = isinstance(arj, dict) and bool(arj.get("professions"))
        rec_json = self._dump_json(arj["professions"]) if update_rec else None

        self.upsert_who_user(
            aid,
            who_story,
            about_story,
            user_type,
            user_display_name=display_name if isinstance(display_name, str) else None,
            update_display_name=has_display,
            recommended_professions_json=rec_json,
            update_recommended_professions=update_rec,
        )

        inner_meta = {
            k: v
            for k, v in user_metadata.items()
            if k not in ("who_user", "about_user", "user_display_name")
        }
        snapshot = {
            "user_state": user_state,
            "user_type": user_type,
            "user_metadata": inner_meta,
        }
        self.save_metadata(aid, snapshot)

        self.upsert_dialog_state(aid, user_state, context=None)

        self.replace_conversation(aid, conversation_history, user_state)
        return aid

    def delete_identity_completely(self, provider: str, external_user_id: str) -> int:
        """Удалить пользователя и все связанные данные (включая identity)."""
        return self.delete_user_by_identity(provider, external_user_id)

    # ---------- обратная совместимость (строковый user_id = telegram) ----------

    def get_conversation_history(self, user_id: str) -> List[Dict[str, str]]:
        aid = self.get_app_user_id("telegram", user_id)
        if aid is None:
            return []
        return self.get_conversation(aid)

    def add_conversation_history(
        self,
        user_id: str,
        message_txt: str,
        message_from: str,
        created_at: datetime,
        user_state: str,
    ) -> int:
        aid = self.get_or_create_app_user("telegram", user_id)
        with self._Session() as s:
            row = Conversation(
                app_user_id=aid,
                message_txt=message_txt,
                message_from=message_from,
                created_at=created_at,
                dialog_phase=user_state,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def clean_conversation_history(self, user_id: str) -> int:
        return self.clear_identity_session("telegram", user_id)

    def clean_metadata(self, user_id: str) -> int:
        """Совместимость с model/start_llm: полная очистка данных сессии для Telegram id."""
        return self.clear_identity_session("telegram", user_id)

    def get_metadata(self, user_id: str) -> dict:
        aid = self.get_app_user_id("telegram", user_id)
        if aid is None:
            return {}
        bundle = self.get_session_bundle("telegram", user_id)
        return {
            "user_state": bundle["user_state"],
            "user_type": bundle["user_type"],
            "user_metadata": bundle["user_metadata"],
        }

    def save_metadata_legacy(self, user_id: str, user_metadata: dict) -> int:
        """Старый вызов: один JSON без разнесения по таблицам."""
        aid = self.get_or_create_app_user("telegram", user_id)
        return self.save_metadata(aid, user_metadata)

