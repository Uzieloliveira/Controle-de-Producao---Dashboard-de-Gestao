import os
import sqlite3
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv


load_dotenv()

DATABASE_PATH = Path(__file__).with_name("controle_producao.db")


def normalize_employee_re(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return digits.lstrip("0") or "0"
    return text


class Storage:
    def __init__(self) -> None:
        self.firestore = None
        self.use_firestore = os.getenv("FIRESTORE_ENABLED", "").lower() == "true"
        if self.use_firestore:
            self.firestore = self._create_firestore_client()
            if self.firestore is None:
                self.use_firestore = False
        if not self.use_firestore:
            self._initialize_sqlite()

    @staticmethod
    def _firestore_candidates(collection_name: str) -> list[str]:
        aliases = {
            "usuarios": ["usuarios", "usuarios_producao", "users"],
            "gestores": ["gestores", "gestores_producao", "managers"],
            "contas": ["contas", "contas_producao", "accounts"],
            "active_sessions": ["active_sessions", "sessoes_ativas", "sessions"],
            "metas_producao": ["metas_producao", "metas", "production_goals"],
            "producoes": ["producoes", "producoes_producao", "production"],
            "pecas_restantes": ["pecas_restantes", "pecas_restantes_producao", "remaining_pieces"],
        }
        preferred = [collection_name]
        return list(dict.fromkeys(preferred + aliases.get(collection_name, [])))

    def _firestore_collection(self, collection_name: str) -> Any:
        if not self.firestore:
            raise RuntimeError("Firestore não inicializado.")
        candidates = self._firestore_candidates(collection_name)
        for name in candidates:
            try:
                return self.firestore.collection(name)
            except Exception:
                continue
        return self.firestore.collection(candidates[0])

    def _create_firestore_client(self) -> Any | None:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        app_env = os.getenv("APP_ENV", "development").lower()

        if credential_path and not os.path.exists(credential_path):
            if app_env == "production":
                raise RuntimeError(
                    "Arquivo de credenciais do Firebase não encontrado. "
                    f"Verifique GOOGLE_APPLICATION_CREDENTIALS ({credential_path})."
                )
            return None

        if not project_id and not credential_path and app_env == "production":
            raise RuntimeError(
                "FIRESTORE_ENABLED=true exige GOOGLE_CLOUD_PROJECT e/ou "
                "GOOGLE_APPLICATION_CREDENTIALS configurados em produção."
            )

        try:
            from google.cloud import firestore

            emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")
            if emulator_host:
                return firestore.Client(project=project_id or "local-dev-project")
            return firestore.Client(project=project_id) if project_id else firestore.Client()
        except Exception:
            if app_env == "production":
                raise RuntimeError(
                    "Não foi possível conectar ao Firestore. Verifique GOOGLE_CLOUD_PROJECT, "
                    "GOOGLE_APPLICATION_CREDENTIALS ou o ambiente do projeto."
                ) from None
            return None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_sqlite(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    re TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    department TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    re TEXT PRIMARY KEY REFERENCES users(re),
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS producoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anotacao TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL,
                    departamento TEXT NOT NULL DEFAULT '',
                    enviado INTEGER NOT NULL DEFAULT 0,
                    operador TEXT NOT NULL,
                    quantidade INTEGER NOT NULL,
                    secao TEXT NOT NULL,
                    usuarioRe TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pecas_restantes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    acabamento INTEGER NOT NULL DEFAULT 0,
                    amarracao INTEGER NOT NULL DEFAULT 0,
                    bandagem INTEGER NOT NULL DEFAULT 0,
                    data TEXT NOT NULL,
                    ligacao INTEGER NOT NULL DEFAULT 0,
                    prenca INTEGER NOT NULL DEFAULT 0,
                    solda INTEGER NOT NULL DEFAULT 0,
                    usuarioRe TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metas_producao (
                    usuario_re TEXT NOT NULL,
                    secao_key TEXT NOT NULL,
                    secao TEXT NOT NULL,
                    quantidade INTEGER NOT NULL,
                    departamento TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (usuario_re, secao_key)
                );
                CREATE TABLE IF NOT EXISTS gestores (
                    re TEXT PRIMARY KEY REFERENCES users(re)
                );
                CREATE TABLE IF NOT EXISTS active_sessions (
                    re TEXT NOT NULL,
                    token TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (re, token)
                );
                """
            )
            migration_needed = False
            try:
                pragma = connection.execute(
                    "PRAGMA table_info(active_sessions)"
                ).fetchall()
                if pragma and pragma[0][5] == 1 and len(pragma) == 3:
                    migration_needed = True
            except Exception:
                migration_needed = False
            if migration_needed:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS active_sessions_new (re TEXT NOT NULL, token TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (re, token))"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO active_sessions_new (re, token, created_at) SELECT re, token, created_at FROM active_sessions"
                )
                connection.execute("DROP TABLE active_sessions")
                connection.execute("ALTER TABLE active_sessions_new RENAME TO active_sessions")
            user_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "active" not in user_columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
                )
            goal_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(metas_producao)").fetchall()
            }
            if "departamento" not in goal_columns:
                connection.execute(
                    "ALTER TABLE metas_producao ADD COLUMN departamento TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                UPDATE metas_producao
                SET departamento = COALESCE(
                    (SELECT department FROM users WHERE users.re = metas_producao.usuario_re),
                    ''
                )
                WHERE departamento = ''
                """
            )

    @staticmethod
    def _user_record(document: Any) -> dict[str, Any] | None:
        if not document:
            return None
        return {
            "RE": normalize_employee_re(document.get("RE", "")),
            "nome": str(document.get("nome", "")),
            "departamento": str(document.get("departamento", "")),
            "ativo": bool(document.get("ativo", True)),
        }

    def _find_firestore_snapshot(self, collection_name: str, employee_re: str) -> Any:
        normalized_employee_re = normalize_employee_re(employee_re)
        if not normalized_employee_re:
            return None

        for candidate in self._firestore_candidates(collection_name):
            try:
                collection = self.firestore.collection(candidate)
            except Exception:
                continue

            try:
                document = collection.document(normalized_employee_re).get()
                if document.exists:
                    return document
            except Exception:
                pass

            try:
                for snapshot in collection.stream():
                    data = snapshot.to_dict() or {}
                    values = {
                        normalize_employee_re(snapshot.id),
                        normalize_employee_re(data.get("RE", "")),
                        normalize_employee_re(data.get("re", "")),
                        normalize_employee_re(data.get("usuarioRe", "")),
                        normalize_employee_re(data.get("usuario_re", "")),
                    }
                    if normalized_employee_re in values:
                        return snapshot
            except Exception:
                continue
        return None

    def get_user(self, employee_re: str) -> dict[str, Any] | None:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            snapshot = self._find_firestore_snapshot("usuarios", employee_re)
            if snapshot is None:
                return None
            user = self._user_record(snapshot.to_dict() if getattr(snapshot, "exists", True) else None)
            if user is not None:
                user["RE"] = user["RE"] or employee_re
            return user
        with self._connection() as connection:
            row = connection.execute(
                "SELECT re, name, department, active FROM users WHERE re = ?", (employee_re,)
            ).fetchone()
        if row is None:
            return None
        return {
            "RE": normalize_employee_re(row["re"]),
            "nome": row["name"],
            "departamento": row["department"],
            "ativo": bool(row["active"]),
        }

    def create_user(self, employee_re: str, name: str, department: str = "") -> dict[str, Any]:
        employee_re = normalize_employee_re(employee_re)
        user = {"RE": employee_re, "nome": name, "departamento": department, "ativo": True}
        if self.use_firestore:
            target_collection = self._firestore_collection("usuarios")
            target_collection.document(employee_re).set(user)
        else:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO users (re, name, department, active) VALUES (?, ?, ?, 1)",
                    (employee_re, name, department),
                )
        return user

    def list_users(self) -> list[dict[str, Any]]:
        if self.use_firestore:
            users: list[dict[str, Any]] = []
            seen: set[str] = set()
            for candidate in self._firestore_candidates("usuarios"):
                try:
                    snapshots = self.firestore.collection(candidate).stream()
                except Exception:
                    continue
                for snapshot in snapshots:
                    record = self._user_record(snapshot.to_dict())
                    if record is None:
                        continue
                    record["RE"] = normalize_employee_re(record["RE"] or snapshot.id)
                    if record["RE"] in seen:
                        continue
                    seen.add(record["RE"])
                    users.append(record)
            return sorted(users, key=lambda item: item["RE"])
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT re, name, department, active FROM users ORDER BY re"
            ).fetchall()
        return [
            {
                "RE": normalize_employee_re(row["re"]),
                "nome": row["name"],
                "departamento": row["department"],
                "ativo": bool(row["active"]),
            }
            for row in rows
        ]

    def update_user(self, employee_re: str, name: str, department: str) -> dict[str, Any]:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            target_collection = self._firestore_collection("usuarios")
            reference = target_collection.document(employee_re)
            reference.update({"nome": name, "departamento": department})
        else:
            with self._connection() as connection:
                connection.execute(
                    "UPDATE users SET name = ?, department = ? WHERE re = ?",
                    (name, department, employee_re),
                )
        user = self.get_user(employee_re)
        if user is None:
            raise LookupError(f"Usuário {employee_re} desapareceu durante a atualização.")
        return user

    def set_user_active(self, employee_re: str, active: bool) -> None:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            self._firestore_collection("usuarios").document(employee_re).update({"ativo": active})
        else:
            with self._connection() as connection:
                connection.execute(
                    "UPDATE users SET active = ? WHERE re = ?",
                    (int(active), employee_re),
                )

    def get_password_hash(self, employee_re: str) -> str | None:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            snapshot = self._find_firestore_snapshot("contas", employee_re)
            if snapshot is None:
                return None
            data = snapshot.to_dict() if getattr(snapshot, "exists", True) else None
            return str(data["passwordHash"]) if data and "passwordHash" in data else None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT password_hash FROM accounts WHERE re = ?", (employee_re,)
            ).fetchone()
        return row["password_hash"] if row else None

    def set_password_hash(self, employee_re: str, password_hash: str) -> None:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            self.firestore.collection("contas").document(employee_re).set(
                {"usuarioRe": employee_re, "passwordHash": password_hash}
            )
        else:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO accounts (re, password_hash) VALUES (?, ?)
                    ON CONFLICT(re) DO UPDATE SET password_hash = excluded.password_hash
                    """,
                    (employee_re, password_hash),
                )

    def register_active_session(self, employee_re: str, token: str) -> None:
        employee_re = normalize_employee_re(employee_re)
        if not employee_re or not token:
            return
        if self.use_firestore:
            collection = self.firestore.collection("active_sessions")
            for snapshot in collection.where("re", "==", employee_re).stream():
                snapshot.reference.delete()
            collection.document(f"{employee_re}:{token}").set({
                "re": employee_re,
                "token": token,
            })
            return
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM active_sessions WHERE re = ?",
                (employee_re,),
            )
            connection.execute(
                """
                INSERT INTO active_sessions (re, token, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (employee_re, token),
            )

    def clear_active_session(self, employee_re: str, token: str | None = None) -> None:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            if token is None:
                collection = self.firestore.collection("active_sessions")
                for snapshot in collection.where("re", "==", employee_re).stream():
                    snapshot.reference.delete()
                return
            document_id = f"{employee_re}:{token}"
            self.firestore.collection("active_sessions").document(document_id).delete()
            return
        with self._connection() as connection:
            if token is None:
                connection.execute("DELETE FROM active_sessions WHERE re = ?", (employee_re,))
            else:
                connection.execute(
                    "DELETE FROM active_sessions WHERE re = ? AND token = ?",
                    (employee_re, token),
                )

    def clear_all_active_sessions(self) -> None:
        if self.use_firestore:
            for snapshot in self.firestore.collection("active_sessions").stream():
                snapshot.reference.delete()
            return
        with self._connection() as connection:
            connection.execute("DELETE FROM active_sessions")

    def get_active_session_tokens(self, employee_re: str) -> list[str]:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            tokens: list[str] = []
            for snapshot in self.firestore.collection("active_sessions").where("re", "==", employee_re).stream():
                data = snapshot.to_dict() or {}
                token = str(data.get("token") or "").strip()
                if token:
                    tokens.append(token)
            return tokens
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT token FROM active_sessions WHERE re = ?",
                (employee_re,),
            ).fetchall()
        return [row["token"] for row in rows]

    def get_active_session_token(self, employee_re: str) -> str | None:
        tokens = self.get_active_session_tokens(employee_re)
        return tokens[0] if tokens else None

    def is_active_session(self, employee_re: str, token: str) -> bool:
        employee_re = normalize_employee_re(employee_re)
        if not employee_re or not token:
            return False
        if self.use_firestore:
            document_id = f"{employee_re}:{token}"
            snapshot = self.firestore.collection("active_sessions").document(document_id).get()
            return snapshot.exists
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM active_sessions WHERE re = ? AND token = ? LIMIT 1",
                (employee_re, token),
            ).fetchone()
        return row is not None

    def is_manager(self, employee_re: str) -> bool:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            snapshot = self._find_firestore_snapshot("gestores", employee_re)
            return snapshot is not None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM gestores WHERE re = ?", (employee_re,)
            ).fetchone()
        return row is not None

    def list_manager_res(self) -> set[str]:
        if self.use_firestore:
            manager_res = set()
            for candidate in self._firestore_candidates("gestores"):
                try:
                    snapshots = self.firestore.collection(candidate).stream()
                except Exception:
                    continue
                for snapshot in snapshots:
                    document = snapshot.to_dict() or {}
                    employee_re = normalize_employee_re(document.get("usuarioRe") or document.get("re") or snapshot.id)
                    if employee_re:
                        manager_res.add(employee_re)
            return manager_res
        with self._connection() as connection:
            rows = connection.execute("SELECT re FROM gestores ORDER BY re").fetchall()
        return {normalize_employee_re(row["re"]) for row in rows}

    def list_managers(self) -> list[dict[str, str]]:
        managers = []
        for employee_re in sorted(self.list_manager_res()):
            user = self.get_user(employee_re)
            if user is not None:
                managers.append(user)
        return managers

    def add_manager(self, employee_re: str) -> None:
        employee_re = normalize_employee_re(employee_re)
        if self.use_firestore:
            self._firestore_collection("gestores").document(employee_re).set({"usuarioRe": employee_re})
            return
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO gestores (re) VALUES (?) ON CONFLICT(re) DO NOTHING",
                (employee_re,),
            )

    def list_records(self, collection: str) -> list[dict[str, Any]]:
        if self.use_firestore:
            snapshots = self.firestore.collection(collection).stream()
            records = []
            for snapshot in snapshots:
                record = snapshot.to_dict()
                record["id"] = snapshot.id
                records.append(record)
            return sorted(records, key=lambda item: item.get("data", ""), reverse=True)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM {collection} ORDER BY data DESC, id DESC",
            ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            if collection == "producoes":
                record["enviado"] = bool(record["enviado"])
        return records

    @staticmethod
    def _section_key(section: str) -> str:
        return " ".join(section.split()).casefold()

    def list_production_goals(self, employee_re: str) -> list[dict[str, Any]]:
        if self.use_firestore:
            snapshots = (
                self.firestore.collection("metas_producao")
                .where("usuarioRe", "==", employee_re)
                .stream()
            )
            records = []
            for snapshot in snapshots:
                record = snapshot.to_dict()
                record["id"] = snapshot.id
                if not record.get("departamento"):
                    owner = self.get_user(employee_re)
                    record["departamento"] = owner.get("departamento", "") if owner else ""
                records.append(record)
            return sorted(records, key=lambda item: item["secao"].casefold())

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT secao, quantidade, departamento FROM metas_producao
                WHERE usuario_re = ? ORDER BY secao COLLATE NOCASE
                """,
                (employee_re,),
            ).fetchall()
        return [
            {
                "id": f"{employee_re}:{self._section_key(row['secao'])}",
                "usuarioRe": employee_re,
                "secao": row["secao"],
                "quantidade": row["quantidade"],
                "departamento": row["departamento"],
            }
            for row in rows
        ]

    def list_all_production_goals(self) -> list[dict[str, Any]]:
        if self.use_firestore:
            records = []
            for snapshot in self.firestore.collection("metas_producao").stream():
                record = snapshot.to_dict() or {}
                employee_re = str(record.get("usuarioRe", "")).strip()
                if not record.get("departamento") and employee_re:
                    owner = self.get_user(employee_re)
                    record["departamento"] = owner.get("departamento", "") if owner else ""
                record["id"] = snapshot.id
                records.append(record)
            return sorted(records, key=lambda item: str(item.get("secao", "")).casefold())

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT usuario_re, secao, quantidade, departamento
                FROM metas_producao ORDER BY secao COLLATE NOCASE
                """
            ).fetchall()
        return [
            {
                "id": f"{row['usuario_re']}:{self._section_key(row['secao'])}",
                "usuarioRe": row["usuario_re"],
                "secao": row["secao"],
                "quantidade": row["quantidade"],
                "departamento": row["departamento"],
            }
            for row in rows
        ]

    def save_production_goal(
        self, employee_re: str, section: str, quantity: int, department: str = ""
    ) -> dict[str, Any]:
        section_key = self._section_key(section)
        record = {
            "usuarioRe": employee_re,
            "secao": section,
            "quantidade": quantity,
            "departamento": department,
        }
        if self.use_firestore:
            document_id = sha256(
                f"{employee_re}\0{section_key}".encode("utf-8")
            ).hexdigest()
            self.firestore.collection("metas_producao").document(document_id).set(record)
            return {"id": document_id, **record}

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO metas_producao (
                    usuario_re, secao_key, secao, quantidade, departamento
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(usuario_re, secao_key)
                DO UPDATE SET secao = excluded.secao, quantidade = excluded.quantidade,
                    departamento = excluded.departamento
                """,
                (employee_re, section_key, section, quantity, department),
            )
        return {
            "id": f"{employee_re}:{section_key}",
            **record,
        }
