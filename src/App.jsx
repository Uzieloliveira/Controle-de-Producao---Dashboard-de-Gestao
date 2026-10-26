import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "./api.js";
import {
  buildProductionComparison,
  filterRecordsByPeriod,
  operatorBarWidths,
  sectionKey,
} from "./productionAnalytics.js";
import wegLogo from "../icon/weg.svg";

const pieceLabels = {
  acabamento: "Acabamento",
  amarracao: "Amarração",
  bandagem: "Bandagem",
  ligacao: "Ligação",
  prenca: "Prensa",
  solda: "Solda",
};

function localDateValue() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ nome: "", RE: "", departamento: "", senha: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result = await apiRequest(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(mode === "register" ? form : { RE: form.RE, senha: form.senha }),
      });
      onAuthenticated(result);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  function changeMode(nextMode) {
    setMode(nextMode);
    setError("");
  }

  return (
    <main className="auth-layout">
      <section className="auth-brand-panel">
        <div className="brand-lockup"><img className="brand-logo brand-logo-on-blue" src={wegLogo} alt="WEG" /><span className="brand-name">Produção</span></div>
        <div className="brand-message">
          <span className="eyebrow">CONTROLE DE PRODUÇÃO</span>
          <h1>Seu trabalho,<br />em cada detalhe.</h1>
          <p>Acompanhe a produção e mantenha seus registros organizados em um só lugar.</p>
        </div>
        <div className="brand-footer">PAINEL OPERACIONAL <span>•</span> 2026</div>
      </section>

      <section className="auth-form-panel">
        <div className="auth-form-wrap">
          <div className="mobile-brand brand-lockup"><img className="brand-logo" src={wegLogo} alt="WEG" /><span className="brand-name">Produção</span></div>
          <span className="eyebrow text-green">{mode === "login" ? "ACESSO AO PAINEL" : "PRIMEIRO ACESSO"}</span>
          <h2>{mode === "login" ? "Acesse com seu RE" : "Cadastre seu acesso"}</h2>
          <p className="form-intro">{mode === "login" ? "Informe seu RE e sua senha." : "Informe seu primeiro nome, RE, departamento e crie uma senha."}</p>

          <form onSubmit={submit} className="auth-form">
            {mode === "register" && (
              <>
                <label className="field-label">
                  Primeiro nome
                  <input className="form-control" autoComplete="given-name" required maxLength={100} value={form.nome} onChange={(event) => setForm({ ...form, nome: event.target.value })} placeholder="Digite seu primeiro nome" />
                </label>
                <label className="field-label">
                  Departamento
                  <input className="form-control" required maxLength={100} value={form.departamento} onChange={(event) => setForm({ ...form, departamento: event.target.value })} placeholder="Informe seu departamento" />
                </label>
              </>
            )}
            <label className="field-label">
              Registro de funcionário (RE)
              <input className="form-control" type="text" inputMode="numeric" pattern="[0-9]{1,5}" maxLength={5} autoComplete="username" required value={form.RE} onChange={(event) => setForm({ ...form, RE: event.target.value.replace(/[^0-9]/g, "").slice(0, 5) })} placeholder="Até 5 dígitos" />
            </label>
            <label className="field-label">
              Senha
              <input className="form-control" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={6} required value={form.senha} onChange={(event) => setForm({ ...form, senha: event.target.value })} placeholder={mode === "register" ? "Mínimo de 6 caracteres" : "Digite sua senha"} />
            </label>
            {error && <div role="alert" className="alert alert-danger py-2 mb-0">{error}</div>}
            <button className="btn btn-primary w-100 auth-submit" disabled={loading}>
              {loading ? "Aguarde..." : mode === "login" ? "Acessar sistema" : "Cadastrar"}
              {!loading && <span aria-hidden="true">→</span>}
            </button>
          </form>

          <p className="auth-switch">
            {mode === "login" ? "Ainda não tem acesso?" : "Já tem uma conta?"}{" "}
            <button type="button" onClick={() => changeMode(mode === "login" ? "register" : "login")}>
              {mode === "login" ? "Cadastre-se" : "Fazer login"}
            </button>
          </p>
          <p className="auth-note">O acesso usa RE e senha. Use este painel somente em ambiente autorizado.</p>
        </div>
      </section>
    </main>
  );
}

