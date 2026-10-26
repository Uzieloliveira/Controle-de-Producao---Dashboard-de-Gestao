import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from backend.storage import Storage


load_dotenv()

app = FastAPI(title="API Controle de Produção", version="1.0.0")
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)

secret_key = os.getenv("APP_SECRET_KEY", "change-this-development-secret")
if secret_key == "change-this-development-secret" and os.getenv("APP_ENV") == "production":
    raise RuntimeError("Configure APP_SECRET_KEY antes de iniciar em produção.")

storage = Storage()
bearer_scheme = HTTPBearer(auto_error=False)
PIECES_FIELDS = ("acabamento", "amarracao", "bandagem", "ligacao", "prenca", "solda")
admin_re = os.getenv("ADMIN_RE", "90829").strip()
admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", "").strip()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    salt_encoded = base64.urlsafe_b64encode(salt).rstrip(b"=").decode("ascii")
    digest_encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{salt_encoded}${digest_encoded}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_part, digest_part = stored_hash.split("$", maxsplit=1)
        salt = base64.urlsafe_b64decode(salt_part + "=" * (-len(salt_part) % 4))
        expected_digest = base64.urlsafe_b64decode(
            digest_part + "=" * (-len(digest_part) % 4)
        )
        actual_digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1
        )
        return hmac.compare_digest(actual_digest, expected_digest)
    except (ValueError, TypeError):
        return False


def is_admin(employee_re: str) -> bool:
    return employee_re == admin_re


def is_manager(employee_re: str) -> bool:
    configured_managers = {
        value.strip()
        for value in os.getenv("DASHBOARD_MANAGER_RES", "").split(",")
        if value.strip()
    }
    return is_admin(employee_re) or employee_re in configured_managers or storage.is_manager(employee_re)


def department_key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def configured_manager_res() -> set[str]:
    return {
        value.strip()
        for value in os.getenv("DASHBOARD_MANAGER_RES", "").split(",")
        if value.strip()
    }


def manager_res() -> set[str]:
    return configured_manager_res() | storage.list_manager_res()


def records_for_department(
    records: list[dict[str, Any]],
    user: dict[str, Any],
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if is_admin(user["RE"]):
        return records

    target_department = department_key(user.get("departamento"))
    if not target_department:
        return []

    users_by_re = {
        str(item.get("RE", "")).strip(): item
        for item in users
        if str(item.get("RE", "")).strip()
    }
    return [
        record
        for record in records
        if department_key(
            record.get("departamento")
            or record.get("department")
            or users_by_re.get(str(record.get("usuarioRe", "")).strip(), {}).get("departamento")
        ) == target_department
    ]


def goals_for_department(
    goals: list[dict[str, Any]],
    user: dict[str, Any],
    productions: list[dict[str, Any]],
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if is_admin(user["RE"]):
        return goals

    target_department = department_key(user.get("departamento"))
    if not target_department:
        return []

    users_by_re = {
        str(item.get("RE", "")).strip(): item
        for item in users
        if str(item.get("RE", "")).strip()
    }
    departments_by_section: dict[str, set[str]] = {}
    for record in productions:
        section_id = department_key(record.get("secao"))
        department_id = department_key(
            record.get("departamento")
            or users_by_re.get(str(record.get("usuarioRe", "")).strip(), {}).get("departamento")
        )
        if section_id and department_id:
            departments_by_section.setdefault(section_id, set()).add(department_id)

    return [
        goal
        for goal in goals
        if target_department in departments_by_section.get(
            department_key(goal.get("secao")),
            {department_key(goal.get("departamento"))},
        )
    ]


def goal_department_for_section(
    section: str,
    user: dict[str, Any],
    productions: list[dict[str, Any]],
    users: list[dict[str, Any]],
) -> str:
    users_by_re = {
        str(item.get("RE", "")).strip(): item
        for item in users
        if str(item.get("RE", "")).strip()
    }
    section_id = department_key(section)
    departments = {
        department_key(department): str(department).strip()
        for record in productions
        if department_key(record.get("secao")) == section_id
        for department in [
            record.get("departamento")
            or users_by_re.get(str(record.get("usuarioRe", "")).strip(), {}).get("departamento")
        ]
        if department_key(department)
    }

    manager_department = str(user.get("departamento", "")).strip()
    manager_department_id = department_key(manager_department)
    if len(departments) > 1:
        if manager_department_id in departments:
            return manager_department
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta seção existe em mais de um departamento. Cadastre a meta com um gestor de um desses departamentos.",
        )
    if departments:
        return next(iter(departments.values()))
    if manager_department_id:
        return manager_department
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Não foi possível identificar o departamento desta seção.",
    )


