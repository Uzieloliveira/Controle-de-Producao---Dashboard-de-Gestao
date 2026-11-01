import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main


class ManagerStorage:
    def list_manager_res(self) -> set[str]:
        return {"22081"}

    @staticmethod
    def list_users() -> list[dict[str, object]]:
        return [
            {
                "RE": "22081",
                "nome": "Maria",
                "departamento": "Montagem",
                "ativo": True,
            },
            {
                "RE": "22082",
                "nome": "João",
                "departamento": "Pintura",
                "ativo": True,
            },
        ]

    @staticmethod
    def list_records(collection: str) -> list[dict[str, object]]:
        if collection == "producoes":
            return [
                {"usuarioRe": "22081", "secao": "Bandagem", "quantidade": 10},
                {"usuarioRe": "22082", "secao": "Pintura", "quantidade": 20},
            ]
        return []

    @staticmethod
    def list_all_production_goals() -> list[dict[str, object]]:
        return [
            {
                "id": "goal-1",
                "usuarioRe": "22081",
                "secao": "Bandagem",
                "quantidade": 500,
                "departamento": "Montagem",
            },
            {
                "id": "goal-2",
                "usuarioRe": "22082",
                "secao": "Pintura",
                "quantidade": 300,
                "departamento": "Pintura",
            },
        ]

    @staticmethod
    def save_production_goal(
        employee_re: str, section: str, quantity: int, department: str
    ) -> dict[str, object]:
        return {
            "id": "goal-2",
            "usuarioRe": employee_re,
            "secao": section,
            "quantidade": quantity,
            "departamento": department,
        }

    @staticmethod
    def get_user(employee_re: str) -> dict[str, object] | None:
        if employee_re == "90829":
            return {
                "RE": employee_re,
                "nome": "Administrador",
                "departamento": "",
                "ativo": True,
            }
        return None


