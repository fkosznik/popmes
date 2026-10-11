import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronRight,
  CircleAlert,
  Clock3,
  ClipboardList,
  Factory,
  FileText,
  LayoutDashboard,
  LogOut,
  Package,
  Pause,
  Play,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Users,
  Warehouse,
  X,
  Zap,
  RefreshCw,
  Pencil,
  Popcorn,
  Menu,
  Ban,
  History,
  Upload,
  Boxes,
} from "lucide-react";
import { api, requestKey } from "./api";
import type {
  User,
  State,
  Task,
  Order,
  Detail,
  Product,
  Variant,
  Customer,
  Report,
  Batch,
} from "./types";

const names: Record<string, string> = {
  draft: "Szkic",
  queued: "Do realizacji",
  in_progress: "W realizacji",
  completed: "Zrealizowane",
  issued: "Wydane",
  cancelled: "Anulowane",
  ready: "Do wykonania",
  waiting: "Oczekujące",
  done: "Wykonane",
};
const roleNames: Record<string, string> = {
  sales: "Sprzedaż",
  production: "Produkcja",
  packing: "Pakowanie",
  manager: "Kierownik",
  admin: "Administrator",
};
const fmt = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 });
const kg = (g: string | number) => fmt.format(Number(g) / 1000) + " kg";
const dt = (s: string | null) =>
  s
    ? new Date(s).toLocaleString("pl-PL", {
        timeZone: "Europe/Warsaw",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Brak terminu";
const late = (o: Order) =>
  Boolean(
    o.due_at &&
    new Date(o.due_at) < new Date() &&
    !["completed", "issued", "cancelled", "draft"].includes(o.status),
  );
const localDate = (s: string | null) =>
  s
    ? new Date(s)
        .toLocaleString("sv-SE", { timeZone: "Europe/Warsaw" })
        .slice(0, 16)
        .replace(" ", "T")
    : "";
// Inputs represent Warsaw local time; use Intl to calculate the correct UTC offset including DST.
function fromWarsaw(value: string) {
  if (!value) return null;
  const guess = new Date(value + "Z");
  const wall = new Date(
    guess
      .toLocaleString("sv-SE", { timeZone: "Europe/Warsaw" })
      .replace(" ", "T") + "Z",
  );
  return new Date(
    guess.getTime() - (wall.getTime() - guess.getTime()),
  ).toISOString();
}
const num = (value: FormDataEntryValue | null) =>
  String(value || "0").replace(",", ".");
const errorText = (e: unknown) =>
  e instanceof Error
    ? e.message === "Failed to fetch"
      ? "Brak połączenia. Zachowano formularz — spróbuj ponownie."
      : e.message
    : "Wystąpił błąd.";
function Badge({ status }: { status: string }) {
  return (
    <span className={"badge " + status}>
      <i />
      {names[status] || status}
    </span>
  );
}
function Progress({ value, total }: { value: number; total: number }) {
  return (
    <div className="progress">
      <span
        style={{
          width: Math.min(100, total ? (value / total) * 100 : 0) + "%",
        }}
      />
    </div>
  );
}
function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={wide ? "field wide" : "field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}
function Empty({
  title = "Tutaj jest jeszcze spokojnie",
  text = "Nowe zadania pojawią się po zatwierdzeniu zamówienia.",
}: {
  title?: string;
  text?: string;
}) {
  return (
    <div className="empty">
      <Package size={36} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
type ModalState = {
  kind: string;
  task?: Task;
  order?: Order;
  report?: Report;
  batch?: Batch;
  entity?: Product | Variant | Customer | User;
  catalog?: string;
};

export default function App() {
  const [user, setUser] = useState<User | null>(null),
    [boot, setBoot] = useState(true),
    [state, setState] = useState<State | null>(null);
  const [page, setPage] = useState("dashboard"),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [catalogTab, setCatalogTab] = useState("variants");
  const [modal, setModal] = useState<ModalState | null>(null),
    [selected, setSelected] = useState<number | null>(null),
    [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [offline, setOffline] = useState(false),
    [mobile, setMobile] = useState(false),
    [users, setUsers] = useState<User[]>([]);
  const [lines, setLines] = useState<
    { variant_id: number; quantity: number }[]
  >([{ variant_id: 0, quantity: 1 }]);
  const retryKeys = useRef(new Map<string, string>()),
    mutationLock = useRef(false);
  const can = (...r: string[]) =>
    Boolean(user?.roles.some((x) => r.includes(x)));
  const load = useCallback(async () => {
    try {
      const data = await api<State>("state/");
      setState(data);
      setUser(data.user);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);
  useEffect(() => {
    api<{ user: User | null }>("auth/me/")
      .then((r) => setUser(r.user))
      .catch((e) => setError(errorText(e)))
      .finally(() => setBoot(false));
  }, []);
  useEffect(() => {
    if (user) {
      load();
      const t = setInterval(load, 5000);
      return () => clearInterval(t);
    }
  }, [user?.id, load]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 4000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  useEffect(() => {
    if (selected !== null && user)
      api<Detail>(`orders/${selected}/`)
        .then(setDetail)
        .catch((e) => setError(errorText(e)));
    else setDetail(null);
  }, [selected, state]);
  useEffect(() => {
    if (page === "users" && user)
      api<User[]>("users/")
        .then(setUsers)
        .catch((e) => setError(errorText(e)));
  }, [page, state]);
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !mutationLock.current) {
        setModal(null);
        setSelected(null);
      }
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, []);
  const perform = async (path: string, data: unknown, close = true) => {
    if (mutationLock.current) return;
    mutationLock.current = true;
    setBusy(true);
    setError("");
    const fingerprint =
      path +
      JSON.stringify(
        data instanceof FormData
          ? [...data.entries()].map(([k, v]) => [
              k,
              v instanceof File ? `${v.name}:${v.size}:${v.lastModified}` : v,
            ])
          : data,
      );
    const key = retryKeys.current.get(fingerprint) || requestKey();
    retryKeys.current.set(fingerprint, key);
    try {
      const result = await api<{ id?: number }>(path, data, key);
      retryKeys.current.delete(fingerprint);
      if (close) setModal(null);
      setToast("Zapisano zmiany");
      await load();
      return result;
    } catch (e) {
      setError(errorText(e));
      return undefined;
    } finally {
      setBusy(false);
      mutationLock.current = false;
    }
  };
  function go(p: string) {
    setPage(p);
    setFilter("all");
    setQuery("");
    setSelected(null);
    setMobile(false);
  }
  function open(m: ModalState) {
    setError("");
    setModal(m);
    if (m.kind === "order")
      setLines(
        m.order?.items.map((i) => ({
          variant_id: i.variant_id,
          quantity: i.quantity,
        })) || [{ variant_id: 0, quantity: 1 }],
      );
  }
  async function loginSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const f = new FormData(e.currentTarget);
    try {
      await api("auth/me/");
      const r = await api<{ user: User }>("auth/login/", Object.fromEntries(f));
      setUser(r.user);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  async function logoutClick() {
    try {
      await api("auth/logout/", {});
      setUser(null);
      setState(null);
      setSelected(null);
      setModal(null);
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (boot)
    return (
      <div className="loading">
        <Popcorn />
        <p>Uruchamiamy POPMES…</p>
      </div>
    );
  if (!user)
    return (
      <div className="login">
        <div className="login-story">
          <div className="brand">
            <span className="brand-symbol">
              <Popcorn />
            </span>
            POP<span>MES</span>
          </div>
          <div>
            <div className="eyebrow">MAŁY ZAKŁAD. WIELKIE MOŻLIWOŚCI.</div>
            <h1>
              Od pierwszego
              <br />
              ziarna do
              <br />
              <em>gotowej paczki.</em>
            </h1>
            <p>
              Zamówienia, produkcja i pakowanie.
              <br />
              Cały zespół, jeden wspólny plan.
            </p>
            <div className="login-process">
              <span>
                <ClipboardList />
                Zamówienie
              </span>
              <ArrowRight />
              <span>
                <Factory />
                Produkcja
              </span>
              <ArrowRight />
              <span>
                <Package />
                Pakowanie
              </span>
            </div>
          </div>
          <small>POPME · Production Operations Platform</small>
        </div>
        <div className="login-form">
          <span className="mini-label">TWÓJ PANEL PRACY</span>
          <h2>Dobrze Cię widzieć.</h2>
          <p>Zaloguj się, żeby sprawdzić, co dziś robimy.</p>
          <form onSubmit={loginSubmit}>
            <Field label="Login">
              <input
                name="username"
                autoComplete="username"
                required
                autoFocus
              />
            </Field>
            <Field label="Hasło">
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                required
              />
            </Field>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            <button className="primary" disabled={busy}>
              Zaloguj się <ArrowRight size={18} />
            </button>
          </form>
          <div className="login-help">
            <ShieldCheck size={17} /> Konto i uprawnienia nadaje administrator.
          </div>
        </div>
      </div>
    );
  const nav = [
    { id: "dashboard", title: "Przegląd", icon: LayoutDashboard, show: true },
    {
      id: "orders",
      title: "Zamówienia",
      icon: ClipboardList,
      show: can("sales", "manager"),
    },
    {
      id: "production",
      title: "Produkcja",
      icon: Factory,
      show: can("production", "manager"),
    },
    {
      id: "packing",
      title: "Pakowanie",
      icon: Package,
      show: can("packing", "manager"),
    },
    {
      id: "stock",
      title: "Partie popcornu",
      icon: Warehouse,
      show: can("manager"),
    },
    {
      id: "catalog",
      title: "Katalog produktów",
      icon: Boxes,
      show: can("admin", "manager", "sales"),
    },
    {
      id: "customers",
      title: "Klienci",
      icon: Users,
      show: can("sales", "manager"),
    },
    { id: "users", title: "Zespół", icon: Settings2, show: can("admin") },
  ];
  const orders = state?.orders || [],
    tasks = state?.tasks || [];
  const active = orders.filter(
    (o) => !["draft", "issued", "cancelled", "completed"].includes(o.status),
  );
  const production = tasks.filter(
    (t) => t.kind === "production" && t.status !== "done",
  );
  const packing = tasks.filter(
    (t) => t.kind === "packing" && t.status !== "done",
  );
  const productionRemaining = can("sales", "manager")
    ? active.reduce(
        (sum, order) =>
          sum + order.deficits.reduce((g, d) => g + Number(d.planned_g), 0),
        0,
      )
    : production.reduce(
        (sum, task) =>
          sum + Math.max(0, Number(task.target_g) - Number(task.produced_g)),
        0,
      );
  const packingRemaining = can("sales", "manager")
    ? active.reduce((sum, order) => sum + order.units - order.packed, 0)
    : packing.reduce(
        (sum, task) => sum + task.item!.quantity - task.item!.packed,
        0,
      );
  const overdueCount = can("sales", "manager")
    ? orders.filter(late).length
    : new Set(
        tasks
          .filter(
            (task) =>
              task.status !== "done" &&
              task.due_at &&
              new Date(task.due_at) < new Date(),
          )
          .map((task) => task.order_id),
      ).size;
  const filteredOrders = orders.filter(
    (o) =>
      (filter === "all" ||
        o.status === filter ||
        (filter === "late" && late(o))) &&
      (
        o.number +
        " " +
        o.customer_name +
        " " +
        o.items.map((i) => i.name).join(" ")
      )
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const filteredTasks = tasks.filter(
    (t) =>
      t.kind === page &&
      (filter === "all"
        ? t.status !== "done"
        : filter === "blocked"
          ? t.blockers.length > 0
          : t.status === filter) &&
      (t.order_number + " " + t.product_name + " " + (t.customer_name || ""))
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const title = nav.find((n) => n.id === page)?.title || "Przegląd";
  const action = (path: string, data: unknown = {}) =>
    void perform(path, data, false);
  const orderTable = (list: Order[]) =>
    list.length ? (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Zamówienie / klient</th>
              <th>Produkty</th>
              <th>Termin gotowości</th>
              <th>Pakowanie</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((o) => (
              <tr
                key={o.id}
                onClick={() => setSelected(o.id)}
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && setSelected(o.id)}
              >
                <td>
                  <strong>{o.number}</strong>
                  <small>{o.customer_name}</small>
                </td>
                <td>
                  <div className="product-dots">
                    {[...new Set(o.items.map((i) => i.product_id))]
                      .slice(0, 4)
                      .map((id) => (
                        <span
                          key={id}
                          style={{
                            background: state?.products.find((p) => p.id === id)
                              ?.color,
                          }}
                        />
                      ))}
                    <span>{fmt.format(o.units)} szt.</span>
                  </div>
                  <small>{o.items.length} poz.</small>
                </td>
                <td className={late(o) ? "overdue" : ""}>
                  {dt(o.due_at)}
                  {o.priority === "urgent" && (
                    <small className="urgent">
                      <Zap size={11} /> Pilne
                    </small>
                  )}
                </td>
                <td className="progress-cell">
                  <div>
                    <b>{o.packed}</b> / {o.units}
                  </div>
                  <Progress value={o.packed} total={o.units} />
                </td>
                <td>
                  {o.hold_reason ? (
                    <span className="badge blocked">
                      <Pause size={11} />
                      Wstrzymane
                    </span>
                  ) : (
                    <Badge status={o.status} />
                  )}
                </td>
                <td>
                  <ChevronRight size={16} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ) : (
      <Empty
        title="Brak zamówień w tym widoku"
        text="Dodaj zamówienie albo zmień filtry wyszukiwania."
      />
    );
  return (
    <div className="app">
      <aside className={"sidebar " + (mobile ? "mobile-open" : "")}>
        <div className="brand">
          <span className="brand-symbol">
            <Popcorn />
          </span>
          POP<span>MES</span>
        </div>
        <div className="workspace">
          <span className="workspace-icon">P</span>
          <div>
            POPME<small>Przestrzeń produkcyjna</small>
          </div>
          <span className="online-dot" />
        </div>
        <div className="nav-label">MIEJSCE PRACY</div>
        <nav>
          {nav
            .filter((n) => n.show)
            .map((n) => (
              <button
                className={page === n.id ? "selected" : ""}
                key={n.id}
                onClick={() => go(n.id)}
              >
                <n.icon size={19} />
                {n.title}
                {n.id === "orders" && active.length > 0 && (
                  <b>{active.length}</b>
                )}
              </button>
            ))}
        </nav>
        <div className="sidebar-note">
          <Activity size={18} />
          <div>
            Dobry plan.
            <br />
            <strong>Dobra produkcja.</strong>
          </div>
        </div>
        <div className="user">
          <div className="avatar">{user.name.slice(0, 2).toUpperCase()}</div>
          <div>
            <strong>{user.name}</strong>
            <small>{user.roles.map((r) => roleNames[r]).join(", ")}</small>
          </div>
          <button title="Wyloguj" aria-label="Wyloguj" onClick={logoutClick}>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <button
            className="mobile-toggle"
            onClick={() => setMobile(!mobile)}
            aria-label="Otwórz menu"
          >
            <Menu />
          </button>
          <div className="breadcrumb">
            Przestrzeń POPME <ChevronRight size={13} /> <strong>{title}</strong>
          </div>
          <div className={"sync " + (offline ? "bad" : "")}>
            <span />
            {offline ? "Brak synchronizacji" : "Dane na bieżąco"}
          </div>
          <span className="top-date">
            {new Date().toLocaleDateString("pl-PL", {
              day: "numeric",
              month: "long",
              year: "numeric",
              timeZone: "Europe/Warsaw",
            })}
          </span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {page === "dashboard"
                  ? "WSZYSTKO NA SWOIM MIEJSCU"
                  : "POPME / OPERACJE"}
              </div>
              <h1>
                {page === "dashboard"
                  ? `Cześć, ${user.name.split(" ")[0]}.`
                  : title}
              </h1>
              <p>
                {page === "dashboard"
                  ? "Sprawdź plan, zadbaj o tempo i ruszamy z produkcją."
                  : page === "production"
                    ? "Każda zgłoszona porcja od razu trafia do pakowania."
                    : page === "packing"
                      ? "Właściwy smak, właściwa etykieta, gotowe zamówienie."
                      : page === "orders"
                        ? "Od przyjęcia zamówienia do ostatniej zapakowanej sztuki."
                        : page === "stock"
                          ? "Dostępny popcorn i pochodzenie każdej partii."
                          : "Wspólne dane, które porządkują codzienną pracę."}
              </p>
            </div>
            {can("sales", "manager") &&
              ["dashboard", "orders"].includes(page) && (
                <button
                  className="primary"
                  onClick={() => open({ kind: "order" })}
                >
                  <Plus size={17} /> Nowe zamówienie
                </button>
              )}
            {["catalog", "customers", "users"].includes(page) &&
              can(
                ...(page === "users"
                  ? ["admin"]
                  : page === "customers"
                    ? ["sales", "manager"]
                    : ["admin", "manager"]),
              ) && (
                <button
                  className="primary"
                  onClick={() =>
                    open({
                      kind: page === "users" ? "user" : "catalog",
                      catalog: page === "customers" ? "customers" : catalogTab,
                    })
                  }
                >
                  <Plus size={17} />
                  {page === "users"
                    ? "Dodaj osobę"
                    : page === "customers"
                      ? "Dodaj klienta"
                      : catalogTab === "variants"
                        ? "Dodaj wariant"
                        : "Dodaj smak"}
                </button>
              )}
          </div>
          {offline && (
            <div className="error" role="status">
              <CircleAlert size={18} /> Nie udało się pobrać aktualnych danych.
              Sprawdź połączenie; formularze pozostają dostępne do ponowienia.{" "}
              <button onClick={load}>
                <RefreshCw size={15} />
                Odśwież
              </button>
            </div>
          )}
          {error && !modal && (
            <div className="error" role="alert">
              {error}
              <button
                aria-label="Zamknij komunikat"
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {!state ? (
            <div className="loading-inline">Pobieramy dane…</div>
          ) : (
            <>
              {page === "dashboard" && (
                <>
                  <div className="metrics">
                    <Metric
                      label={
                        can("sales", "manager")
                          ? "Aktywne zamówienia"
                          : "Otwarte zadania"
                      }
                      value={
                        can("sales", "manager")
                          ? active.length
                          : tasks.filter((t) => t.status !== "done").length
                      }
                      sub="Wspólny plan zespołu"
                      icon={<ClipboardList />}
                    />
                    <Metric
                      label="Do wyprodukowania"
                      value={
                        can("sales", "manager", "production")
                          ? kg(productionRemaining)
                          : "—"
                      }
                      sub="Pozostała zaplanowana masa"
                      icon={<Factory />}
                    />
                    <Metric
                      label="Do zapakowania"
                      value={
                        can("sales", "manager", "packing")
                          ? fmt.format(packingRemaining)
                          : "—"
                      }
                      sub="sztuk do zakończenia"
                      icon={<Package />}
                    />
                    <Metric
                      label="Po terminie"
                      value={overdueCount}
                      sub="Wymagają Twojej uwagi"
                      icon={<Clock3 />}
                      alert={overdueCount > 0}
                    />
                  </div>
                  <div className="dashboard-grid">
                    <section className="panel orders-panel">
                      <div className="panel-head">
                        <div>
                          <h2>
                            {can("sales", "manager")
                              ? "Najbliższe zamówienia"
                              : "Twój plan pracy"}
                          </h2>
                          <p>Najpierw to, co najważniejsze.</p>
                        </div>
                        <button
                          className="text-button"
                          onClick={() =>
                            go(
                              can("sales", "manager")
                                ? "orders"
                                : can("production")
                                  ? "production"
                                  : "packing",
                            )
                          }
                        >
                          Zobacz wszystkie <ArrowRight size={15} />
                        </button>
                      </div>
                      {can("sales", "manager") ? (
                        orderTable(
                          [...active]
                            .sort((a, b) =>
                              (a.due_at || "").localeCompare(b.due_at || ""),
                            )
                            .slice(0, 6),
                        )
                      ) : (
                        <div className="worker-overview">
                          {tasks
                            .filter((t) => t.status !== "done")
                            .slice(0, 5)
                            .map((t) => (
                              <button key={t.id} onClick={() => go(t.kind)}>
                                <span
                                  className="flavor-icon"
                                  style={{
                                    background: t.color + "22",
                                    color: t.color,
                                  }}
                                >
                                  <Popcorn />
                                </span>
                                <div>
                                  <strong>{t.product_name}</strong>
                                  <small>
                                    {t.order_number} ·{" "}
                                    {t.kind === "production"
                                      ? kg(t.target_g)
                                      : `${t.item?.quantity} szt.`}
                                  </small>
                                </div>
                                <ChevronRight />
                              </button>
                            ))}
                          {!tasks.length && <Empty />}
                        </div>
                      )}
                    </section>
                    <aside className="day-plan">
                      <div className="eyebrow">PRZEPŁYW PRACY</div>
                      <h2>
                        Od zamówienia
                        <br />
                        do gotowej paczki.
                      </h2>
                      <p>
                        Jeden proces. Wspólna informacja dla całego zespołu.
                      </p>
                      <div className="flow-step">
                        <span>01</span>
                        <div>
                          <strong>Przyjmij zamówienie</strong>
                          <small>Produkty, ilości i termin</small>
                        </div>
                        <ClipboardList size={19} />
                      </div>
                      <div className="flow-step">
                        <span>02</span>
                        <div>
                          <strong>Wyprodukuj popcorn</strong>
                          <small>Raportuj gotowe kilogramy</small>
                        </div>
                        <Factory size={19} />
                      </div>
                      <div className="flow-step">
                        <span>03</span>
                        <div>
                          <strong>Zapakuj i wydaj</strong>
                          <small>Każda sztuka ma znaczenie</small>
                        </div>
                        <CheckCheck size={19} />
                      </div>
                      <div className="plan-foot">
                        <span className="online-dot" /> Automatyczne odświeżanie
                        co 5 s
                      </div>
                    </aside>
                  </div>
                  {(tasks.some(
                    (t) => t.blockers.length && t.status !== "done",
                  ) ||
                    orders.some((o) =>
                      o.deficits.some((d) => Number(d.shortage_g) > 0),
                    )) && (
                    <section className="panel attention">
                      <h2>
                        <CircleAlert size={19} /> Warto sprawdzić
                      </h2>
                      {tasks
                        .filter((t) => t.blockers.length && t.status !== "done")
                        .slice(0, 4)
                        .map((t) => (
                          <div key={t.id}>
                            <strong>
                              {t.order_number} · {t.product_name}
                            </strong>
                            <span>{t.blockers.join(" · ")}</span>
                          </div>
                        ))}
                      {orders
                        .filter((o) =>
                          o.deficits.some((d) => Number(d.shortage_g) > 0),
                        )
                        .map((o) => (
                          <button
                            className="text-button"
                            key={o.id}
                            onClick={() => setSelected(o.id)}
                          >
                            {o.number} — potrzebna produkcja uzupełniająca{" "}
                            <ArrowRight size={14} />
                          </button>
                        ))}
                    </section>
                  )}
                </>
              )}
              {page === "orders" && (
                <section className="panel">
                  <Toolbar
                    query={query}
                    setQuery={setQuery}
                    placeholder="Numer zamówienia, klient lub produkt…"
                  >
                    <select
                      aria-label="Status zamówienia"
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    >
                      <option value="all">Wszystkie statusy</option>
                      {[
                        "draft",
                        "queued",
                        "in_progress",
                        "completed",
                        "issued",
                        "cancelled",
                        "late",
                      ].map((k) => (
                        <option key={k} value={k}>
                          {names[k] || "Po terminie"}
                        </option>
                      ))}
                    </select>
                  </Toolbar>
                  {orderTable(filteredOrders)}
                </section>
              )}
              {["production", "packing"].includes(page) && (
                <>
                  <div className="queue-summary">
                    <span>
                      <i className="online-dot" /> {filteredTasks.length} zadań
                      w widoku
                    </span>
                    <span>Najpierw pilne, potem według terminu</span>
                  </div>
                  <section className="panel toolbar-panel">
                    <Toolbar
                      query={query}
                      setQuery={setQuery}
                      placeholder="Szukaj smaku lub numeru zamówienia…"
                    >
                      <select
                        aria-label="Filtr zadań"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        {[
                          ["all", "Otwarte zadania"],
                          ["ready", "Do wykonania"],
                          ["waiting", "Oczekujące"],
                          ["in_progress", "W trakcie"],
                          ["blocked", "Zablokowane"],
                          ["done", "Wykonane"],
                        ].map(([k, n]) => (
                          <option key={k} value={k}>
                            {n}
                          </option>
                        ))}
                      </select>
                    </Toolbar>
                  </section>
                  <div className="task-grid">
                    {filteredTasks.map((t) => (
                      <article className="task-card" key={t.id}>
                        <div className="task-top">
                          <span>{t.order_number}</span>
                          {t.priority === "urgent" ? (
                            <span className="urgent">
                              <Zap size={13} />
                              Pilne
                            </span>
                          ) : (
                            <span className="task-date">
                              <Clock3 size={12} />
                              {dt(t.due_at)}
                            </span>
                          )}
                        </div>
                        <div className="task-title">
                          <span
                            className="flavor-icon"
                            style={{
                              background: t.color + "22",
                              color: t.color,
                            }}
                          >
                            <Popcorn size={26} />
                          </span>
                          <div>
                            <h2>{t.product_name}</h2>
                            <p>
                              {t.kind === "production"
                                ? t.supplemental
                                  ? "Produkcja uzupełniająca"
                                  : "Produkcja popcornu"
                                : `${fmt.format(Number(t.item!.weight_g))} g · ${t.item!.packaging}`}
                            </p>
                          </div>
                        </div>
                        {t.customer_name && (
                          <div className="client-note">{t.customer_name}</div>
                        )}
                        <div className="task-count">
                          <strong>
                            {t.kind === "production"
                              ? kg(t.produced_g)
                              : fmt.format(t.item!.packed)}
                          </strong>
                          <span>
                            /{" "}
                            {t.kind === "production"
                              ? kg(t.target_g)
                              : `${fmt.format(t.item!.quantity)} szt.`}
                          </span>
                          <Badge status={t.status} />
                        </div>
                        <Progress
                          value={
                            t.kind === "production"
                              ? Number(t.produced_g)
                              : t.item!.packed
                          }
                          total={
                            t.kind === "production"
                              ? Number(t.target_g)
                              : t.item!.quantity
                          }
                        />
                        <div className="task-info">
                          <span>
                            {t.kind === "production"
                              ? "Do wykonania"
                              : "Dostępny popcorn"}
                          </span>
                          <strong>
                            {kg(
                              t.kind === "production"
                                ? Math.max(
                                    0,
                                    Number(t.target_g) - Number(t.produced_g),
                                  )
                                : t.available_g,
                            )}
                          </strong>
                        </div>
                        {(t.instruction || t.notes) && (
                          <p className="instruction">
                            {[t.instruction, t.notes]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        )}
                        {t.item?.label && (
                          <a className="file-link" href={t.item.label.url}>
                            <FileText size={15} /> Etykieta v
                            {t.item.label.version}
                            <span>
                              {t.item.label.approved
                                ? "Zatwierdzona"
                                : "Do zatwierdzenia"}
                            </span>
                            <ArrowDownToLine size={14} />
                          </a>
                        )}
                        {t.blockers.length > 0 && (
                          <div className="task-block">
                            <CircleAlert size={14} />
                            {t.blockers.join(" · ")}
                          </div>
                        )}
                        <div className="task-work">
                          <span>
                            <Clock3 size={12} />
                            {Math.floor(t.work_seconds / 60)} min pracy
                          </span>
                          <span>
                            {t.workers.join(", ") || "Brak aktywnego wykonawcy"}
                          </span>
                        </div>
                        {t.status !== "done" && (
                          <div className="task-actions">
                            <button
                              disabled={
                                busy || (!t.active && t.blockers.length > 0)
                              }
                              onClick={() =>
                                action(
                                  `tasks/${t.id}/${t.active ? "pause" : "start"}/`,
                                )
                              }
                            >
                              {t.active ? (
                                <Pause size={16} />
                              ) : (
                                <Play size={16} />
                              )}{" "}
                              {t.active ? "Pauza" : "Rozpocznij"}
                            </button>
                            <button
                              className="primary"
                              disabled={busy || t.blockers.length > 0}
                              onClick={() => open({ kind: "report", task: t })}
                            >
                              <Check size={16} />
                              {t.kind === "production"
                                ? "Zgłoś produkcję"
                                : "Zgłoś pakowanie"}
                            </button>
                          </div>
                        )}
                        <div className="task-links">
                          {t.status !== "done" && (
                            <button
                              className="text-button"
                              onClick={() =>
                                open({ kind: "task-hold", task: t })
                              }
                            >
                              Zgłoś problem
                            </button>
                          )}
                          {t.hold_reason && can("manager") && (
                            <button
                              className="text-button"
                              disabled={busy}
                              onClick={() => action(`tasks/${t.id}/resume/`)}
                            >
                              Usuń blokadę
                            </button>
                          )}
                          {t.kind === "production" && can("manager") && (
                            <button
                              className="text-button"
                              onClick={() => open({ kind: "target", task: t })}
                            >
                              Zmień cel
                            </button>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                  {!filteredTasks.length && (
                    <section className="panel">
                      <Empty
                        title="Kolejka jest pusta"
                        text="Zmień filtr lub zatwierdź nowe zamówienie."
                      />
                    </section>
                  )}
                </>
              )}
              {page === "catalog" && (
                <>
                  <div className="tabs">
                    <button
                      className={catalogTab === "variants" ? "active" : ""}
                      onClick={() => setCatalogTab("variants")}
                    >
                      Warianty sprzedażowe <b>{state.variants.length}</b>
                    </button>
                    <button
                      className={catalogTab === "products" ? "active" : ""}
                      onClick={() => setCatalogTab("products")}
                    >
                      Smaki / produkty <b>{state.products.length}</b>
                    </button>
                  </div>
                  <section className="panel">
                    <Toolbar
                      query={query}
                      setQuery={setQuery}
                      placeholder="Szukaj produktu…"
                    />
                    {catalogTab === "products" ? (
                      <div className="catalog-grid">
                        {state.products
                          .filter((p) =>
                            (p.name + p.code)
                              .toLowerCase()
                              .includes(query.toLowerCase()),
                          )
                          .map((p) => (
                            <button
                              className="product-card"
                              key={p.id}
                              disabled={!can("manager", "admin")}
                              onClick={() =>
                                open({
                                  kind: "catalog",
                                  catalog: "products",
                                  entity: p,
                                })
                              }
                            >
                              <span
                                className="flavor-icon"
                                style={{
                                  background: p.color + "22",
                                  color: p.color,
                                }}
                              >
                                <Popcorn size={28} />
                              </span>
                              <h3>{p.name}</h3>
                              <p>{p.code}</p>
                              <span
                                className={
                                  "badge " +
                                  (p.active ? "completed" : "cancelled")
                                }
                              >
                                {p.active ? "Aktywny" : "Archiwalny"}
                              </span>
                            </button>
                          ))}
                      </div>
                    ) : (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Produkt</th>
                              <th>SKU</th>
                              <th>Gramatura</th>
                              <th>Opakowanie</th>
                              <th>Etykieta</th>
                              <th />
                            </tr>
                          </thead>
                          <tbody>
                            {state.variants
                              .filter((v) =>
                                (v.name + v.sku)
                                  .toLowerCase()
                                  .includes(query.toLowerCase()),
                              )
                              .map((v) => (
                                <tr key={v.id}>
                                  <td>
                                    <strong>{v.name}</strong>
                                    {!v.active && <small>Archiwalny</small>}
                                  </td>
                                  <td>{v.sku}</td>
                                  <td>{fmt.format(Number(v.weight_g))} g</td>
                                  <td>{v.packaging}</td>
                                  <td>
                                    {v.custom_label
                                      ? "Personalizowana"
                                      : "Standardowa"}
                                  </td>
                                  <td>
                                    {can("admin", "manager") && (
                                      <button
                                        className="icon-button"
                                        aria-label={`Edytuj ${v.name}`}
                                        onClick={() =>
                                          open({
                                            kind: "catalog",
                                            catalog: "variants",
                                            entity: v,
                                          })
                                        }
                                      >
                                        <Pencil size={15} />
                                      </button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                </>
              )}
              {page === "customers" && (
                <section className="panel">
                  <Toolbar
                    query={query}
                    setQuery={setQuery}
                    placeholder="Szukaj klienta…"
                  />
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Klient</th>
                          <th>Kontakt</th>
                          <th>E-mail</th>
                          <th>Telefon</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {state.customers
                          .filter((c) =>
                            (c.name + c.email + c.phone)
                              .toLowerCase()
                              .includes(query.toLowerCase()),
                          )
                          .map((c) => (
                            <tr key={c.id}>
                              <td>
                                <strong>{c.name}</strong>
                                <small>
                                  {c.active ? c.tax_id : "Archiwalny"}
                                </small>
                              </td>
                              <td>{c.contact || "—"}</td>
                              <td>{c.email || "—"}</td>
                              <td>{c.phone || "—"}</td>
                              <td>
                                <button
                                  className="icon-button"
                                  aria-label={`Edytuj ${c.name}`}
                                  onClick={() =>
                                    open({
                                      kind: "catalog",
                                      catalog: "customers",
                                      entity: c,
                                    })
                                  }
                                >
                                  <Pencil size={15} />
                                </button>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  {!state.customers.length && (
                    <Empty
                      title="Dodaj pierwszego klienta"
                      text="Dane będą dostępne podczas przyjmowania zamówień."
                    />
                  )}
                </section>
              )}
              {page === "users" && (
                <section className="panel">
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Osoba</th>
                          <th>Login</th>
                          <th>Role</th>
                          <th>Status</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {users.map((u) => (
                          <tr key={u.id}>
                            <td>
                              <strong>{u.name}</strong>
                            </td>
                            <td>{u.username}</td>
                            <td>
                              {u.roles.map((r) => roleNames[r]).join(", ")}
                            </td>
                            <td>{u.active ? "Aktywne konto" : "Nieaktywne"}</td>
                            <td>
                              <button
                                className="icon-button"
                                aria-label={`Edytuj ${u.name}`}
                                onClick={() =>
                                  open({ kind: "user", entity: u })
                                }
                              >
                                <Pencil size={15} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
              {page === "stock" && (
                <section className="panel">
                  <Toolbar
                    query={query}
                    setQuery={setQuery}
                    placeholder="Szukaj partii lub smaku…"
                  />
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Partia</th>
                          <th>Smak</th>
                          <th>Zamówienie</th>
                          <th>Dostępna masa</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {state.batches
                          .filter((b) =>
                            (b.number + b.product_name)
                              .toLowerCase()
                              .includes(query.toLowerCase()),
                          )
                          .map((b) => (
                            <tr key={b.id}>
                              <td>
                                <strong>{b.number}</strong>
                                <small>{dt(b.created_at)}</small>
                              </td>
                              <td>{b.product_name}</td>
                              <td>
                                {
                                  orders.find((o) => o.id === b.order_id)
                                    ?.number
                                }
                                <small>
                                  {[
                                    "completed",
                                    "cancelled",
                                    "issued",
                                  ].includes(
                                    orders.find((o) => o.id === b.order_id)
                                      ?.status || "",
                                  )
                                    ? "Nadwyżka · do decyzji"
                                    : "Przypisana do zamówienia"}
                                </small>
                              </td>
                              <td>
                                <strong>{kg(b.available_g)}</strong>
                              </td>
                              <td>
                                <button
                                  onClick={() =>
                                    open({ kind: "stock", batch: b })
                                  }
                                >
                                  Rozlicz <ArrowRight size={14} />
                                </button>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  {!state.batches.length && (
                    <Empty
                      title="Brak dostępnego popcornu"
                      text="Partie pojawią się po zgłoszeniu produkcji."
                    />
                  )}
                </section>
              )}
            </>
          )}
          <footer>
            POPMES <span>Produkcja pod kontrolą.</span>
            <span>Wersja 0.1</span>
          </footer>
        </div>
      </main>
      {toast && (
        <div className="toast" role="status">
          <CheckCheck size={19} />
          {toast}
        </div>
      )}
      {selected !== null && detail && (
        <div className="drawer-backdrop" onClick={() => setSelected(null)}>
          <section
            className="drawer"
            onClick={(e) => e.stopPropagation()}
            aria-label="Szczegóły zamówienia"
          >
            <div className="drawer-head">
              <div className="eyebrow">SZCZEGÓŁY ZAMÓWIENIA</div>
              <button
                className="icon-button"
                aria-label="Zamknij szczegóły"
                onClick={() => setSelected(null)}
              >
                <X />
              </button>
            </div>
            <h2>{detail.number}</h2>
            <div className="drawer-customer">
              {detail.customer_name}
              <Badge status={detail.status} />
            </div>
            <div className="detail-meta">
              <div>
                <small>Termin gotowości</small>
                <strong>{dt(detail.due_at)}</strong>
              </div>
              <div>
                <small>Odbiór</small>
                <strong>
                  {
                    { pickup: "Osobisty", courier: "Kurier", other: "Inny" }[
                      detail.delivery
                    ]
                  }
                </strong>
              </div>
              <div>
                <small>Priorytet</small>
                <strong>
                  {detail.priority === "urgent" ? "Pilne" : "Standardowy"}
                </strong>
              </div>
            </div>
            {detail.address && <p className="instruction">{detail.address}</p>}
            {detail.hold_reason && (
              <div className="error">Wstrzymane: {detail.hold_reason}</div>
            )}
            <div className="detail-actions">
              {detail.status === "draft" && (
                <>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => action(`orders/${detail.id}/confirm/`)}
                  >
                    <Check />
                    Zatwierdź
                  </button>
                  <button
                    onClick={() => open({ kind: "order", order: detail })}
                  >
                    <Pencil size={15} />
                    Edytuj szkic
                  </button>
                  <button
                    onClick={() => open({ kind: "delete", order: detail })}
                  >
                    Usuń szkic
                  </button>
                </>
              )}
              {!["draft", "cancelled", "issued"].includes(detail.status) && (
                <button onClick={() => open({ kind: "amend", order: detail })}>
                  <Pencil size={15} />
                  Zmień zamówienie
                </button>
              )}
              {detail.status === "completed" && (
                <button
                  className="primary"
                  disabled={busy || !!detail.hold_reason}
                  onClick={() => action(`orders/${detail.id}/issue/`)}
                >
                  Oznacz jako wydane
                </button>
              )}
              {can("manager") &&
                !["cancelled", "issued"].includes(detail.status) && (
                  <>
                    <button
                      onClick={() =>
                        detail.hold_reason
                          ? action(`orders/${detail.id}/resume/`)
                          : open({ kind: "hold", order: detail })
                      }
                    >
                      {detail.hold_reason ? "Wznów" : "Wstrzymaj"}
                    </button>
                    <button
                      className="danger-outline"
                      onClick={() => open({ kind: "cancel", order: detail })}
                    >
                      Anuluj
                    </button>
                  </>
                )}
              {can("manager") && detail.status === "issued" && (
                <button
                  onClick={() => open({ kind: "unissue", order: detail })}
                >
                  Cofnij wydanie
                </button>
              )}
            </div>
            {detail.deficits.some((d) => Number(d.shortage_g) > 0) && (
              <div className="shortage">
                <CircleAlert size={18} />
                <div>
                  <strong>Brakuje popcornu do zakończenia</strong>
                  <p>
                    Po uwzględnieniu zapasu i zaplanowanej produkcji:{" "}
                    {kg(
                      detail.deficits.reduce(
                        (a, d) => a + Number(d.shortage_g),
                        0,
                      ),
                    )}
                    .
                  </p>
                  {can("manager") && (
                    <button
                      disabled={busy}
                      onClick={() => action(`orders/${detail.id}/replenish/`)}
                    >
                      Dodaj produkcję uzupełniającą
                    </button>
                  )}
                </div>
              </div>
            )}
            <h3>Pozycje zamówienia</h3>
            {detail.items.map((i) => (
              <div className="detail-item" key={i.id}>
                <div className="detail-item-top">
                  <div>
                    <strong>{i.name}</strong>
                    <small>
                      {fmt.format(Number(i.weight_g))} g · {i.packaging}
                    </small>
                  </div>
                  <strong>
                    {i.packed} / {i.quantity} szt.
                  </strong>
                </div>
                <Progress value={i.packed} total={i.quantity} />
                <div className="label-row">
                  <span>
                    <FileText size={14} />
                    {i.label
                      ? `Etykieta v${i.label.version} · ${i.label.approved ? "zatwierdzona" : "do zatwierdzenia"}`
                      : i.custom_label
                        ? "Brak wymaganej etykiety"
                        : "Etykieta standardowa"}
                  </span>
                  {i.label && (
                    <a href={i.label.url} className="text-button">
                      Pobierz
                    </a>
                  )}
                  {i.label &&
                    !i.label.approved &&
                    !["cancelled", "issued"].includes(detail.status) && (
                      <button
                        disabled={busy}
                        onClick={() => action(`labels/${i.label!.id}/approve/`)}
                      >
                        Zatwierdź
                      </button>
                    )}
                </div>
                {!["cancelled", "issued"].includes(detail.status) && (
                  <label className="upload-button">
                    <Upload size={14} /> Dodaj{" "}
                    {i.label ? "nową wersję" : "etykietę"}
                    <input
                      type="file"
                      accept=".pdf,.png,.jpg,.jpeg"
                      disabled={busy}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) {
                          const f = new FormData();
                          f.append("file", file);
                          action(`items/${i.id}/labels/`, f);
                        }
                        e.target.value = "";
                      }}
                    />
                  </label>
                )}
                {i.labels.length > 1 && (
                  <details>
                    <summary>Poprzednie wersje</summary>
                    {i.labels.slice(1).map((l) => (
                      <a className="file-link" key={l.id} href={l.url}>
                        v{l.version} · {l.filename}
                      </a>
                    ))}
                  </details>
                )}
              </div>
            ))}
            {[
              ["Dla produkcji", detail.production_notes],
              ["Dla pakowania", detail.packing_notes],
              ["Uwagi wewnętrzne", detail.internal_notes],
            ]
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div className="note-block" key={k}>
                  <small>{k}</small>
                  <p>{v}</p>
                </div>
              ))}
            <h3>Raporty wykonania</h3>
            {detail.reports.length ? (
              detail.reports.map((r) => (
                <div
                  className={"report-row " + (r.corrected ? "corrected" : "")}
                  key={r.id}
                >
                  <div>
                    <strong>
                      {r.kind === "production" ? "Produkcja" : "Pakowanie"} ·{" "}
                      {r.product_name}
                    </strong>
                    <p>
                      {r.kind === "production"
                        ? kg(r.grams)
                        : `${r.units} szt. · ${kg(r.grams)} zużycia`}
                      {r.corrected ? " · SKORYGOWANO" : ""}
                    </p>
                    <small>
                      {r.user} · {dt(r.created_at)}
                      {r.batch ? ` · ${r.batch}` : ""}
                    </small>
                    {r.allocations.map((a, index) => (
                      <small key={index}>
                        {a.batch}: {kg(a.grams)}
                      </small>
                    ))}
                    {r.label && (
                      <a className="text-button" href={r.label.url}>
                        Etykieta v{r.label.version}
                      </a>
                    )}
                    {r.note && <small>{r.note}</small>}
                  </div>
                  {can("manager") &&
                    !r.corrected &&
                    !["issued", "cancelled"].includes(detail.status) && (
                      <button
                        onClick={() => open({ kind: "correction", report: r })}
                      >
                        Korekta
                      </button>
                    )}
                </div>
              ))
            ) : (
              <p className="muted">
                Wykonanie pojawi się po pierwszym raporcie.
              </p>
            )}
            <h3>
              <History size={17} /> Historia zamówienia
            </h3>
            <div className="timeline">
              {detail.events.map((e) => (
                <div key={e.id}>
                  <i />
                  <strong>{e.action}</strong>
                  <small>
                    {e.user} · {dt(e.created_at)}
                  </small>
                  {Object.keys(e.detail).length > 0 && (
                    <details>
                      <summary>Szczegóły</summary>
                      <pre>{JSON.stringify(e.detail, null, 2)}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
      {modal && state && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
          >
            <div className="modal-head">
              <div>
                <div className="eyebrow">
                  POPMES /{" "}
                  {modal.kind === "report"
                    ? "RAPORT WYKONANIA"
                    : "EDYCJA DANYCH"}
                </div>
                <h2 id="modal-title">{modalTitle(modal)}</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Zamknij formularz"
                disabled={busy}
                onClick={() => setModal(null)}
              >
                <X />
              </button>
            </div>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                const d = Object.fromEntries(f);
                let path = "",
                  data: unknown = d;
                if (modal.kind === "order") {
                  path = "orders/save/";
                  data = {
                    ...d,
                    id: modal.order?.id,
                    version: modal.order?.version,
                    customer_id: d.customer_id ? Number(d.customer_id) : null,
                    due_at: fromWarsaw(String(d.due_at || "")),
                    items: lines.filter((l) => l.variant_id),
                    confirm:
                      (e.nativeEvent as SubmitEvent).submitter?.getAttribute(
                        "value",
                      ) === "confirm",
                  };
                } else if (modal.kind === "report") {
                  const t = modal.task!;
                  path = `tasks/${t.id}/report/`;
                  data =
                    t.kind === "production"
                      ? {
                          grams: String(Number(num(f.get("kg"))) * 1000),
                          waste_g: String(
                            Number(num(f.get("waste_kg"))) * 1000,
                          ),
                          batch_id: d.batch_id ? Number(d.batch_id) : null,
                          note: d.note,
                        }
                      : {
                          units: Number(d.units),
                          grams: d.kg
                            ? String(Number(num(f.get("kg"))) * 1000)
                            : null,
                          waste_g: String(
                            Number(num(f.get("waste_kg"))) * 1000,
                          ),
                          note: d.note,
                          ...(d.batch_id
                            ? {
                                allocations: [
                                  {
                                    batch_id: Number(d.batch_id),
                                    grams: d.kg
                                      ? String(Number(num(f.get("kg"))) * 1000)
                                      : String(
                                          Number(d.units) *
                                            Number(t.item!.weight_g),
                                        ),
                                  },
                                ],
                              }
                            : {}),
                        };
                } else if (modal.kind === "catalog") {
                  path = `catalog/${modal.catalog}/`;
                  data = {
                    ...d,
                    ...(modal.entity ? { id: modal.entity.id } : {}),
                    active: f.has("active"),
                    ...(modal.catalog === "variants"
                      ? {
                          weight_g: num(f.get("weight_g")),
                          product: Number(d.product),
                          custom_label: f.has("custom_label"),
                        }
                      : {}),
                  };
                } else if (modal.kind === "user") {
                  path = "users/";
                  data = {
                    ...d,
                    id: modal.entity?.id,
                    active: f.has("active"),
                    roles: f.getAll("roles"),
                  };
                } else if (modal.kind === "correction") {
                  path = `reports/${modal.report!.id}/correct/`;
                  data = {
                    reason: d.reason,
                    restore_mass: f.has("restore_mass"),
                  };
                } else if (modal.kind === "stock") {
                  path = `batches/${modal.batch!.id}/move/`;
                  data = {
                    reason: d.reason,
                    order_id: d.order_id ? Number(d.order_id) : null,
                    grams: String(Number(num(f.get("kg"))) * 1000),
                  };
                } else if (modal.kind === "amend") {
                  path = `orders/${modal.order!.id}/amend/`;
                  data = {
                    ...d,
                    version: modal.order!.version,
                    due_at: fromWarsaw(String(d.due_at)),
                    items: modal.order!.items.map((i) => ({
                      id: i.id,
                      quantity: Number(d["qty_" + i.id]),
                    })),
                  };
                } else if (modal.kind === "target") {
                  path = `tasks/${modal.task!.id}/target/`;
                  data = {
                    reason: d.reason,
                    target_g: String(Number(num(f.get("kg"))) * 1000),
                  };
                } else if (modal.kind === "task-hold") {
                  path = `tasks/${modal.task!.id}/hold/`;
                } else {
                  path = `orders/${modal.order!.id}/${modal.kind}/`;
                }
                const result = await perform(path, data);
                if (result && modal.kind === "order" && result.id) {
                  setSelected(result.id);
                  setPage("orders");
                }
                if (result && modal.kind === "delete") setSelected(null);
              }}
            >
              {modal.kind === "order" && (
                <>
                  <div className="form-grid">
                    <Field label="Klient">
                      <select
                        name="customer_id"
                        defaultValue={modal.order?.customer_id || ""}
                      >
                        <option value="">Wybierz klienta</option>
                        {state.customers
                          .filter((c) => c.active)
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                      </select>
                    </Field>
                    <Field label="Termin gotowości (czas Warszawy)">
                      <input
                        name="due_at"
                        type="datetime-local"
                        defaultValue={localDate(modal.order?.due_at || null)}
                      />
                    </Field>
                    <Field label="Priorytet">
                      <select
                        name="priority"
                        defaultValue={modal.order?.priority || "normal"}
                      >
                        <option value="normal">Standardowy</option>
                        <option value="urgent">Pilny</option>
                      </select>
                    </Field>
                    <Field label="Sposób odbioru">
                      <select
                        name="delivery"
                        defaultValue={modal.order?.delivery || "pickup"}
                      >
                        <option value="pickup">Odbiór osobisty</option>
                        <option value="courier">Kurier</option>
                        <option value="other">Inny</option>
                      </select>
                    </Field>
                    <Field label="Adres dostawy (wymagany dla kuriera)" wide>
                      <input
                        name="address"
                        defaultValue={modal.order?.address || ""}
                      />
                    </Field>
                  </div>
                  <div className="form-section-head">
                    <h3>Co produkujemy?</h3>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() =>
                        setLines([...lines, { variant_id: 0, quantity: 1 }])
                      }
                    >
                      <Plus size={14} />
                      Dodaj pozycję
                    </button>
                  </div>
                  {lines.map((l, index) => (
                    <div className="order-line" key={index}>
                      <select
                        aria-label={`Produkt ${index + 1}`}
                        value={l.variant_id}
                        onChange={(e) =>
                          setLines(
                            lines.map((x, i) =>
                              i === index
                                ? { ...x, variant_id: Number(e.target.value) }
                                : x,
                            ),
                          )
                        }
                      >
                        <option value="0">Wybierz produkt</option>
                        {state.variants
                          .filter((v) => v.active)
                          .map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.name} · {fmt.format(Number(v.weight_g))} g{" "}
                              {v.custom_label ? "· z logo" : ""}
                            </option>
                          ))}
                      </select>
                      <input
                        aria-label={`Ilość ${index + 1}`}
                        type="number"
                        min="1"
                        max="10000000"
                        step="1"
                        value={l.quantity}
                        onChange={(e) =>
                          setLines(
                            lines.map((x, i) =>
                              i === index
                                ? { ...x, quantity: Number(e.target.value) }
                                : x,
                            ),
                          )
                        }
                      />
                      <span>szt.</span>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label="Usuń pozycję"
                        onClick={() =>
                          setLines(lines.filter((_, i) => i !== index))
                        }
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ))}
                  <div className="order-total">
                    <span>Łączne zapotrzebowanie netto</span>
                    <strong>
                      {kg(
                        lines.reduce(
                          (a, l) =>
                            a +
                            Number(
                              state.variants.find((v) => v.id === l.variant_id)
                                ?.weight_g || 0,
                            ) *
                              l.quantity,
                          0,
                        ),
                      )}
                    </strong>
                  </div>
                  <div className="form-grid">
                    <Field label="Uwagi dla produkcji">
                      <textarea
                        name="production_notes"
                        defaultValue={modal.order?.production_notes}
                      />
                    </Field>
                    <Field label="Uwagi dla pakowania">
                      <textarea
                        name="packing_notes"
                        defaultValue={modal.order?.packing_notes}
                      />
                    </Field>
                    <Field label="Uwagi wewnętrzne" wide>
                      <textarea
                        name="internal_notes"
                        defaultValue={modal.order?.internal_notes}
                      />
                    </Field>
                  </div>
                  <p className="form-help">
                    Etykiety dodasz w szczegółach zapisanego zamówienia.
                    Personalizowane pakowanie poczeka na ich zatwierdzenie.
                  </p>
                </>
              )}
              {modal.kind === "report" && (
                <>
                  <div className="form-callout">
                    <Popcorn size={24} />
                    <div>
                      <strong>{modal.task!.product_name}</strong>
                      <span>
                        {modal.task!.order_number} · raportujesz nową, dodatkową
                        ilość
                      </span>
                    </div>
                  </div>
                  <div className="form-grid">
                    {modal.task!.kind === "production" ? (
                      <>
                        <Field label="Gotowy popcorn (kg)">
                          <input
                            name="kg"
                            type="number"
                            min="0.001"
                            step="0.001"
                            required
                            autoFocus
                          />
                        </Field>
                        <Field label="Partia">
                          <select name="batch_id">
                            <option value="">Utwórz nową partię</option>
                            {modal
                              .task!.batches.filter(
                                (b) => b.origin_task_id === modal.task!.id,
                              )
                              .map((b) => (
                                <option key={b.id} value={b.id}>
                                  {b.number}
                                </option>
                              ))}
                          </select>
                        </Field>
                      </>
                    ) : (
                      <>
                        <Field label="Dodatkowe zapakowane sztuki">
                          <input
                            name="units"
                            type="number"
                            min="1"
                            step="1"
                            max={
                              modal.task!.item!.quantity -
                              modal.task!.item!.packed
                            }
                            required
                            autoFocus
                          />
                        </Field>
                        <Field label="Łączne zużycie popcornu (kg, opcjonalnie)">
                          <input
                            name="kg"
                            type="number"
                            min="0.001"
                            step="0.001"
                            placeholder="Puste = sztuki × gramatura"
                          />
                        </Field>
                        <Field label="Pobranie partii" wide>
                          <select name="batch_id">
                            <option value="">
                              Automatycznie: najstarsze dostępne partie (FIFO)
                            </option>
                            {modal
                              .task!.batches.filter(
                                (b) => Number(b.available_g) > 0,
                              )
                              .map((b) => (
                                <option key={b.id} value={b.id}>
                                  {b.number} · {kg(b.available_g)}
                                </option>
                              ))}
                          </select>
                        </Field>
                      </>
                    )}
                    <Field
                      label={
                        modal.task!.kind === "production"
                          ? "Odpad produkcyjny (kg)"
                          : "Straty wliczone w zużycie (kg)"
                      }
                    >
                      <input
                        name="waste_kg"
                        type="number"
                        min="0"
                        step="0.001"
                        defaultValue="0"
                      />
                    </Field>
                    <Field label="Komentarz" wide>
                      <textarea
                        name="note"
                        placeholder="Opcjonalne uwagi do wykonania"
                      />
                    </Field>
                  </div>
                  <p className="form-help">
                    {modal.task!.kind === "production"
                      ? "Zgłoś produkt gotowy do pakowania, po zakończeniu suszenia i studzenia."
                      : "Dostępne " +
                        kg(modal.task!.available_g) +
                        ". Przy stratach lub naddatku wpisz całkowite zużycie."}
                  </p>
                </>
              )}
              {modal.kind === "catalog" && (
                <CatalogForm
                  kind={modal.catalog!}
                  entity={modal.entity}
                  state={state}
                />
              )}
              {modal.kind === "user" && (
                <>
                  <div className="form-grid">
                    <Field label="Imię / nazwa">
                      <input
                        name="name"
                        required
                        defaultValue={(modal.entity as User)?.name}
                      />
                    </Field>
                    <Field label="Login">
                      <input
                        name="username"
                        required
                        defaultValue={(modal.entity as User)?.username}
                        autoComplete="off"
                      />
                    </Field>
                    <Field
                      label={
                        modal.entity
                          ? "Nowe hasło (puste = bez zmiany)"
                          : "Hasło (minimum 10 znaków)"
                      }
                      wide
                    >
                      <input
                        name="password"
                        type="password"
                        minLength={10}
                        required={!modal.entity}
                        autoComplete="new-password"
                      />
                    </Field>
                  </div>
                  <h3>Role użytkownika</h3>
                  <div className="role-checkboxes">
                    {Object.entries(roleNames).map(([k, v]) => (
                      <label key={k}>
                        <input
                          type="checkbox"
                          name="roles"
                          value={k}
                          defaultChecked={(
                            modal.entity as User
                          )?.roles.includes(k)}
                        />
                        {v}
                      </label>
                    ))}
                  </div>
                  <label className="check-field">
                    <input
                      type="checkbox"
                      name="active"
                      defaultChecked={
                        modal.entity ? (modal.entity as User).active : true
                      }
                    />
                    Konto aktywne
                  </label>
                </>
              )}
              {modal.kind === "amend" && (
                <>
                  <p className="form-help">
                    Zmiany zachowują już wykonaną produkcję oraz historię
                    etykiet. Po rozpoczęciu pracy potrzebna jest rola
                    kierownika.
                  </p>
                  <div className="form-grid">
                    <Field label="Termin gotowości (czas Warszawy)">
                      <input
                        name="due_at"
                        type="datetime-local"
                        required
                        defaultValue={localDate(modal.order!.due_at)}
                      />
                    </Field>
                    <Field label="Priorytet">
                      <select
                        name="priority"
                        defaultValue={modal.order!.priority}
                      >
                        <option value="normal">Standardowy</option>
                        <option value="urgent">Pilny</option>
                      </select>
                    </Field>
                    {modal.order!.items.map((i) => (
                      <Field
                        key={i.id}
                        label={`${i.name} (zapakowano ${i.packed})`}
                      >
                        <input
                          type="number"
                          min={Math.max(1, i.packed)}
                          step="1"
                          name={"qty_" + i.id}
                          defaultValue={i.quantity}
                          required
                        />
                      </Field>
                    ))}
                    <Field label="Uwagi produkcyjne">
                      <textarea
                        name="production_notes"
                        defaultValue={modal.order!.production_notes}
                      />
                    </Field>
                    <Field label="Uwagi pakowania">
                      <textarea
                        name="packing_notes"
                        defaultValue={modal.order!.packing_notes}
                      />
                    </Field>
                  </div>
                  <Field label="Powód zmiany">
                    <textarea name="reason" required />
                  </Field>
                </>
              )}
              {modal.kind === "correction" && (
                <>
                  <p className="form-help">
                    Cofnięcie całego raportu #{modal.report!.id}:{" "}
                    {modal.report!.kind === "production"
                      ? kg(modal.report!.grams)
                      : modal.report!.units + " szt."}
                    . Oryginał pozostanie w historii. Następnie możesz zgłosić
                    poprawną ilość.
                  </p>
                  {modal.report!.kind === "packing" && (
                    <label className="check-field">
                      <input type="checkbox" name="restore_mass" />
                      Przywróć zużytą masę — wyłącznie jeśli pakowanie nie
                      nastąpiło, a popcorn fizycznie pozostał w partii.
                    </label>
                  )}
                  <Field label="Przyczyna korekty">
                    <textarea name="reason" required />
                  </Field>
                </>
              )}
              {modal.kind === "stock" && (
                <>
                  <p className="form-help">
                    {modal.batch!.number} · dostępne{" "}
                    {kg(modal.batch!.available_g)}. Transfer przenosi całą
                    dostępną pozostałość partii z zachowaniem pochodzenia.
                  </p>
                  <Field label="Przenieś do zamówienia albo rozlicz rozchód">
                    <select name="order_id">
                      <option value="">Rozchód / odpad</option>
                      {orders
                        .filter(
                          (o) =>
                            o.id !== modal.batch!.order_id &&
                            ![
                              "draft",
                              "cancelled",
                              "issued",
                              "completed",
                            ].includes(o.status) &&
                            o.items.some(
                              (i) => i.product_id === modal.batch!.product_id,
                            ),
                        )
                        .map((o) => (
                          <option value={o.id} key={o.id}>
                            {o.number} · {o.customer_name}
                          </option>
                        ))}
                    </select>
                  </Field>
                  <Field label="Masa rozchodu (kg) — tylko przy rozchodzie">
                    <input
                      name="kg"
                      type="number"
                      min="0.001"
                      step="0.001"
                      max={Number(modal.batch!.available_g) / 1000}
                    />
                  </Field>
                  <Field label="Powód">
                    <textarea name="reason" required />
                  </Field>
                </>
              )}
              {modal.kind === "target" && (
                <>
                  <Field label="Nowy całkowity cel produkcji (kg)">
                    <input
                      name="kg"
                      type="number"
                      min={Number(modal.task!.produced_g) / 1000}
                      step="0.001"
                      defaultValue={Number(modal.task!.target_g) / 1000}
                      required
                    />
                  </Field>
                  <Field label="Powód zmiany">
                    <textarea name="reason" required />
                  </Field>
                </>
              )}
              {["hold", "task-hold", "cancel", "unissue"].includes(
                modal.kind,
              ) && (
                <>
                  <p className="form-help">
                    {modal.kind === "cancel"
                      ? "Wykonana produkcja i raporty pozostaną w historii. Pozostała praca zostanie zatrzymana."
                      : "Czynność zostanie zapisana w historii wraz z Twoim kontem."}
                  </p>
                  <Field label="Przyczyna">
                    <textarea name="reason" required autoFocus />
                  </Field>
                </>
              )}
              {modal.kind === "delete" && (
                <p>Usunąć szkic {modal.order!.number}?</p>
              )}
              {error && (
                <div className="error" role="alert">
                  {error}
                </div>
              )}
              <div className="modal-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setModal(null)}
                >
                  Wróć
                </button>
                {modal.kind === "order" && (
                  <button type="submit" value="draft" disabled={busy}>
                    Zapisz szkic
                  </button>
                )}
                <button
                  type="submit"
                  value="confirm"
                  className="primary"
                  disabled={busy}
                >
                  {busy
                    ? "Zapisywanie…"
                    : modal.kind === "order"
                      ? "Zatwierdź do realizacji"
                      : modal.kind === "report"
                        ? "Zapisz wykonanie"
                        : "Zapisz zmiany"}
                  <Check size={16} />
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
function Metric({
  label,
  value,
  sub,
  icon,
  alert = false,
}: {
  label: string;
  value: string | number;
  sub: string;
  icon: ReactNode;
  alert?: boolean;
}) {
  return (
    <div className={"metric " + (alert ? "alert" : "")}>
      <div>
        <span>{label}</span>
        {icon}
      </div>
      <strong>{value}</strong>
      <p>{sub}</p>
    </div>
  );
}
function Toolbar({
  query,
  setQuery,
  placeholder,
  children,
}: {
  query: string;
  setQuery: (q: string) => void;
  placeholder: string;
  children?: ReactNode;
}) {
  return (
    <div className="toolbar">
      <label className="search">
        <Search size={17} />
        <input
          aria-label="Wyszukaj"
          placeholder={placeholder}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {children}
    </div>
  );
}
function modalTitle(m: ModalState) {
  return (
    (
      {
        order: m.order ? "Edytuj szkic" : "Nowe zamówienie",
        report:
          m.task?.kind === "production"
            ? "Zgłoś gotowy popcorn"
            : "Zgłoś zapakowane sztuki",
        catalog: m.entity
          ? "Edytuj dane"
          : m.catalog === "customers"
            ? "Nowy klient"
            : m.catalog === "products"
              ? "Nowy smak"
              : "Nowy wariant",
        user: m.entity ? "Edytuj użytkownika" : "Dodaj osobę do zespołu",
        amend: "Zmień zamówienie",
        correction: "Korekta wykonania",
        stock: "Rozlicz partię",
        target: "Zmień cel produkcji",
        hold: "Wstrzymaj zamówienie",
        "task-hold": "Zgłoś problem",
        cancel: "Anuluj zamówienie",
        unissue: "Cofnij wydanie",
        delete: "Usuń szkic",
      } as Record<string, string>
    )[m.kind] || "Zapisz zmiany"
  );
}
function CatalogForm({
  kind,
  entity,
  state,
}: {
  kind: string;
  entity?: Product | Variant | Customer | User;
  state: State;
}) {
  const p = entity as Product | undefined,
    v = entity as Variant | undefined,
    c = entity as Customer | undefined;
  return (
    <>
      <div className="form-grid">
        <Field label="Nazwa" wide>
          <input name="name" required defaultValue={entity?.name} />
        </Field>
        {kind === "products" && (
          <>
            <Field label="Kod smaku">
              <input name="code" required defaultValue={p?.code} />
            </Field>
            <Field label="Kolor oznaczenia">
              <input
                type="color"
                name="color"
                defaultValue={p?.color || "#d49743"}
              />
            </Field>
            <Field label="Instrukcja produkcji" wide>
              <textarea name="instruction" defaultValue={p?.instruction} />
            </Field>
          </>
        )}
        {kind === "variants" && (
          <>
            <Field label="SKU">
              <input name="sku" required defaultValue={v?.sku} />
            </Field>
            <Field label="Smak / produkt produkcyjny">
              <select name="product" required defaultValue={v?.product || ""}>
                <option value="">Wybierz smak</option>
                {state.products
                  .filter((x) => x.active || x.id === v?.product)
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Masa netto (g)">
              <input
                name="weight_g"
                type="number"
                min="0.001"
                step="0.001"
                required
                defaultValue={v?.weight_g}
              />
            </Field>
            <Field label="Opakowanie">
              <input
                name="packaging"
                required
                defaultValue={v?.packaging || "Doypack kraft"}
              />
            </Field>
            <Field label="Instrukcja pakowania / standardowej etykiety" wide>
              <textarea name="instruction" defaultValue={v?.instruction} />
            </Field>
            <label className="check-field wide">
              <input
                name="custom_label"
                type="checkbox"
                defaultChecked={v?.custom_label}
              />
              Wymagana personalizowana etykieta klienta
            </label>
          </>
        )}
        {kind === "customers" && (
          <>
            <Field label="Osoba kontaktowa">
              <input name="contact" defaultValue={c?.contact} />
            </Field>
            <Field label="Telefon">
              <input name="phone" defaultValue={c?.phone} />
            </Field>
            <Field label="E-mail">
              <input name="email" type="email" defaultValue={c?.email} />
            </Field>
            <Field label="NIP">
              <input name="tax_id" defaultValue={c?.tax_id} />
            </Field>
            <Field label="Adres" wide>
              <textarea name="address" defaultValue={c?.address} />
            </Field>
          </>
        )}
      </div>
      <label className="check-field">
        <input
          type="checkbox"
          name="active"
          defaultChecked={entity ? entity.active : true}
        />
        Aktywny — dostępny przy nowych zamówieniach
      </label>
    </>
  );
}
