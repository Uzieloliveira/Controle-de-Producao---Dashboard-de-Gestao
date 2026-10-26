import unittest
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

if __name__ == "__main__":
    unittest.main()