def ensure_manager_department_available(employee_re: str, department: str) -> None:
    department_id = department_key(department)
    if not department_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O usuário precisa ter um departamento para ser gestor.",
        )

    users_by_re = {
        str(item.get("RE", "")).strip(): item
        for item in storage.list_users()
        if str(item.get("RE", "")).strip()
    }
    current_manager_res = manager_res()
    conflict = next(
        (
            item for re_value, item in users_by_re.items()
            if re_value != employee_re
            and re_value in current_manager_res
            and department_key(item.get("departamento")) == department_id
        ),
        None,
    )
    if conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Já existe um gestor para o departamento {conflict.get('departamento')}.",
        )


class RegistrationInput(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    RE: str = Field(min_length=1, max_length=5)
    departamento: str = Field(min_length=1, max_length=100)
    senha: str = Field(min_length=6, max_length=128)

    @field_validator("nome")
    @classmethod
    def strip_first_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Informe o primeiro nome.")
        return value.split()[0]

    @field_validator("departamento")
    @classmethod
    def strip_department(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Informe o departamento.")
        return value

    @field_validator("RE", mode="before")
    @classmethod
    def strip_re(cls, value: Any) -> str:
        if isinstance(value, str):
            value = value.strip()
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}", value):
            raise ValueError("O RE deve conter somente números e ter no máximo 5 dígitos.")
        return value


class LoginInput(BaseModel):
    RE: str = Field(min_length=1, max_length=5)
    senha: str = Field(min_length=1, max_length=128)

    @field_validator("RE", mode="before")
    @classmethod
    def strip_re(cls, value: Any) -> str:
        if isinstance(value, str):
            value = value.strip()
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}", value):
            raise ValueError("O RE deve conter somente números e ter no máximo 5 dígitos.")
        return value


class ManagerInput(BaseModel):
    RE: str = Field(min_length=1, max_length=5)

    @field_validator("RE", mode="before")
    @classmethod
    def strip_re(cls, value: Any) -> str:
        if isinstance(value, str):
            value = value.strip()
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}", value):
            raise ValueError("O RE deve conter somente números e ter no máximo 5 dígitos.")
        return value


