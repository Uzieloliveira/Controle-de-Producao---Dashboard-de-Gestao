import os
import unittest
from unittest.mock import patch

from backend.storage import Storage


class Snapshot:
    def __init__(self, document_id: str, data: dict[str, str]) -> None:
        self.id = document_id
        self.data = data
        self.exists = True

    def to_dict(self) -> dict[str, str]:
        return self.data


class Collection:
    def __init__(self, snapshots: list[Snapshot], documents: dict[str, Snapshot]) -> None:
        self.snapshots = snapshots
        self.documents = documents

    def stream(self) -> list[Snapshot]:
        return self.snapshots

    def document(self, document_id: str) -> "Document":
        return Document(self.documents.get(document_id))


class Document:
    def __init__(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot

    def get(self) -> Snapshot:
        if self.snapshot is None:
            return MissingSnapshot()
        return self.snapshot


class MissingSnapshot:
    exists = False

    @staticmethod
    def to_dict() -> None:
        return None


class FakeFirestore:
    def __init__(self) -> None:
        users = [Snapshot("12345", {"nome": "Operador"})]
        managers = [Snapshot("manager-document", {"usuarioRe": "12345"})]
        production_users = [Snapshot("98765", {"RE": "98765", "nome": "Multiplicador de produção"})]
        productions = [Snapshot("prod-1", {"usuarioRe": "98765", "operador": "", "quantidade": 42, "data": "2026-11-03"})]
        self.documents = {
            "usuarios": {snapshot.id: snapshot for snapshot in users},
            "gestores": {snapshot.id: snapshot for snapshot in managers},
            "usuarios_producao": {snapshot.id: snapshot for snapshot in production_users},
            "producoes": {snapshot.id: snapshot for snapshot in productions},
        }
        self.collections = {
            "usuarios": users,
            "gestores": managers,
            "usuarios_producao": production_users,
            "producoes": productions,
        }

    def collection(self, name: str) -> Collection:
        return Collection(self.collections[name], self.documents[name])


class FirestoreStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = object.__new__(Storage)
        self.storage.use_firestore = True
        self.storage.firestore = FakeFirestore()

    def test_list_users_uses_document_id_when_re_field_is_missing(self) -> None:
        self.assertEqual(self.storage.list_users()[0]["RE"], "12345")

    def test_get_user_uses_document_id_when_re_field_is_missing(self) -> None:
        self.assertEqual(self.storage.get_user("12345")["RE"], "12345")

    def test_list_manager_res_returns_document_ids(self) -> None:
        self.assertEqual(self.storage.list_manager_res(), {"12345"})

    def test_user_lookup_normalizes_re_formatting(self) -> None:
        snapshot = Snapshot("000123", {"RE": " 123 ", "nome": "João", "departamento": "Pintura", "ativo": True})
        self.storage.firestore.collections["usuarios"] = [snapshot]
        self.storage.firestore.documents["usuarios"] = {"000123": snapshot}

        self.assertEqual(self.storage.get_user("123")["RE"], "123")
        self.assertEqual(self.storage.get_user("000123")["RE"], "123")

    def test_list_users_ignores_production_user_collection(self) -> None:
        self.assertNotIn("usuarios_producao", Storage._firestore_candidates("usuarios"))

        production_snapshot = Snapshot("99999", {"RE": "99999", "nome": "Produção", "departamento": "Operação", "ativo": True})
        self.storage.firestore.collections["usuarios_producao"] = [production_snapshot]
        self.storage.firestore.documents["usuarios_producao"] = {"99999": production_snapshot}

        users = self.storage.list_users()
        self.assertEqual([user["RE"] for user in users], ["12345"])

    def test_production_records_keep_operator_name_from_production_table(self) -> None:
        production_snapshot = Snapshot("prod-2", {"usuarioRe": "98765", "operador": "novoteste", "quantidade": 7, "data": "2026-11-03"})
        self.storage.firestore.collections["producoes"] = [production_snapshot]
        self.storage.firestore.documents["producoes"] = {"prod-2": production_snapshot}

        records = self.storage.list_records("producoes")
        self.assertEqual(records[0]["operador"], "novoteste")
        self.assertEqual(records[0]["multiplicador"], "Multiplicador de produção")

    def test_production_records_do_not_derive_operator_name_from_users_producao(self) -> None:
        production_snapshot = Snapshot("prod-3", {"usuarioRe": "000999", "operador": "novoteste", "quantidade": 8, "data": "2026-11-03"})
        self.storage.firestore.collections["producoes"] = [production_snapshot]
        self.storage.firestore.documents["producoes"] = {"prod-3": production_snapshot}

        records = self.storage.list_records("producoes")
        self.assertEqual(records[0]["operador"], "novoteste")
        self.assertEqual(records[0]["multiplicador"], "")

    @patch.dict(os.environ, {"FIRESTORE_ENABLED": "true", "APP_ENV": "development"}, clear=False)
    @patch("google.cloud.firestore.Client", side_effect=RuntimeError("ADC missing"))
    def test_firestore_connection_failure_falls_back_to_sqlite(self, _mock_client) -> None:
        storage = Storage()
        self.assertFalse(storage.use_firestore)
        self.assertIsNone(storage.firestore)

    @patch.dict(
        os.environ,
        {"FIRESTORE_ENABLED": "true", "APP_ENV": "production", "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/nao-existe.json"},
        clear=False,
    )
    def test_missing_firestore_credentials_fail_fast_in_production(self) -> None:
        with self.assertRaises(RuntimeError):
            Storage()


if __name__ == "__main__":
    unittest.main()
