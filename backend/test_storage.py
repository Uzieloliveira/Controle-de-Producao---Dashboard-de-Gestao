import unittest

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
        self.documents = {
            "usuarios": {snapshot.id: snapshot for snapshot in users},
            "gestores": {snapshot.id: snapshot for snapshot in managers},
        }
        self.collections = {
            "usuarios": users,
            "gestores": managers,
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


if __name__ == "__main__":
    unittest.main()