class UserUpdateInput(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    departamento: str = Field(default="", max_length=100)

    @field_validator("nome")
    @classmethod
    def strip_first_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Informe o primeiro nome.")
        return value.split()[0]

    @field_validator("departamento")
    @classmethod
    def strip_department(cls, value: str) -> str:
        return value.strip()


class PasswordUpdateInput(BaseModel):
    senha: str = Field(min_length=6, max_length=128)


class ProductionGoalInput(BaseModel):
    secao: str = Field(min_length=1, max_length=100)
    quantidade: int = Field(ge=0)

    @field_validator("secao")
    @classmethod
    def strip_section(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Informe a seção.")
        return value


def _create_token(employee_re: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": employee_re, "exp": int(time.time()) + 60 * 60 * 12}).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    return f"{payload}.{signature}"


def _read_token(token: str) -> str:
    try:
        payload, signature = token.split(".", maxsplit=1)
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(secret_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Assinatura inválida.")
        decoded_payload = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded_payload)
        if not isinstance(claims.get("sub"), str) or claims.get("exp", 0) < time.time():
            raise ValueError("Token expirado ou inválido.")
        return claims["sub"]
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.") from error


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, str]:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Faça login para continuar.")
    employee_re = _read_token(credentials.credentials)
    user = storage.get_user(employee_re)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado.")
    if not user["ativo"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este usuário está bloqueado.")
    return {
        **user,
        "perfil": "administrador" if is_admin(employee_re) else "gestor" if is_manager(employee_re) else "usuario",
    }


def manager_user(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    if not is_manager(user["RE"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a gestores autorizados.",
        )
    return user


def admin_user(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    if not is_admin(user["RE"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao administrador do sistema.",
        )
    return user


def _auth_response(user: dict[str, str]) -> dict[str, Any]:
    return {
        "token": _create_token(user["RE"]),
        "usuario": {
            **user,
            "perfil": "administrador" if is_admin(user["RE"]) else "gestor" if is_manager(user["RE"]) else "usuario",
        },
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "armazenamento": "firestore" if storage.use_firestore else "sqlite"}


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(data: RegistrationInput) -> dict[str, Any]:
    user = storage.get_user(data.RE)
    if user and not user["ativo"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este usuário está bloqueado.")
    registered_first_name = user["nome"].strip().split(maxsplit=1)[0] if user and user["nome"].strip() else ""
    if user and registered_first_name.casefold() != data.nome.casefold():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O primeiro nome informado não corresponde ao cadastro deste RE.",
        )
    if is_admin(data.RE):
        if not admin_password_hash or not _verify_password(data.senha, admin_password_hash):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A senha inicial do administrador não está configurada corretamente.",
            )
    else:
        if storage.get_password_hash(data.RE) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este RE já possui senha cadastrada.")
    if user is None:
        user = storage.create_user(data.RE, data.nome, data.departamento)
    else:
        user = storage.update_user(data.RE, user["nome"], data.departamento)
    storage.set_password_hash(
        data.RE,
        admin_password_hash if is_admin(data.RE) else _hash_password(data.senha),
    )

    return _auth_response(user)


@app.post("/api/auth/login")
def login(data: LoginInput) -> dict[str, Any]:
    user = storage.get_user(data.RE)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="RE não cadastrado. Faça o cadastro com seu primeiro nome e RE.",
        )
    if not user["ativo"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este usuário está bloqueado.")
    password_hash = storage.get_password_hash(data.RE)
    if is_admin(data.RE) and admin_password_hash:
        if password_hash != admin_password_hash:
            storage.set_password_hash(data.RE, admin_password_hash)
        password_hash = admin_password_hash
    if password_hash is None or not _verify_password(data.senha, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="RE ou senha incorretos.")
    return _auth_response(user)


@app.get("/api/auth/me")
def get_current_user(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return user


@app.get("/api/admin/gestores")
def list_managers(user: dict[str, str] = Depends(admin_user)) -> list[dict[str, Any]]:
    configured_managers = {
        value.strip()
        for value in os.getenv("DASHBOARD_MANAGER_RES", "").split(",")
        if value.strip()
    }
    all_manager_res = configured_managers | {user["RE"]} | storage.list_manager_res()
    users_by_re = {
        str(manager.get("RE", "")).strip(): manager
        for manager in storage.list_users()
        if str(manager.get("RE", "")).strip()
    }
    managers = []
    for employee_re in sorted(all_manager_res):
        manager = users_by_re.get(employee_re) or storage.get_user(employee_re)
        if manager is not None:
            managers.append(manager)
    return managers


@app.get("/api/admin/usuarios")
def list_users(user: dict[str, str] = Depends(admin_user)) -> list[dict[str, Any]]:
    return storage.list_users()


@app.put("/api/admin/usuarios/{employee_re}")
def update_user(
    employee_re: str,
    data: UserUpdateInput,
    user: dict[str, str] = Depends(admin_user),
) -> dict[str, Any]:
    if employee_re == admin_re:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O cadastro do administrador principal não pode ser alterado.")
    if re.fullmatch(r"[0-9]{1,5}", employee_re) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RE inválido.")
    existing_user = storage.get_user(employee_re)
    if existing_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    if employee_re in manager_res():
        ensure_manager_department_available(employee_re, data.departamento)
    return storage.update_user(employee_re, data.nome, data.departamento)


@app.put("/api/admin/usuarios/{employee_re}/senha")
def update_user_password(
    employee_re: str,
    data: PasswordUpdateInput,
    user: dict[str, str] = Depends(admin_user),
) -> dict[str, str]:
    if employee_re == admin_re:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A senha do administrador principal é definida por ADMIN_PASSWORD_HASH.",
        )
    if re.fullmatch(r"[0-9]{1,5}", employee_re) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RE inválido.")
    target_user = storage.get_user(employee_re)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    if not target_user["ativo"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este usuário está bloqueado.")
    storage.set_password_hash(employee_re, _hash_password(data.senha))
    return {"status": "Senha atualizada."}


@app.put("/api/admin/usuarios/{employee_re}/status")
def set_user_status(
    employee_re: str,
    active: bool,
    user: dict[str, str] = Depends(admin_user),
) -> dict[str, Any]:
    if employee_re == admin_re:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O administrador principal não pode ser bloqueado.")
    if re.fullmatch(r"[0-9]{1,5}", employee_re) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RE inválido.")
    target_user = storage.get_user(employee_re)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    storage.set_user_active(employee_re, active)
    return {**target_user, "ativo": active}


@app.get("/api/gestores/operadores")
def list_operators(user: dict[str, str] = Depends(manager_user)) -> list[dict[str, Any]]:
    users = storage.list_users()
    if is_admin(user["RE"]):
        department_users = users
    else:
        target_department = department_key(user.get("departamento"))
        department_users = [
            operator for operator in users
            if target_department
            and department_key(operator.get("departamento")) == target_department
        ]
    manager_ids = manager_res() | {admin_re}
    return [
        {**operator, "perfilGestor": operator["RE"] in manager_ids}
        for operator in department_users
    ]


@app.put("/api/gestores/operadores/{employee_re}/bloquear")
def block_operator(
    employee_re: str, user: dict[str, str] = Depends(manager_user)
) -> dict[str, Any]:
    if re.fullmatch(r"[0-9]{1,5}", employee_re) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="RE inválido.")
    if is_manager(employee_re):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gestores só podem bloquear operadores.")
    operator = storage.get_user(employee_re)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cadastro do operador não encontrado.")
    if not is_admin(user["RE"]) and department_key(operator.get("departamento")) != department_key(user.get("departamento")):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cadastro do operador não encontrado.")
    storage.set_user_active(employee_re, False)
    return {**operator, "ativo": False}


@app.post("/api/admin/gestores", status_code=status.HTTP_201_CREATED)
def add_manager(
    data: ManagerInput, user: dict[str, str] = Depends(admin_user)
) -> dict[str, Any]:
    manager = storage.get_user(data.RE)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Não existe usuário cadastrado com esse RE.",
        )
    if is_manager(data.RE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este usuário já possui acesso de gestor.",
        )
    ensure_manager_department_available(data.RE, manager.get("departamento", ""))
    storage.add_manager(data.RE)
    return manager


@app.get("/api/dashboard")
def dashboard(user: dict[str, str] = Depends(manager_user)) -> dict[str, Any]:
    users = storage.list_users()
    productions = records_for_department(storage.list_records("producoes"), user, users)
    remaining_records = records_for_department(
        storage.list_records("pecas_restantes"), user, users
    )
    latest_pieces_by_operator: dict[str, dict[str, Any]] = {}
    for record in remaining_records:
        employee_re = str(record.get("usuarioRe", "")).strip()
        record_key = employee_re or str(record.get("id", ""))
        current = latest_pieces_by_operator.get(record_key)
        if current is None or str(record.get("data", "")) > str(current.get("data", "")):
            latest_pieces_by_operator[record_key] = record

    return {
        "usuario": user,
        "producoes": productions,
        "pecas_restantes": remaining_records,
        "metas_producao": goals_for_department(
            storage.list_all_production_goals(),
            user,
            storage.list_records("producoes"),
            users,
        ),
        "resumo": {
            "total_produzido": sum(int(record.get("quantidade") or 0) for record in productions),
            "pecas_pendentes": sum(
                int(record.get(field) or 0)
                for record in latest_pieces_by_operator.values()
                for field in PIECES_FIELDS
            ),
        },
    }


@app.get("/api/producoes")
def list_productions(user: dict[str, str] = Depends(manager_user)) -> list[dict[str, Any]]:
    return records_for_department(
        storage.list_records("producoes"), user, storage.list_users()
    )


@app.get("/api/pecas-restantes")
def list_remaining_pieces(user: dict[str, str] = Depends(manager_user)) -> list[dict[str, Any]]:
    return records_for_department(
        storage.list_records("pecas_restantes"), user, storage.list_users()
    )


@app.get("/api/metas-producao")
def list_production_goals(
    user: dict[str, str] = Depends(manager_user),
) -> list[dict[str, Any]]:
    return goals_for_department(
        storage.list_all_production_goals(),
        user,
        storage.list_records("producoes"),
        storage.list_users(),
    )


@app.post("/api/metas-producao")
def save_production_goal(
    data: ProductionGoalInput, user: dict[str, str] = Depends(manager_user)
) -> dict[str, Any]:
    department = goal_department_for_section(
        data.secao,
        user,
        storage.list_records("producoes"),
        storage.list_users(),
    )
    return storage.save_production_goal(
        user["RE"], data.secao, data.quantidade, department
    )