class ManagerRouteTests(unittest.TestCase):
    def test_manager_records_are_limited_to_department(self) -> None:
        records = [
            {"usuarioRe": "22081", "quantidade": 10},
            {"usuarioRe": "22082", "quantidade": 20},
            {"departamento": "Montagem", "quantidade": 30},
            {"departamento": "Pintura", "quantidade": 40},
        ]
        users = ManagerStorage.list_users()
        manager = {"RE": "22081", "departamento": "montagem"}

        self.assertEqual(
            main.records_for_department(records, manager, users),
            [records[0], records[2]],
        )

    def test_manager_records_resolve_department_by_user_re_with_normalized_values(self) -> None:
        records = [
            {"usuarioRe": "000123", "quantidade": 10},
            {"usuarioRe": "456", "quantidade": 20},
        ]
        users = [
            {"RE": "123", "departamento": "Montagem"},
            {"RE": "456", "departamento": "Pintura"},
        ]
        manager = {"RE": "123", "departamento": "Montagem"}

        self.assertEqual(
            [record["quantidade"] for record in main.records_for_department(records, manager, users)],
            [10],
        )

    def test_manager_results_endpoints_hide_other_departments(self) -> None:
        main.app.dependency_overrides[main.manager_user] = lambda: {
            "RE": "22081",
            "departamento": "Montagem",
        }
        try:
            with patch.object(main, "storage", ManagerStorage()):
                with TestClient(main.app) as client:
                    production_response = client.get("/api/producoes")
                    users_response = client.get("/api/gestores/operadores")
        finally:
            main.app.dependency_overrides.pop(main.manager_user, None)

        self.assertEqual(production_response.status_code, 200)
        self.assertEqual(
            [record["usuarioRe"] for record in production_response.json()],
            ["22081"],
        )
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(
            [operator["RE"] for operator in users_response.json()],
            ["22081"],
        )

    def test_second_manager_for_same_department_is_rejected(self) -> None:
        with patch.object(main, "storage", ManagerStorage()):
            with self.assertRaises(HTTPException) as raised:
                main.ensure_manager_department_available("22082", " montagem ")

        self.assertEqual(raised.exception.status_code, 409)

    def test_administrator_can_see_records_from_all_departments(self) -> None:
        records = [{"departamento": "Montagem"}, {"departamento": "Pintura"}]

        self.assertEqual(
            main.records_for_department(
                records, {"RE": "90829"}, ManagerStorage.list_users()
            ),
            records,
        )

    def test_list_managers_resolves_user_by_re_from_user_listing(self) -> None:
        main.app.dependency_overrides[main.admin_user] = lambda: {"RE": "90829"}
        try:
            with patch.object(main, "storage", ManagerStorage()):
                with TestClient(main.app) as client:
                    response = client.get("/api/admin/gestores")
        finally:
            main.app.dependency_overrides.pop(main.admin_user, None)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            {
                "RE": "22081",
                "nome": "Maria",
                "departamento": "Montagem",
                "ativo": True,
            },
            response.json(),
        )

    def test_manager_can_list_and_save_section_goals(self) -> None:
        main.app.dependency_overrides[main.manager_user] = lambda: {
            "RE": "22081",
            "departamento": "Montagem",
        }
        try:
            with patch.object(main, "storage", ManagerStorage()):
                with TestClient(main.app) as client:
                    list_response = client.get("/api/metas-producao")
                    save_response = client.post(
                        "/api/metas-producao",
                        json={"secao": "Acabamento", "quantidade": 350},
                    )
        finally:
            main.app.dependency_overrides.pop(main.manager_user, None)

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()[0]["secao"], "Bandagem")
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["usuarioRe"], "22081")
        self.assertEqual(save_response.json()["quantidade"], 350)
        self.assertEqual(save_response.json()["departamento"], "Montagem")

    def test_goals_are_filtered_by_department_and_admin_can_see_all(self) -> None:
        goals = ManagerStorage.list_all_production_goals()
        self.assertEqual(
            [goal["secao"] for goal in main.goals_for_department(
                goals,
                {"RE": "22081", "departamento": "montagem"},
                [],
                ManagerStorage.list_users(),
            )],
            ["Bandagem"],
        )
        self.assertEqual(
            len(main.goals_for_department(
                goals, {"RE": "90829"}, [], ManagerStorage.list_users()
            )),
            2,
        )

    def test_manager_remaining_pieces_are_filtered_by_department(self) -> None:
        records = [
            {"usuarioRe": "22081", "data": "2026-01-10", "acabamento": 5},
            {"usuarioRe": "22082", "data": "2026-01-11", "acabamento": 7},
            {"usuarioRe": "22081", "data": "2026-01-12", "acabamento": 2},
        ]
        users = ManagerStorage.list_users()
        manager = {"RE": "22081", "departamento": "montagem"}

        filtered = main.records_for_department(records, manager, users)

        self.assertEqual(len(filtered), 2)
        self.assertEqual([record["usuarioRe"] for record in filtered], ["22081", "22081"])
        self.assertTrue(all(main.department_key(record.get("departamento") or users[0]["departamento"]) == "montagem" for record in filtered))

    def test_goal_department_comes_from_production_section_department(self) -> None:
        production_rows = [
            {"secao": "Bandagem", "departamento": "Montagem", "usuarioRe": "x"},
            {"secao": "Pintura", "departamento": "Pintura", "usuarioRe": "y"},
        ]
        users: list[dict[str, object]] = []

        self.assertEqual(
            main.goal_department_for_section(
                "bandagem",
                {"RE": "22082", "departamento": "Pintura"},
                production_rows,
                users,
            ),
            "Montagem",
        )
        bandagem_goal = {
            "secao": "Bandagem",
            "departamento": "Montagem",
        }
        self.assertEqual(
            main.goals_for_department(
                [bandagem_goal],
                {"RE": "22081", "departamento": "Montagem"},
                production_rows,
                users,
            ),
            [bandagem_goal],
        )
        self.assertEqual(
            main.goals_for_department(
                [bandagem_goal],
                {"RE": "22082", "departamento": "Pintura"},
                production_rows,
                users,
            ),
            [],
        )

    def test_same_user_cannot_login_in_multiple_sessions(self) -> None:
        class ConcurrentLoginStorage:
            @staticmethod
            def get_user(employee_re: str) -> dict[str, object] | None:
                if employee_re == "10001":
                    return {
                        "RE": employee_re,
                        "nome": "Usuário",
                        "departamento": "Montagem",
                        "ativo": True,
                    }
                return None

            @staticmethod
            def get_password_hash(employee_re: str) -> str | None:
                if employee_re == "10001":
                    return main._hash_password("senha123")
                return None

            @staticmethod
            def is_manager(employee_re: str) -> bool:
                return False

        main.active_sessions.clear()
        try:
            with patch.object(main, "storage", ConcurrentLoginStorage()):
                with TestClient(main.app) as client:
                    first_login = client.post(
                        "/api/auth/login",
                        json={"RE": "10001", "senha": "senha123"},
                    )
                    second_login = client.post(
                        "/api/auth/login",
                        json={"RE": "10001", "senha": "senha123"},
                    )

            self.assertEqual(first_login.status_code, 200)
            self.assertEqual(second_login.status_code, 409)
            self.assertEqual(len(main.active_sessions["10001"]), 1)
            self.assertIn("Encerre a seção atual", second_login.json()["detail"])
        finally:
            main.active_sessions.clear()

    def test_invalid_stale_session_is_cleared_before_login(self) -> None:
        class StaleSessionStorage:
            @staticmethod
            def get_user(employee_re: str) -> dict[str, object] | None:
                if employee_re == "10001":
                    return {
                        "RE": employee_re,
                        "nome": "Usuário",
                        "departamento": "Montagem",
                        "ativo": True,
                    }
                return None

            @staticmethod
            def get_password_hash(employee_re: str) -> str | None:
                if employee_re == "10001":
                    return main._hash_password("senha123")
                return None

            @staticmethod
            def get_active_session_token(employee_re: str) -> str | None:
                if employee_re == "10001":
                    return "token-invalido"
                return None

            @staticmethod
            def clear_active_session(employee_re: str) -> None:
                return None

            @staticmethod
            def is_manager(employee_re: str) -> bool:
                return False

        main.active_sessions.clear()
        try:
            with patch.object(main, "storage", StaleSessionStorage()):
                with TestClient(main.app) as client:
                    response = client.post(
                        "/api/auth/login",
                        json={"RE": "10001", "senha": "senha123"},
                    )

            self.assertEqual(response.status_code, 200)
            self.assertIn("token", response.json())
            self.assertIn("10001", main.active_sessions)
            self.assertNotEqual(main.active_sessions["10001"], "token-invalido")
        finally:
            main.active_sessions.clear()

    def test_tokens_are_unique_even_for_same_user_in_same_second(self) -> None:
        with patch("backend.main.time.time", return_value=1700000000):
            first = main._create_token("10001")
            second = main._create_token("10001")

        self.assertNotEqual(first, second)

    def test_expired_session_token_is_treated_as_inactive(self) -> None:
        expired_token = main._create_token("10001")
        main.active_sessions["10001"] = expired_token

        with patch("backend.main._read_token", side_effect=HTTPException(status_code=401, detail="expired")):
            self.assertIsNone(main._read_active_session_token("10001"))
            self.assertNotIn("10001", main.active_sessions)

    def test_sqlite_storage_keeps_only_one_active_token_for_same_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "active_sessions.db"
            with patch("backend.storage.DATABASE_PATH", db_path):
                storage = __import__("backend.storage", fromlist=["Storage"]).Storage()
                storage.register_active_session("10001", "first-token")
                storage.register_active_session("10001", "second-token")

                self.assertEqual(
                    storage.get_active_session_tokens("10001"),
                    ["second-token"],
                )

    def test_concurrent_logins_are_rejected_for_same_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "concurrent_login.db"
            import backend.storage as storage_module

            with patch("backend.storage.DATABASE_PATH", db_path):
                storage_module.DATABASE_PATH = db_path
                storage = storage_module.Storage()
                storage.create_user("10001", "Usuário", "Montagem")
                storage.set_password_hash("10001", main._hash_password("senha123"))

                main.active_sessions.clear()
                with patch.object(main, "storage", storage):
                    response_codes: list[int] = []
                    lock = threading.Lock()

                    def login_once() -> None:
                        with TestClient(main.app) as client:
                            response = client.post(
                                "/api/auth/login",
                                json={"RE": "10001", "senha": "senha123"},
                            )
                            with lock:
                                response_codes.append(response.status_code)

                    threads = [threading.Thread(target=login_once) for _ in range(2)]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()

                self.assertCountEqual(response_codes, [200, 409])
                self.assertEqual(len(main.active_sessions["10001"]), 1)

    def test_register_session_replaces_existing_token_for_same_user(self) -> None:
        main.active_sessions.clear()
        try:
            first_token = main._create_token("10001")
            second_token = main._create_token("10001")

            class SessionStorage:
                @staticmethod
                def get_active_session_token(employee_re: str) -> str | None:
                    return first_token if employee_re == "10001" else None

                @staticmethod
                def register_active_session(employee_re: str, token: str) -> None:
                    return None

                @staticmethod
                def clear_active_session(employee_re: str) -> None:
                    return None

                @staticmethod
                def is_active_session(employee_re: str, token: str) -> bool:
                    return employee_re == "10001" and token == second_token

            with patch.object(main, "storage", SessionStorage()):
                main._register_active_session("10001", first_token)
                main._register_active_session("10001", second_token)

            self.assertEqual(len(main.active_sessions["10001"]), 1)
            self.assertSetEqual(main.active_sessions["10001"], {second_token})
        finally:
            main.active_sessions.clear()

if __name__ == "__main__":
    unittest.main()
