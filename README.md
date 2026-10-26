# 🏭 Controle de Produção

Aplicação web para acompanhar produção e peças restantes, comparar resultados por período, cadastrar metas por seção e administrar usuários e gestores. A interface é feita com React e Vite; a API é feita com Python e FastAPI. O armazenamento principal pode ser o Cloud Firestore; há também um modo SQLite para desenvolvimento local.

## 📚 Índice

- [✨ Funcionalidades](#funcionalidades)
- [🧰 Tecnologias e requisitos](#tecnologias-e-requisitos)
- [📦 Instalação local](#instalação-local)
- [☁️ Configuração do Firestore](#configuração-do-firestore)
- [▶️ Executar o sistema](#executar-o-sistema)
- [🌐 Configuração fora do desenvolvimento local](#configuração-fora-do-desenvolvimento-local)
- [👥 Funcionalidades por perfil](#funcionalidades-por-perfil)
- [🗃️ Banco de dados e estrutura](#banco-de-dados-e-estrutura)
- [🔌 Endpoints principais](#endpoints-principais)
- [🧪 Testes](#testes)
- [🗂️ Estrutura principal](#estrutura-principal)

## ✨ Funcionalidades

- Cadastro e login com RE numérico (até 5 dígitos) e senha.
- Visão geral com filtro por dia ou mês, totais produzidos por seção, comparação de produção por operador e metas.
- Cartões de produção individuais por seção, organizados em grade responsiva.
- Consulta de peças restantes por tipo: acabamento, amarração, bandagem, ligação, prensa e solda.
- Cadastro e consulta de metas diárias por seção. A meta é comparada individualmente para cada operador da seção.
- Consulta de usuários registrados e bloqueio de operadores por gestores.
- Administração de usuários: edição de nome e departamento, redefinição de senha, bloqueio e reativação.
- Administração de gestores pelo administrador.
- Filtro de acesso dos gestores por departamento; o administrador pode consultar todos os departamentos.

Os registros de produção e peças restantes são somente leitura nesta API e são alimentados pelo aplicativo que os coleta (por exemplo, o aplicativo mobile). O painel web não cria nem edita esses registros.

## 🧰 Tecnologias e requisitos

- Windows 10/11 (os comandos abaixo são para PowerShell).
- Node.js 18 ou superior e npm.
- Python 3.10 ou superior e pip.
- Projeto Google Cloud com Cloud Firestore habilitado para usar o banco Firestore.
- Google Cloud CLI, se for usar a autenticação ADC por usuário. Como alternativa, é possível autenticar com uma conta de serviço protegida.

Downloads oficiais:

- [Node.js](https://nodejs.org/en/download)
- [Python](https://www.python.org/downloads/)
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)

O Google Cloud CLI é necessário somente para o fluxo `gcloud auth application-default login`. Não é necessário instalar o Firebase CLI para executar esta aplicação.

## 📦 Instalação local

Abra o PowerShell na pasta do projeto e instale as dependências:

```powershell
npm ci
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Se o PowerShell bloquear a ativação do ambiente virtual, permita scripts apenas para o terminal atual e tente novamente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Também é possível executar o Python do ambiente sem ativá-lo, usando `.\.venv\Scripts\python.exe` nos comandos abaixo.

## ☁️ Configuração do Firestore

O backend acessa o **Cloud Firestore pelo SDK Python `google-cloud-firestore`**. Não usa o Firebase Authentication: cadastro, validação de senha e sessão são feitos pela API deste sistema. No console do Google Cloud ou Firebase:

1. Selecione ou crie um projeto Google Cloud.
2. Ative a API Cloud Firestore.
3. Crie um banco de dados Firestore no modo nativo.
4. Configure uma identidade de execução com permissão para ler e gravar no Firestore (por exemplo, o papel **Cloud Datastore User**, `roles/datastore.user`). Para desenvolvimento, pode usar ADC de usuário; para implantação, prefira uma conta de serviço com privilégio mínimo e mantenha a chave fora da pasta do projeto.

### 🔐 Autenticação de desenvolvimento com ADC

Instale o Google Cloud CLI e execute no PowerShell:

```powershell
gcloud auth application-default login
gcloud config set project SEU_PROJECT_ID
```

Substitua `SEU_PROJECT_ID` pelo ID real do seu projeto. A identidade autenticada precisa ter permissão de leitura e gravação no Firestore. O backend usa as credenciais ADC automaticamente.

Como alternativa, defina `GOOGLE_APPLICATION_CREDENTIALS` apontando para o arquivo JSON de uma conta de serviço. Guarde esse arquivo fora do repositório e não o compartilhe. Este repositório ignora arquivos com nomes comuns de chave de serviço no `.gitignore`; se uma chave já tiver sido publicada ou compartilhada, revogue-a no Google Cloud e gere outra.

### ⚙️ Arquivo `.env`

Crie ou edite `.env` na raiz do projeto. Este arquivo não deve ser versionado nem compartilhado:

```dotenv
APP_ENV=development
APP_SECRET_KEY=SUBSTITUA_POR_UMA_CHAVE_ALEATORIA_LONGA
ADMIN_RE=90829
ADMIN_PASSWORD_HASH=COLE_AQUI_O_HASH_SCRYPT
FIRESTORE_ENABLED=true
GOOGLE_CLOUD_PROJECT=SEU_PROJECT_ID
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
# Opcional: caminho para chave de serviço fora do projeto, se não usar ADC.
# GOOGLE_APPLICATION_CREDENTIALS=C:\caminho\seguro\service-account.json
# Opcional: REs de gestores iniciais, separados por vírgula.
# DASHBOARD_MANAGER_RES=12345,67890
```

`GOOGLE_APPLICATION_CREDENTIALS` é opcional quando as ADC já estiverem configuradas. `FRONTEND_ORIGINS` deve conter a origem do navegador que acessará a API, sem caminho adicional.

Gere uma chave aleatória para `APP_SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

O administrador inicial deve usar `ADMIN_RE` e uma senha cujo hash scrypt seja configurado em `ADMIN_PASSWORD_HASH`. Para gerar um hash compatível, execute o script abaixo, digite a senha quando solicitado e copie somente o hash impresso para `.env`:

```powershell
@'
import base64
import getpass
import hashlib
import secrets

password = getpass.getpass("Senha inicial do administrador: ")
salt = secrets.token_bytes(16)
digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
print(f"{encode(salt)}${encode(digest)}")
'@ | python -
```

O usuário administrador deve se cadastrar com o RE configurado em `ADMIN_RE` e a senha correspondente ao hash. Se esse RE ainda não existir em `usuarios`, o cadastro cria o documento. Para outros usuários, o cadastro solicita RE, primeiro nome, departamento e uma senha de pelo menos 6 caracteres. Se o RE já existir, o primeiro nome informado precisa corresponder ao cadastro existente.

`ADMIN_RE` é o RE administrador reconhecido pelo backend. `DASHBOARD_MANAGER_RES` é opcional e concede acesso de gestor aos REs listados; gestores também podem ser concedidos pelo painel administrativo. O administrador principal não pode ser bloqueado nem ter o cadastro alterado pelo painel.

### 🗃️ Alternar para SQLite

Para desenvolvimento sem Firestore, configure:

```dotenv
FIRESTORE_ENABLED=false
```

O backend cria e inicializa automaticamente `backend\controle_producao.db`. Esse banco SQLite local não é sincronizado com o Firestore. Não altere o valor de `FIRESTORE_ENABLED` esperando que os dados sejam migrados entre os bancos.

## ▶️ Executar o sistema

Com `.env` configurado, abra dois terminais na raiz do projeto.

Terminal 1 — API:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```powershell
npm run dev
```

Abra [http://localhost:5173](http://localhost:5173). O Vite encaminha as chamadas `/api` para `http://127.0.0.1:8000`; portanto, mantenha ambos os processos em execução. Para verificar o backend, acesse [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health). A documentação interativa da API fica em [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## 🌐 Configuração fora do desenvolvimento local

Se a API estiver hospedada em outro endereço, defina `VITE_API_URL` antes de iniciar ou compilar o frontend. O valor deve incluir o prefixo da API, por exemplo:

```powershell
$env:VITE_API_URL = "https://api.exemplo.com/api"
npm run build
```

Configure `FRONTEND_ORIGINS` no backend com a origem exata do site, como `https://painel.exemplo.com`. Em produção:

- Defina `APP_ENV=production` e configure uma `APP_SECRET_KEY` forte e exclusiva. O backend recusa iniciar em produção se a chave padrão de desenvolvimento estiver em uso.
- Armazene `.env`, hashes e credenciais em um gerenciador de segredos ou configuração protegida da plataforma; não os inclua no bundle do frontend.
- Execute a API com um servidor ASGI adequado ao ambiente. `--reload` é somente para desenvolvimento.
- Publique o resultado de `npm run build` (`dist`) em um servidor estático e configure HTTPS e o encaminhamento para a API.
- Não exponha a chave JSON da conta de serviço, nem permita acesso irrestrito ao Firestore pelo navegador.

## 👥 Funcionalidades por perfil

| Perfil | Acesso |
| --- | --- |
| Usuário | Cadastro/login; a API reserva a consulta do painel operacional para gestores e administrador. |
| Gestor | Consulta produção, peças restantes, metas e operadores do próprio departamento; cadastra metas e pode bloquear operadores do departamento. |
| Administrador | Consulta todos os departamentos; administra cadastros, senhas, status de usuários e acesso de gestores. |

O token de sessão é assinado pelo backend e expira após 12 horas. As senhas dos usuários são armazenadas com scrypt, nunca em texto puro. O hash configurado em `ADMIN_PASSWORD_HASH` é a credencial inicial usada para o administrador.

## 🗃️ Banco de dados e estrutura

Com Firestore ativado, o backend usa as seguintes coleções. Elas são criadas pelo Firestore quando os documentos são gravados; os dados de produção e peças podem ser inseridos pelo aplicativo mobile que os coleta.

| Coleção | Conteúdo principal |
| --- | --- |
| `usuarios` | `RE`, `nome`, `departamento`, `ativo`. |
| `contas` | `usuarioRe`, `passwordHash` (hash scrypt). |
| `gestores` | `usuarioRe` para os REs autorizados como gestores. |
| `producoes` | `anotacao`, `data`, `departamento`, `enviado`, `operador`, `quantidade`, `secao`, `usuarioRe`. |
| `pecas_restantes` | `acabamento`, `amarracao`, `bandagem`, `data`, `ligacao`, `prenca`, `solda`, `usuarioRe`. |
| `metas_producao` | `usuarioRe`, `secao`, `quantidade`, `departamento`. Uma meta é identificada pelo gestor e pela seção. |

O backend interpreta os campos de produção e peças restantes como registros de histórico. Na comparação por dia/mês, os totais de produção são somados no período. As peças restantes usam o registro mais recente de cada operador dentro do período selecionado. No modo mensal, a meta exibida continua sendo diária e não é multiplicada pelo número de dias do mês. As datas dos registros podem estar em formato ISO ou brasileiro.

Com Firestore desativado, o SQLite cria as tabelas equivalentes `users`, `accounts`, `gestores`, `producoes`, `pecas_restantes` e `metas_producao` em `backend\controle_producao.db`.

## 🔌 Endpoints principais

Entre as rotas de negócio abaixo, todas exceto health check, login e cadastro exigem autenticação Bearer. As rotas administrativas exigem administrador e as rotas operacionais exigem gestor ou administrador.

| Método | Rota | Acesso / finalidade |
| --- | --- | --- |
| `GET` | `/api/health` | Verifica API e tipo de armazenamento ativo. |
| `POST` | `/api/auth/register` | Cria credenciais de acesso para um RE não bloqueado. |
| `POST` | `/api/auth/login` | Inicia sessão com RE e senha. |
| `GET` | `/api/auth/me` | Retorna o usuário autenticado. |
| `GET` | `/api/dashboard` | Carrega dados operacionais e resumos permitidos ao perfil. |
| `GET` | `/api/producoes` | Consulta registros de produção. |
| `GET` | `/api/pecas-restantes` | Consulta registros de peças restantes. |
| `GET`, `POST` | `/api/metas-producao` | Lista ou grava metas por seção. |
| `GET`, `POST` | `/api/admin/gestores` | Lista ou concede acesso de gestor (administrador). |
| `GET` | `/api/admin/usuarios` | Lista cadastros de usuários (administrador). |
| `PUT` | `/api/admin/usuarios/{RE}` | Atualiza nome e departamento (administrador). |
| `PUT` | `/api/admin/usuarios/{RE}/senha` | Redefine senha de usuário (administrador). |
| `PUT` | `/api/admin/usuarios/{RE}/status?active=true\|false` | Ativa/bloqueia usuário (administrador). |
| `GET` | `/api/gestores/operadores` | Lista usuários do escopo do gestor. |
| `PUT` | `/api/gestores/operadores/{RE}/bloquear` | Bloqueia operador do departamento do gestor. |

## 🧪 Testes

Na raiz do projeto:

```powershell
npm test
python -m unittest discover -s backend -p "test_*.py"
```

Para gerar o bundle de produção do frontend:

```powershell
npm run build
```

## 🗂️ Estrutura principal

```text
src\
  App.jsx                  Interface e telas do painel
  api.js                   Cliente HTTP da API
  productionAnalytics.js   Filtros e cálculos de produção
  productionAnalytics.test.js
  styles.css               Estilos e layout responsivo
backend\
  main.py                  API FastAPI, autenticação e regras de acesso
  storage.py               Persistência Firestore/SQLite
  test_main.py
  test_storage.py
  controle_producao.db     Banco local (criado no modo SQLite)
icon\
  weg.svg                  Logotipo usado pela interface
```