function Field({ label, children, className = "" }) {
  return <label className={`field-label ${className}`}>{label}{children}</label>;
}

function MetricCard({ label, value, caption, icon, accent }) {
  return (
    <article className={`metric-card ${accent || ""}`}>
      <div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div>
      <strong>{Number(value || 0).toLocaleString("pt-BR")}</strong>
      <small>{caption}</small>
    </article>
  );
}

function Dashboard({ token, user, onLogout }) {
  const [dashboard, setDashboard] = useState(null);
  const [activeTab, setActiveTab] = useState("producoes");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [goal, setGoal] = useState({ secao: "", quantidade: "" });
  const [managerRE, setManagerRE] = useState("");
  const [managers, setManagers] = useState([]);
  const [users, setUsers] = useState([]);
  const [operators, setOperators] = useState([]);
  const [productionGoals, setProductionGoals] = useState([]);
  const [userEdits, setUserEdits] = useState({});
  const [userPasswords, setUserPasswords] = useState({});
  const [comparisonMode, setComparisonMode] = useState("day");
  const [comparisonDate, setComparisonDate] = useState(localDateValue);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [refreshingDashboard, setRefreshingDashboard] = useState(false);
  const dashboardLoadAttempt = useRef(0);

  useEffect(() => {
    if (!notice) return undefined;
    const timeoutId = window.setTimeout(() => setNotice(""), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  const loadDashboard = useCallback(async () => {
    const data = await apiRequest("/dashboard", { token });
    setDashboard(data);
  }, [token]);

  const loadManagers = useCallback(async () => {
    const data = await apiRequest("/admin/gestores", { token });
    setManagers(data);
  }, [token]);

  const loadUsers = useCallback(async () => {
    const data = await apiRequest("/admin/usuarios", { token });
    setUsers(data);
    setUserEdits(Object.fromEntries(data.map((item) => [
      item.RE,
      { nome: item.nome, departamento: item.departamento || "" },
    ])));
  }, [token]);

  async function saveUserPassword(employeeRE) {
    const password = userPasswords[employeeRE] || "";
    if (password.length < 6) {
      setError("A senha deve ter pelo menos 6 caracteres.");
      return;
    }
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await apiRequest(`/admin/usuarios/${employeeRE}/senha`, {
        token,
        method: "PUT",
        body: JSON.stringify({ senha: password }),
      });
      setUserPasswords((currentPasswords) => ({
        ...currentPasswords,
        [employeeRE]: "",
      }));
      setNotice(`Senha do RE ${employeeRE} atualizada.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  const loadOperators = useCallback(async () => {
    const data = await apiRequest("/gestores/operadores", { token });
    setOperators(data);
  }, [token]);

  const loadProductionGoals = useCallback(async () => {
    const data = await apiRequest("/metas-producao", { token });
    setProductionGoals(data);
  }, [token]);

  const retryDashboardLoad = useCallback(async () => {
    const attempt = dashboardLoadAttempt.current + 1;
    dashboardLoadAttempt.current = attempt;
    setRefreshingDashboard(true);
    setError("");
    try {
      const results = await Promise.allSettled([loadDashboard(), loadOperators()]);
      if (attempt !== dashboardLoadAttempt.current) return;

      const failedRequest = results.find((result) => result.status === "rejected");
      if (failedRequest) {
        setError(failedRequest.reason instanceof Error
          ? failedRequest.reason.message
          : "Não foi possível carregar os dados do painel.");
      } else {
        setError("");
      }
    } finally {
      if (attempt === dashboardLoadAttempt.current) {
        setRefreshingDashboard(false);
      }
    }
  }, [loadDashboard, loadOperators]);

  useEffect(() => {
    retryDashboardLoad();
  }, [retryDashboardLoad]);

  useEffect(() => {
    if (activeTab === "admin" && (user.perfil === "administrador" || user.RE === "90829")) {
      loadManagers().catch((requestError) => setError(requestError.message));
    }
  }, [activeTab, loadManagers, user]);

  useEffect(() => {
    if (activeTab === "usuarios" && (user.perfil === "administrador" || user.RE === "90829")) {
      loadUsers().catch((requestError) => setError(requestError.message));
    }
  }, [activeTab, loadUsers, user]);

  useEffect(() => {
    if (activeTab === "metas" || activeTab === "producoes") {
      loadProductionGoals().catch((requestError) => setError(requestError.message));
    }
  }, [activeTab, loadProductionGoals]);

  const recentProduction = useMemo(
    () => filterRecordsByPeriod(
      dashboard?.producoes || [],
      comparisonMode,
      comparisonDate,
    ).slice(0, 6),
    [comparisonDate, comparisonMode, dashboard],
  );
  const recentPieces = useMemo(
    () => filterRecordsByPeriod(
      dashboard?.pecas_restantes || [],
      comparisonMode,
      comparisonDate,
    ).slice(0, 6),
    [comparisonDate, comparisonMode, dashboard],
  );
  const comparison = useMemo(() => {
    return buildProductionComparison(
      dashboard?.producoes || [],
      productionGoals,
      comparisonMode,
      comparisonDate,
      dashboard?.pecas_restantes || [],
      Object.keys(pieceLabels),
    );
  }, [comparisonDate, comparisonMode, dashboard, productionGoals]);

  const sectionScale = Math.max(1, ...comparison.sections.map((item) => item.quantidade));
  const remainingPiecesScale = Math.max(
    1,
    ...comparison.remainingPiecesByType.map((item) => item.quantidade),
  );
  const productionScale = Math.max(
    1,
    ...comparison.operators.flatMap((item) => [item.quantidade, item.meta]),
  );

  async function submitGoal(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await apiRequest("/metas-producao", {
        token,
        method: "POST",
        body: JSON.stringify({ secao: goal.secao, quantidade: Number(goal.quantidade) }),
      });
      setGoal({ secao: "", quantidade: "" });
      await loadProductionGoals();
      setNotice("Meta de produção salva com sucesso.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function submitManager(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setSaving(true);
    try {
      const manager = await apiRequest("/admin/gestores", {
        token,
        method: "POST",
        body: JSON.stringify({ RE: managerRE }),
      });
      setManagerRE("");
      await loadManagers();
      setNotice(`${manager.nome} agora tem acesso de gestor.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function saveUser(employeeRE) {
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await apiRequest(`/admin/usuarios/${employeeRE}`, {
        token,
        method: "PUT",
        body: JSON.stringify(userEdits[employeeRE]),
      });
      await loadUsers();
      setNotice("Cadastro atualizado com sucesso.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function setUserActive(employeeRE, active) {
    const action = active ? "reativar" : "bloquear";
    if (!window.confirm(`Deseja ${action} o acesso do RE ${employeeRE}?`)) return;
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await apiRequest(`/admin/usuarios/${employeeRE}/status?active=${active}`, {
        token,
        method: "PUT",
      });
      await loadUsers();
      setNotice(`Acesso do RE ${employeeRE} ${active ? "reativado" : "bloqueado"}.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function blockOperator(employeeRE) {
    if (!window.confirm(`Deseja bloquear o acesso do operador RE ${employeeRE}?`)) return;
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await apiRequest(`/gestores/operadores/${employeeRE}/bloquear`, {
        token,
        method: "PUT",
      });
      await loadOperators();
      setNotice(`Acesso do operador RE ${employeeRE} bloqueado.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("pt-BR");
  }

  const periodTotal = comparison.sections.reduce((total, item) => total + item.quantidade, 0);
  const remainingPiecesTotal = comparison.remainingPiecesByType.reduce(
    (total, item) => total + item.quantidade,
    0,
  );
  const pageTitles = {
    producoes: "Visão geral",
    pecas: "Peças restantes",
    metas: "Metas por seção",
    admin: "Administrar gestores",
    usuarios: "Administrar usuários",
    operadores: "Usuários registrados",
  };
  const isAdministrator = user.perfil === "administrador" || user.RE === "90829";
  const periodLabel = comparisonMode === "day"
    ? new Date(`${comparisonDate}T00:00:00`).toLocaleDateString("pt-BR")
    : new Date(`${comparisonDate}-01T00:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
        <div className="sidebar-header">
          <a className="brand-lockup sidebar-brand" href="#inicio"><img className="brand-logo brand-logo-on-blue" src={wegLogo} alt="WEG" />{!sidebarCollapsed && <span className="brand-name">Produção</span>}</a>
          <button type="button" className="sidebar-toggle" title={sidebarCollapsed ? "Expandir menu" : "Recolher menu"} aria-label={sidebarCollapsed ? "Expandir menu" : "Recolher menu"} onClick={() => setSidebarCollapsed((current) => !current)}>
            <span aria-hidden="true">{sidebarCollapsed ? "›" : "‹"}</span>
          </button>
        </div>
        {!sidebarCollapsed && <div className="sidebar-caption">MENU PRINCIPAL</div>}
        <button className={`nav-link ${activeTab === "producoes" ? "active" : ""}`} onClick={() => setActiveTab("producoes")}><span className="nav-link-icon">▦</span>{!sidebarCollapsed && <span className="nav-link-label">Visão geral</span>}</button>
        <button className={`nav-link ${activeTab === "pecas" ? "active" : ""}`} onClick={() => setActiveTab("pecas")}><span className="nav-link-icon">▧</span>{!sidebarCollapsed && <span className="nav-link-label">Peças restantes</span>}</button>
        {user.perfil !== "usuario" && <button className={`nav-link ${activeTab === "metas" ? "active" : ""}`} onClick={() => setActiveTab("metas")}><span className="nav-link-icon">◎</span>{!sidebarCollapsed && <span className="nav-link-label">Metas por seção</span>}</button>}
        {user.perfil !== "usuario" && <button className={`nav-link ${activeTab === "operadores" ? "active" : ""}`} onClick={() => setActiveTab("operadores")}><span className="nav-link-icon">♙</span>{!sidebarCollapsed && <span className="nav-link-label">Usuários registrados</span>}</button>}
        {isAdministrator && <button className={`nav-link ${activeTab === "usuarios" ? "active" : ""}`} onClick={() => setActiveTab("usuarios")}><span className="nav-link-icon">⚙</span>{!sidebarCollapsed && <span className="nav-link-label">Administrar usuários</span>}</button>}
        {isAdministrator && <button className={`nav-link ${activeTab === "admin" ? "active" : ""}`} onClick={() => setActiveTab("admin")}><span className="nav-link-icon">♙</span>{!sidebarCollapsed && <span className="nav-link-label">Administrar gestores</span>}</button>}
        <div className="sidebar-bottom">
          {!sidebarCollapsed && <div className="sidebar-status"><span className="status-dot" /> Sistema operacional</div>}
          <div className={`profile-card ${sidebarCollapsed ? "collapsed" : ""}`}>
            <div className="avatar">{user.nome?.trim().charAt(0).toUpperCase() || "U"}</div>
            {!sidebarCollapsed && (
              <>
                <div className="profile-info"><strong>{user.nome}</strong><small>RE {user.RE}</small><small>{user.departamento || "Departamento não informado"}</small></div>
                <button className="logout-button" title="Sair da conta" onClick={onLogout} aria-label="Sair da conta">↗</button>
              </>
            )}
            {sidebarCollapsed && <button className="logout-button compact" title="Sair da conta" onClick={onLogout} aria-label="Sair da conta">↗</button>}
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb-label">PAINEL <span>/</span> {pageTitles[activeTab].toLocaleUpperCase("pt-BR")}</div>
          <div className="topbar-right"><span className="today-label">{new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</span><span className="topbar-avatar">{user.nome?.trim().charAt(0).toUpperCase() || "U"}</span></div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div><span className="eyebrow text-green">ACOMPANHAMENTO OPERACIONAL</span><h1>{pageTitles[activeTab]}</h1><p>{activeTab === "metas" ? "Defina e acompanhe suas metas individuais de produção por seção." : activeTab === "admin" ? "Conceda acesso de gestor a usuários que já possuem cadastro." : `Olá, ${user.nome?.split(" ")[0] || "bem-vindo"}. Aqui está o resumo dos seus registros.`}</p></div>
            <div className="date-chip"><span>◷</span> {new Date().toLocaleDateString("pt-BR")}</div>
          </div>

          {error && (
            <div role="alert" className="alert alert-danger d-flex align-items-center justify-content-between gap-3">
              <span>{error}</span>
              <button
                className="btn btn-sm btn-outline-danger flex-shrink-0"
                disabled={refreshingDashboard}
                onClick={retryDashboardLoad}
              >
                {refreshingDashboard ? "Conectando..." : "Tentar novamente"}
              </button>
            </div>
          )}
          {notice && <div role="status" className="alert alert-success">{notice}</div>}

          {(activeTab === "producoes" || activeTab === "pecas") && (
            <section className={`metrics-grid ${activeTab === "producoes" ? "section-metrics-grid" : ""}`}>
              {activeTab === "producoes" ? (
                comparison.sections.length > 0
                  ? comparison.sections.map((item) => (
                    <MetricCard
                      key={sectionKey(item.secao)}
                      label={item.secao}
                      value={item.quantidade}
                      caption={`${comparisonMode === "day" ? "no dia" : "no mês"} selecionado`}
                      icon="↗"
                    />
                  ))
                  : <p className="empty-state section-metrics-empty">Não há seções com produção registrada.</p>
              ) : (
                <MetricCard label="Peças restantes" value={remainingPiecesTotal} caption={`${comparisonMode === "day" ? "no dia" : "no mês"} selecionado`} icon="◉" accent="metric-warm" />
              )}
            </section>
          )}

          {!["operadores", "admin", "metas"].includes(activeTab) && <div className="comparison-toolbar dashboard-period-toolbar">
            <div className="comparison-period">
              <label htmlFor="comparison-mode">Comparar por</label>
              <select id="comparison-mode" className="form-select form-select-sm" value={comparisonMode} onChange={(event) => {
                const nextMode = event.target.value;
                setComparisonMode(nextMode);
                if (nextMode === "day" && comparisonDate.length === 7) {
                  setComparisonDate(`${comparisonDate}-01`);
                } else if (nextMode === "month" && comparisonDate.length === 10) {
                  setComparisonDate(comparisonDate.slice(0, 7));
                }
              }}>
                <option value="day">Dia</option>
                <option value="month">Mês</option>
              </select>
            </div>
            <div className="comparison-period">
              <label htmlFor="comparison-date">{comparisonMode === "day" ? "Data" : "Mês"}</label>
              <input id="comparison-date" className="form-control form-control-sm" type={comparisonMode === "day" ? "date" : "month"} value={comparisonMode === "day" ? comparisonDate : comparisonDate.slice(0, 7)} onChange={(event) => setComparisonDate(event.target.value)} />
            </div>
            <span className="comparison-period-label">{periodLabel}</span>
          </div>}

          {activeTab === "admin" ? (
            <section className="admin-layout">
              <div className="content-card admin-card">
                <div className="card-heading">
                  <div><span className="eyebrow text-green">ACESSO AO PAINEL</span><h2>Gestores autorizados</h2></div>
                  <div className="record-count">{managers.length} gestores</div>
                </div>
                <div className="manager-list">
                  {managers.map((manager) => (
                    <div className="manager-row" key={manager.RE}>
                      <div className="avatar">{manager.nome?.trim().charAt(0).toUpperCase() || "U"}</div>
                      <div className="manager-info"><strong>{manager.nome}</strong><small>RE {manager.RE}</small></div>
                      <span className={`manager-badge ${manager.RE === "90829" ? "administrator" : ""}`}>{manager.RE === "90829" ? "Administrador" : "Gestor"}</span>
                    </div>
                  ))}
                  {managers.length === 0 && <p className="empty-state">Nenhum gestor cadastrado.</p>}
                </div>
              </div>
              <div className="content-card form-card">
                <div className="card-heading"><div><span className="eyebrow text-green">NOVO ACESSO</span><h2>Cadastrar gestor</h2></div></div>
                <form className="record-form" onSubmit={submitManager}>
                  <Field label="RE de usuário já cadastrado">
                    <input className="form-control" type="text" inputMode="numeric" pattern="[0-9]{1,5}" maxLength={5} required value={managerRE} onChange={(event) => setManagerRE(event.target.value.replace(/[^0-9]/g, "").slice(0, 5))} placeholder="Até 5 dígitos" />
                  </Field>
                  <p className="goal-help">Somente usuários já cadastrados podem receber acesso. Gestores podem consultar a produção e as peças de todos os REs.</p>
                  <button className="btn btn-primary submit-record" disabled={saving}>{saving ? "Salvando..." : "Conceder acesso de gestor"} <span>→</span></button>
                </form>
              </div>
            </section>
          ) : activeTab === "usuarios" ? (
            <section className="content-card records-card">
              <div className="card-heading">
                <div><span className="eyebrow text-green">ADMINISTRAÇÃO</span><h2>Cadastros de usuários</h2></div>
                <div className="record-count">{users.length} usuários</div>
              </div>
              <p className="goal-help">Bloquear impede novos acessos, mas preserva o cadastro e todos os históricos. O RE administrador principal não pode ser alterado ou bloqueado.</p>
              <div className="table-responsive">
                <table className="table align-middle">
                  <thead><tr><th>RE</th><th>Primeiro nome</th><th>Departamento</th><th>Status</th><th>Senha</th><th>Ações</th></tr></thead>
                  <tbody>{users.map((item) => {
                    const protectedAdmin = item.RE === user.RE;
                    const edit = userEdits[item.RE] || { nome: item.nome, departamento: item.departamento || "" };
                    return (
                      <tr key={item.RE}>
                        <td>{item.RE}</td>
                        <td><input className="form-control form-control-sm" value={edit.nome} disabled={protectedAdmin} onChange={(event) => setUserEdits({ ...userEdits, [item.RE]: { ...edit, nome: event.target.value } })} /></td>
                        <td><input className="form-control form-control-sm" value={edit.departamento} disabled={protectedAdmin} onChange={(event) => setUserEdits({ ...userEdits, [item.RE]: { ...edit, departamento: event.target.value } })} /></td>
                        <td><span className={`badge ${item.ativo ? "text-bg-success" : "text-bg-secondary"}`}>{item.ativo ? "Ativo" : "Bloqueado"}</span></td>
                        <td>{!protectedAdmin && <div className="user-password-edit"><input className="form-control form-control-sm" type="password" minLength={6} autoComplete="new-password" aria-label={`Nova senha do RE ${item.RE}`} placeholder="Nova senha" value={userPasswords[item.RE] || ""} onChange={(event) => setUserPasswords({ ...userPasswords, [item.RE]: event.target.value })} /><button className="btn btn-sm btn-outline-primary" disabled={saving || (userPasswords[item.RE] || "").length < 6} onClick={() => saveUserPassword(item.RE)}>Atualizar senha</button></div>}</td>
                        <td className="d-flex gap-2">
                          {!protectedAdmin && <><button className="btn btn-sm btn-outline-primary" disabled={saving} onClick={() => saveUser(item.RE)}>Salvar cadastro</button><button className={`btn btn-sm ${item.ativo ? "btn-outline-danger" : "btn-outline-success"}`} disabled={saving} onClick={() => setUserActive(item.RE, !item.ativo)}>{item.ativo ? "Bloquear" : "Reativar"}</button></>}
                          {protectedAdmin && <span className="text-muted small">Protegido</span>}
                        </td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            </section>
          ) : activeTab === "operadores" ? (
            <section className="content-card records-card">
              <div className="card-heading">
                <div><span className="eyebrow text-green">USUÁRIOS DO SISTEMA</span><h2>Usuários registrados</h2></div>
                <div className="record-count">{operators.length} usuários</div>
              </div>
              <p className="goal-help">Gestores podem bloquear usuários. O bloqueio preserva o cadastro e os registros existentes; para reativar o acesso, solicite ao administrador.</p>
              <div className="manager-list">
                {operators.map((operator) => (
                  <div className="manager-row" key={operator.RE}>
                    <div className="avatar">{operator.nome?.trim().charAt(0).toUpperCase() || "U"}</div>
                    <div className="manager-info"><strong>{operator.nome || "Usuário sem cadastro"}</strong><small>RE {operator.RE}{operator.departamento ? ` · ${operator.departamento}` : ""}</small></div>
                    <span className={`badge ${operator.ativo ? "text-bg-success" : "text-bg-secondary"}`}>{operator.ativo ? "Ativo" : "Bloqueado"}</span>
                    {!operator.perfilGestor && operator.ativo && <button className="btn btn-sm btn-outline-danger" disabled={saving} onClick={() => blockOperator(operator.RE)}>Bloquear</button>}
                  </div>
                ))}
                {operators.length === 0 && <p className="empty-state">Nenhum usuário encontrado nos registros de produção.</p>}
              </div>
            </section>
          ) : activeTab === "metas" ? (
            <section className="goals-layout">
              <div className="content-card goals-card">
                <div className="card-heading">
                  <div><span className="eyebrow text-green">ACOMPANHAMENTO</span><h2>Metas cadastradas</h2></div>
                  <div className="record-count">{productionGoals.length} metas</div>
                </div>
                <div className="goals-list">
                  {productionGoals.map((item) => {
                    return (
                      <article className="goal-item" key={item.id}>
                        <div className="goal-summary"><strong>{item.secao}</strong><span>{Number(item.quantidade).toLocaleString("pt-BR")} un. / operador / dia</span></div>
                      </article>
                    );
                  })}
                  {productionGoals.length === 0 && <p className="empty-state">Você ainda não cadastrou metas de produção.</p>}
                </div>
              </div>
              <div className="content-card form-card">
                <div className="card-heading"><div><span className="eyebrow text-green">NOVA META</span><h2>Meta de produção</h2></div></div>
                <form className="record-form" onSubmit={submitGoal}>
                  <Field label="Seção"><input className="form-control" required maxLength={100} value={goal.secao} onChange={(event) => setGoal({ ...goal, secao: event.target.value })} placeholder="Ex.: Montagem" /></Field>
                  <Field label="Quantidade da meta"><input className="form-control" type="number" required min="0" step="1" value={goal.quantidade} onChange={(event) => setGoal({ ...goal, quantidade: event.target.value })} placeholder="Ex.: 500" /></Field>
                  <p className="goal-help">A meta diária da seção é aplicada individualmente a cada operador. Salvar novamente a mesma seção atualiza o valor.</p>
                  <button className="btn btn-primary submit-record" disabled={saving}>{saving ? "Salvando..." : "Salvar meta"} <span>→</span></button>
                </form>
              </div>
            </section>
          ) : <section className="workspace-grid">
            <div className="content-card records-card">
              <div className="card-heading">
                <div><span className="eyebrow text-green">DADOS DO APLICATIVO MOBILE</span><h2>{activeTab === "producoes" ? "Produção e comparativos" : "Peças registradas"}</h2></div>
              </div>
              {activeTab === "producoes" ? (
                <>
                <div className="charts-grid">
                  <div className="content-card chart-card">
                    <div className="card-heading"><div><span className="eyebrow text-green">ATINGIMENTO DE META</span><h2>Produzido x meta por operador</h2></div></div>
                    <div className="chart-content">
                      {comparison.operators.map((item) => {
                        const percent = item.meta > 0 ? Math.round((item.quantidade / item.meta) * 100) : null;
                        const barWidths = operatorBarWidths(item.quantidade, item.meta, productionScale);
                        return (
                          <article className="operator-chart-row" key={`${sectionKey(item.secao)}-${sectionKey(item.operador)}`}>
                            <div className="operator-chart-heading"><strong>{item.operador}</strong><span>{item.secao} · {percent === null ? "Meta não definida" : `${percent}% atingido`}</span></div>
                            <div className="comparison-bar"><span>Produzido</span><div className="bar-track"><div className="bar-fill produced" style={{ width: `${barWidths.produced}%` }} /></div><strong>{item.quantidade.toLocaleString("pt-BR")}</strong></div>
                            <div className="comparison-bar"><span>Meta diária</span><div className="bar-track"><div className="bar-fill target" style={{ width: `${barWidths.target}%` }} /></div><strong>{item.meta.toLocaleString("pt-BR")}</strong></div>
                          </article>
                        );
                      })}
                      {comparison.operators.length === 0 && <p className="empty-state">Nenhum operador cadastrado para exibir.</p>}
                    </div>
                    <div className="chart-legend"><span><i className="legend-produced" /> Produzido</span><span><i className="legend-target" /> Meta individual por operador</span></div>
                  </div>
                  <div className="content-card chart-card section-production-card">
                    <div className="card-heading"><div><span className="eyebrow text-green">PRODUTIVIDADE DA SEÇÃO</span><h2>Total produzido por seção</h2></div></div>
                    <div className="chart-content section-chart">
                      {comparison.sections.map((item) => (
                        <div className="section-chart-row" key={sectionKey(item.secao)}>
                          <div className="section-chart-heading"><strong>{item.secao}</strong><span>{item.quantidade.toLocaleString("pt-BR")} un.</span></div>
                          <div className="bar-track"><div className="bar-fill produced" style={{ width: `${Math.min(100, item.quantidade / sectionScale * 100)}%` }} /></div>
                        </div>
                      ))}
                      {comparison.sections.length === 0 && <p className="empty-state">Não há produção registrada para {periodLabel}.</p>}
                    </div>
                    <div className="section-total">Total produzido no período <strong>{periodTotal.toLocaleString("pt-BR")} un.</strong></div>
                  </div>
                  <div className="content-card chart-card">
                    <div className="card-heading"><div><span className="eyebrow text-green">ESTOQUE EM PROCESSO</span><h2>Peças restantes por seção</h2></div></div>
                    <div className="chart-content section-chart">
                      {comparison.remainingPiecesByType.map((item) => (
                        <div className="section-chart-row" key={item.field}>
                          <div className="section-chart-heading"><strong>{pieceLabels[item.field] || item.field}</strong><span>{item.quantidade.toLocaleString("pt-BR")} un.</span></div>
                          <div className="bar-track"><div className="bar-fill remaining" style={{ width: `${Math.min(100, item.quantidade / remainingPiecesScale * 100)}%` }} /></div>
                        </div>
                      ))}
                      {comparison.remainingPiecesByType.length === 0 && <p className="empty-state">Não há tipos de peças configurados.</p>}
                    </div>
                    <div className="section-total">Total de peças restantes <strong>{remainingPiecesTotal.toLocaleString("pt-BR")} un.</strong></div>
                  </div>
                </div>
                <div className="card-heading recent-heading">
                  <div><span className="eyebrow text-green">HISTÓRICO</span><h2>Produção recente</h2></div>
                </div>
                <div className="table-responsive">
                  <table className="table production-table align-middle">
                    <thead><tr><th>DATA</th><th>OPERADOR / SEÇÃO</th><th>QUANTIDADE</th><th>OBSERVAÇÕES</th></tr></thead>
                    <tbody>
                      {recentProduction.map((record) => <tr key={record.id}><td>{formatDate(record.data)}</td><td><strong>{record.operador}</strong><small>{record.secao}</small></td><td><strong>{Number(record.quantidade).toLocaleString("pt-BR")}</strong> un.</td><td className="observation-cell">{String(record.anotacao || "").trim() || "—"}</td></tr>)}
                      {recentProduction.length === 0 && <tr><td colSpan="4" className="empty-state">Nenhuma produção registrada ainda.</td></tr>}
                    </tbody>
                  </table>
                </div>
                </>
              ) : (
                <div className="table-responsive">
                  <table className="table production-table align-middle">
                    <thead><tr><th>DATA</th>{Object.values(pieceLabels).map((label) => <th key={label}>{label.toUpperCase()}</th>)}</tr></thead>
                    <tbody>
                      {recentPieces.map((record) => <tr key={record.id}><td>{formatDate(record.data)}</td>{Object.keys(pieceLabels).map((field) => <td key={field}>{Number(record[field] || 0).toLocaleString("pt-BR")}</td>)}</tr>)}
                      {recentPieces.length === 0 && <tr><td colSpan="7" className="empty-state">Nenhum registro de peças restantes.</td></tr>}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>}
          <footer className="page-footer">Controle de Produção <span>•</span> Seus dados são vinculados ao RE {user.RE}</footer>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("production-session") || "null");
    } catch {
      return null;
    }
  });

  function authenticate(result) {
    localStorage.setItem("production-session", JSON.stringify(result));
    setSession(result);
  }

  function logout() {
    localStorage.removeItem("production-session");
    setSession(null);
  }

  return session?.token && session?.usuario
    ? <Dashboard token={session.token} user={session.usuario} onLogout={logout} />
    : <AuthScreen onAuthenticated={authenticate} />;
}
