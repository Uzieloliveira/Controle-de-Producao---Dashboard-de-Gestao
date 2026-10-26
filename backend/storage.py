import os
import sqlite3
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator


DATABASE_PATH = Path(__file__).with_name("controle_producao.db")


class Storage:
    def __init__(self) -> None:
        self.firestore = None
        self.use_firestore = os.getenv("FIRESTORE_ENABLED", "").lower() == "true"
        if self.use_firestore:
            from google.cloud import firestore

            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            self.firestore = firestore.Client(project=project_id) if project_id else firestore.Client()
        else:
            self._initialize_sqlite()

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
                """
            )
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
            "RE": str(document.get("RE", "")),
            "nome": str(document.get("nome", "")),
            "departamento": str(document.get("departamento", "")),
            "ativo": bool(document.get("ativo", True)),
        }

    def get_user(self, employee_re: str) -> dict[str, Any] | None:
        if self.use_firestore:
            snapshot = self.firestore.collection("usuarios").document(employee_re).get()
            user = self._user_record(snapshot.to_dict() if snapshot.exists else None)
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
            "RE": row["re"],
            "nome": row["name"],
            "departamento": row["department"],
            "ativo": bool(row["active"]),
        }

    def create_user(self, employee_re: str, name: str, department: str = "") -> dict[str, Any]:
        user = {"RE": employee_re, "nome": name, "departamento": department, "ativo": True}
        if self.use_firestore:
            self.firestore.collection("usuarios").document(employee_re).set(user)
        else:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO users (re, name, department, active) VALUES (?, ?, ?, 1)",
                    (employee_re, name, department),
                )
        return user

    def list_users(self) -> list[dict[str, Any]]:
        if self.use_firestore:
            users = []
            for snapshot in self.firestore.collection("usuarios").stream():
                record = self._user_record(snapshot.to_dict())
                if record is not None:
                    record["RE"] = record["RE"] or snapshot.id
                    users.append(record)
            return sorted(users, key=lambda item: item["RE"])
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT re, name, department, active FROM users ORDER BY re"
            ).fetchall()
        return [
            {
                "RE": row["re"],
                "nome": row["name"],
                "departamento": row["department"],
                "ativo": bool(row["active"]),
            }
            for row in rows
        ]

    def update_user(self, employee_re: str, name: str, department: str) -> dict[str, Any]:
        if self.use_firestore:
            reference = self.firestore.collection("usuarios").document(employee_re)
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
        if self.use_firestore:
            self.firestore.collection("usuarios").document(employee_re).update(
                {"ativo": active}
            )
        else:
            with self._connection() as connection:
                connection.execute(
                    "UPDATE users SET active = ? WHERE re = ?",
                    (int(active), employee_re),
                )

    def get_password_hash(self, employee_re: str) -> str | None:
        if self.use_firestore:
            snapshot = self.firestore.collection("contas").document(employee_re).get()
            data = snapshot.to_dict() if snapshot.exists else None
            return str(data["passwordHash"]) if data and "passwordHash" in data else None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT password_hash FROM accounts WHERE re = ?", (employee_re,)
            ).fetchone()
        return row["password_hash"] if row else None

    def set_password_hash(self, employee_re: str, password_hash: str) -> None:
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

    def is_manager(self, employee_re: str) -> bool:
        if self.use_firestore:
            return self.firestore.collection("gestores").document(employee_re).get().exists
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM gestores WHERE re = ?", (employee_re,)
            ).fetchone()
        return row is not None

    def list_manager_res(self) -> set[str]:
        if self.use_firestore:
            manager_res = set()
            for snapshot in self.firestore.collection("gestores").stream():
                document = snapshot.to_dict() or {}
                employee_re = str(document.get("usuarioRe") or snapshot.id).strip()
                if employee_re:
                    manager_res.add(employee_re)
            return manager_res
        with self._connection() as connection:
            rows = connection.execute("SELECT re FROM gestores ORDER BY re").fetchall()
        return {row["re"] for row in rows}

    def list_managers(self) -> list[dict[str, str]]:
        managers = []
        for employee_re in sorted(self.list_manager_res()):
            user = self.get_user(employee_re)
            if user is not None:
                managers.append(user)
        return managers

    def add_manager(self, employee_re: str) -> None:
        if self.use_firestore:
            self.firestore.collection("gestores").document(employee_re).set(
                {"usuarioRe": employee_re}
            )
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
