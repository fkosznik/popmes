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
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleAlert,
  Clock3,
  ClipboardList,
  Factory,
  FileText,
  LayoutDashboard,
  LogOut,
  Package,
  Moon,
  Sun,
  Truck,
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
import { roleCopy, statusNames, t, zoneChoices, type Lang } from "./i18n";
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
  StockItem,
  StockDetail,
  Supplier,
} from "./types";

const themes = [
  { id: "plum", name: "Śliwka", color: "#885cba" },
  { id: "teal", name: "Morski", color: "#14627a" },
  { id: "forest", name: "Las", color: "#2f7d4a" },
  { id: "amber", name: "Bursztyn", color: "#b86a1a" },
] as const;
const roleHints: Record<string, string> = {
  sales: "Klienci, zamówienia i wydanie",
  production: "Kolejka produkcji",
  packing: "Wysyłka gotowych zamówień",
  manager: "Plan, korekty i cały obieg",
  admin: "Katalog, konta i ustawienia organizacji",
};
const names: Record<string, string> = {
  draft: "Szkic",
  queued: "Do realizacji",
  producing: "W trakcie produkcji",
  awaiting_shipment: "Czeka na wysyłkę",
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
  packing: "Wysyłka",
  manager: "Kierownik",
  admin: "Administrator",
};
const fmt = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 });

function isShipping(kind: string) {
  return kind === "shipping" || kind === "packing";
}
function produceLeft(item?: { quantity: number; allocated?: number; produced: number }) {
  if (!item) return 0;
  return Math.max(0, item.quantity - (item.allocated || 0) - item.produced);
}
function ingredientLabel(count: number) {
  if (count === 1) return "1 składnik";
  const last = count % 10;
  const lastTwo = count % 100;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14))
    return `${count} składniki`;
  return `${count} składników`;
}
const PACK_WEIGHTS = [15, 30, 100, 400];
type OrderLine = {
  product_id: number;
  weight_g: number;
  logo: boolean;
  quantity: string | number;
};
function matchVariant(
  variants: Variant[],
  line: Pick<OrderLine, "product_id" | "weight_g" | "logo">,
) {
  const matches = variants.filter(
    (v) =>
      v.product === line.product_id &&
      Number(v.weight_g) === Number(line.weight_g) &&
      v.custom_label === line.logo,
  );
  return matches.find((v) => v.active) || matches[0];
}
function deliveryLabel(value?: string, shipping = false) {
  const names = shipping
    ? {
        pickup: "Odbiór osobisty",
        courier: "Wysyłka kurierem",
        locker: "Paczkomat",
        other: "Inny odbiór",
      }
    : {
        pickup: "Odbiór osobisty",
        courier: "Kurier",
        locker: "Paczkomat",
        other: "Inny",
      };
  return names[value as keyof typeof names] || "Odbiór osobisty";
}
function orderStage(
  items: { quantity: number; allocated?: number; produced: number; packed: number }[],
) {
  if (items.length && items.every((item) => item.packed >= item.quantity))
    return "completed";
  if (items.some((item) => produceLeft(item) > 0)) return "producing";
  return "awaiting_shipment";
}
function shipReady(item?: {
  quantity: number;
  allocated?: number;
  produced: number;
  packed: number;
}) {
  if (!item) return 0;
  return Math.max(0, (item.allocated || 0) + item.produced - item.packed);
}
function groupShipping(tasks: Task[]) {
  const map = new Map<number, Task[]>();
  for (const task of tasks) {
    if (!isShipping(task.kind)) continue;
    const list = map.get(task.order_id) || [];
    list.push(task);
    map.set(task.order_id, list);
  }
  return [...map.values()].map((group) => {
    const head = group[0];
    const items =
      head.items && head.items.length
        ? head.items
        : group.flatMap((task) => (task.item ? [task.item] : []));
    const waiting = items.some(
      (item) => item.quantity - item.packed > shipReady(item),
    );
    const blockers = [...new Set(group.flatMap((task) => task.blockers))];
    const hard = blockers.filter((reason) => reason !== "Czeka na produkcję");
    const done =
      items.length > 0 && items.every((item) => item.packed >= item.quantity);
    const status = done
      ? "done"
      : hard.length
        ? "blocked"
        : waiting
          ? "waiting"
          : "ready";
    return { head, items, blockers, status };
  });
}
const kg = (g: string | number) => fmt.format(Number(g) / 1000) + " kg";
const clock = { lang: "pl" as Lang, zone: "Europe/Warsaw" };
const dateLocale = () => (clock.lang === "en" ? "en-GB" : "pl-PL");
const dt = (s: string | null) =>
  s
    ? new Date(s).toLocaleString(dateLocale(), {
        timeZone: clock.zone,
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : clock.lang === "en"
      ? "No date"
      : "Brak terminu";
const late = (o: Order) =>
  Boolean(
    o.due_at &&
    new Date(o.due_at) < new Date() &&
    !["completed", "issued", "cancelled", "draft"].includes(o.status),
  );
type OrderSortKey = "customer" | "flavor" | "due" | "progress" | "status";
const orderColumns: { key: OrderSortKey; label: string }[] = [
  { key: "customer", label: "Zamówienie / klient" },
  { key: "flavor", label: "Produkty" },
  { key: "due", label: "Termin gotowości" },
  { key: "progress", label: "Realizacja" },
  { key: "status", label: "Status" },
];
const flavorText = (order: Order) =>
  order.items
    .map((item) => `${item.product_name} ${fmt.format(Number(item.weight_g))} g`)
    .join(" · ");
function compareOrders(
  a: Order,
  b: Order,
  key: OrderSortKey,
  dir: "asc" | "desc",
) {
  let diff = 0;
  if (key === "due") {
    const left = a.due_at ? new Date(a.due_at).getTime() : null;
    const right = b.due_at ? new Date(b.due_at).getTime() : null;
    if (left === null && right === null) diff = 0;
    else if (left === null) return 1;
    else if (right === null) return -1;
    else diff = left - right;
  } else if (key === "progress") {
    const ratio = (order: Order) => (order.units ? order.packed / order.units : 0);
    diff = ratio(a) - ratio(b) || a.packed - b.packed;
  } else if (key === "status") {
    const label = (order: Order) =>
      order.hold_reason ? "Wstrzymane" : names[order.status] || order.status;
    diff = label(a).localeCompare(label(b), "pl", { sensitivity: "base" });
  } else if (key === "flavor") {
    diff = flavorText(a).localeCompare(flavorText(b), "pl", {
      sensitivity: "base",
      numeric: true,
    });
  } else {
    diff = a.customer_name.localeCompare(b.customer_name, "pl", {
      sensitivity: "base",
    });
  }
  if (!diff) return b.id - a.id;
  return dir === "asc" ? diff : -diff;
}
const localDate = (s: string | null) =>
  s
    ? new Date(s)
        .toLocaleString("sv-SE", { timeZone: clock.zone })
        .slice(0, 16)
        .replace(" ", "T")
    : "";
// Inputs represent the user's time zone; Intl supplies the UTC offset, including DST.
function fromWarsaw(value: string) {
  if (!value) return null;
  const guess = new Date(value + "Z");
  const wall = new Date(
    guess.toLocaleString("sv-SE", { timeZone: clock.zone }).replace(" ", "T") +
      "Z",
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
  stockItem?: StockItem;
  supplier?: Supplier;
  entity?: Product | Variant | Customer | User;
  catalog?: string;
};
type Focus =
  | { kind: "stock"; id: number }
  | { kind: "product"; id: number }
  | { kind: "variant"; id: number };

export default function App() {
  const [user, setUser] = useState<User | null>(null),
    [boot, setBoot] = useState(true),
    [state, setState] = useState<State | null>(null),
    [appVersion, setAppVersion] = useState<string | null>(null);
  const [page, setPage] = useState("dashboard"),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [orderSort, setOrderSort] = useState<{
      key: OrderSortKey;
      dir: "asc" | "desc";
    } | null>(null),
    [ordersOffset, setOrdersOffset] = useState(0),
    [catalogTab, setCatalogTab] = useState("variants");
  const [modal, setModal] = useState<ModalState | null>(null),
    [selected, setSelected] = useState<number | null>(null),
    [detail, setDetail] = useState<Detail | null>(null),
    [focus, setFocus] = useState<Focus | null>(null),
    [stockExtra, setStockExtra] = useState<StockDetail | null>(null),
    [historyFailed, setHistoryFailed] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [offline, setOffline] = useState(false),
    [mobile, setMobile] = useState(false),
    [users, setUsers] = useState<User[]>([]);
  const [packWeight, setPackWeight] = useState<number | null>(null);
  const [account, setAccount] = useState<{
    name: string;
    email: string;
    phone: string;
    street: string;
    postal_code: string;
    city: string;
    country: string;
    language: Lang;
    timezone: string;
    start_page: string;
    appearance: "light" | "dark";
  } | null>(null);
  const [passwords, setPasswords] = useState({
    current_password: "",
    password: "",
    password_repeat: "",
  });
  const [orgForm, setOrgForm] = useState<{
    name: string;
    default_language: "pl" | "en";
    theme: "plum" | "teal" | "forest" | "amber";
  } | null>(null);
  const [spaceForm, setSpaceForm] = useState<{
    id?: number;
    name: string;
    active: boolean;
    primary: boolean;
  }>({ name: "", active: true, primary: false });
  const startApplied = useRef(false);
  const [lines, setLines] = useState<OrderLine[]>([]);
  const [recipeLines, setRecipeLines] = useState<
    { stock_id: number; quantity: string }[]
  >([{ stock_id: 0, quantity: "" }]);
  const [customerId, setCustomerId] = useState(0);
  const [deliveryMethod, setDeliveryMethod] = useState("courier");
  const retryKeys = useRef(new Map<string, string>()),
    mutationLock = useRef(false);
  const can = (...r: string[]) =>
    Boolean(user?.roles.some((x) => r.includes(x)));
  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (page === "dashboard") params.set("orders_scope", "upcoming");
    else if (page === "orders") {
      params.set("orders_scope", "page");
      params.set("orders_limit", "50");
      params.set("orders_offset", String(ordersOffset));
      if (query) params.set("orders_q", query);
      if (filter) params.set("orders_status", filter);
      if (orderSort) {
        params.set("orders_sort", orderSort.key);
        params.set("orders_dir", orderSort.dir);
      }
    } else params.set("orders_scope", "none");
    try {
      const data = await api<State>("state/?" + params.toString());
      setState(data);
      setUser(data.user);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, [page, query, filter, orderSort, ordersOffset]);
  useEffect(() => {
    api<{ user: User | null }>("auth/me/")
      .then((r) => setUser(r.user))
      .catch((e) => setError(errorText(e)))
      .finally(() => setBoot(false));
  }, []);
  useEffect(() => {
    if (!user) return;
    let cancel = false;
    api<{ version?: string }>("version/")
      .then((data) => {
        if (cancel) return;
        const value = (data.version || "").trim();
        setAppVersion(/^\d+\.\d+\.\d+$/.test(value) ? value : null);
      })
      .catch(() => {
        if (!cancel) setAppVersion(null);
      });
    return () => {
      cancel = true;
    };
  }, [user?.id]);
  useEffect(() => {
    setOrdersOffset(0);
  }, [query, filter, orderSort, page]);
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
    if (selected === null || !user) {
      setDetail(null);
      return;
    }
    let cancel = false;
    const pull = () =>
      api<Detail>(`orders/${selected}/`)
        .then((data) => {
          if (!cancel) setDetail(data);
        })
        .catch((e) => {
          if (!cancel) setError(errorText(e));
        });
    pull();
    const timer = setInterval(pull, 5000);
    return () => {
      cancel = true;
      clearInterval(timer);
    };
  }, [selected, user?.id]);
  useEffect(() => {
    if (!user || focus?.kind !== "stock") {
      setStockExtra(null);
      setHistoryFailed(false);
      return;
    }
    const id = focus.id;
    let cancel = false;
    setHistoryFailed(false);
    const pull = () =>
      api<StockDetail>(`stock/${id}/detail/`)
        .then((data) => {
          if (!cancel) setStockExtra(data);
        })
        .catch(() => {
          if (!cancel) setHistoryFailed(true);
        });
    pull();
    const timer = setInterval(pull, 15000);
    return () => {
      cancel = true;
      clearInterval(timer);
    };
  }, [user, focus]);
  useEffect(() => {
    if ((page === "admin" || page === "users") && user)
      api<User[]>("users/")
        .then(setUsers)
        .catch((e) => setError(errorText(e)));
  }, [page, state]);
  useEffect(() => {
    document.documentElement.dataset.theme = state?.organization?.theme || "plum";
  }, [state?.organization?.theme]);
  useEffect(() => {
    const chosen = page === "account" && account ? account.appearance : user?.appearance;
    document.documentElement.dataset.mode = chosen === "dark" ? "dark" : "light";
  }, [user?.appearance, account, page]);
  useEffect(() => {
    if (page !== "admin") {
      setOrgForm(null);
      return;
    }
    if (!state?.organization || orgForm) return;
    const theme = state.organization.theme;
    setOrgForm({
      name: state.organization.name,
      default_language: state.organization.default_language === "en" ? "en" : "pl",
      theme:
        theme === "teal" || theme === "forest" || theme === "amber" ? theme : "plum",
    });
  }, [page, state, orgForm]);
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !mutationLock.current) {
        setModal(null);
        setSelected(null);
        setFocus(null);
      }
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, []);
  useEffect(() => {
    if (!user || startApplied.current) return;
    startApplied.current = true;
    const next = user.start_page;
    if (!next || next === "dashboard") return;
    const has = (...roles: string[]) => user.roles.some((r) => roles.includes(r));
    const allowed =
      next === "orders" || next === "customers"
        ? has("sales", "manager")
        : next === "production"
          ? has("production", "manager")
          : next === "shipping"
            ? has("packing", "manager")
            : next === "stock"
              ? has("manager", "sales", "production", "packing", "admin")
              : next === "catalog"
                ? has("admin", "manager", "sales")
                : next === "users" || next === "admin"
                ? has("admin")
                : false;
    if (allowed) setPage(next === "users" ? "admin" : next);
  }, [user]);
  useEffect(() => {
    if (page !== "account") {
      setAccount(null);
      return;
    }
    if (!user || account) return;
    setAccount({
      name: user.name,
      email: user.email || "",
      phone: user.phone || "",
      street: user.street || "",
      postal_code: user.postal_code || "",
      city: user.city || "",
      country: user.country || "",
      language: user.language === "en" ? "en" : "pl",
      timezone: user.timezone || "Europe/Warsaw",
      start_page: user.start_page || "dashboard",
      appearance: user.appearance === "dark" ? "dark" : "light",
    });
  }, [page, user, account]);
  const lang: Lang = user?.language === "en" ? "en" : "pl";
  clock.lang = lang;
  clock.zone = user?.timezone || "Europe/Warsaw";
  Object.assign(names, statusNames[lang]);
  Object.assign(roleNames, roleCopy[lang]);
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
      setToast(t(lang, "saved"));
      await load();
      if (selected !== null) {
        const fresh = await api<Detail>(`orders/${selected}/`);
        setDetail(fresh);
      }
      return result;
    } catch (e) {
      setError(errorText(e));
      return undefined;
    } finally {
      setBusy(false);
      mutationLock.current = false;
    }
  };
  function toggleAppearance() {
    if (!user) return;
    const next = user.appearance === "dark" ? "light" : "dark";
    if (account) setAccount({ ...account, appearance: next });
    void perform(
      "account/",
      {
        name: user.name,
        email: user.email || "",
        phone: user.phone || "",
        street: user.street || "",
        postal_code: user.postal_code || "",
        city: user.city || "",
        country: user.country || "",
        language: user.language === "en" ? "en" : "pl",
        timezone: user.timezone || "Europe/Warsaw",
        start_page: user.start_page || "dashboard",
        appearance: next,
      },
      false,
    );
  }
  function go(p: string) {
    setPage(p);
    setFilter("all");
    setQuery("");
    setSelected(null);
    setFocus(null);
    setMobile(false);
  }
  function open(m: ModalState) {
    setError("");
    setModal(m);
    if (m.kind === "order") {
      setCustomerId(m.order?.customer_id || 0);
      setDeliveryMethod(m.order?.delivery || "courier");
      const next = (m.order?.items || []).map((i) => ({
        product_id: i.product_id,
        weight_g: Number(i.weight_g),
        logo: i.custom_label,
        quantity: i.quantity,
      }));
      setLines(next);
      setPackWeight(next[0]?.weight_g ?? null);
    }
    if (m.kind === "recipe") {
      const variant = m.entity as Variant;
      setRecipeLines(
        variant.recipe?.length
          ? variant.recipe.map((line) => ({
              stock_id: line.stock_id,
              quantity: line.quantity,
            }))
          : [{ stock_id: 0, quantity: "" }],
      );
    }
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
      setFocus(null);
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
              Zamówienia, produkcja i wysyłka.
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
                <Truck />
                Wysyłka
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
    { id: "dashboard", title: t(lang, "overview"), icon: LayoutDashboard, show: true },
    {
      id: "orders",
      title: t(lang, "orders"),
      icon: ClipboardList,
      show: can("sales", "manager"),
    },
    {
      id: "production",
      title: t(lang, "production"),
      icon: Factory,
      show: can("production", "manager"),
    },
    {
      id: "shipping",
      title: t(lang, "shipping"),
      icon: Truck,
      show: can("packing", "manager"),
    },
    {
      id: "stock",
      title: t(lang, "stock"),
      icon: Warehouse,
      show: can("manager", "sales", "production", "packing", "admin"),
    },
    {
      id: "catalog",
      title: t(lang, "catalog"),
      icon: Boxes,
      show: can("admin", "manager", "sales"),
    },
    {
      id: "customers",
      title: t(lang, "customers"),
      icon: Users,
      show: can("sales", "manager"),
    },
    { id: "admin", title: t(lang, "admin"), icon: Settings2, show: can("admin") },
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
    (t) => isShipping(t.kind) && t.status !== "done",
  );
  const focusedStock =
    focus?.kind === "stock"
      ? (state?.stock || []).find((item) => item.id === focus.id)
      : undefined;
  const focusedProduct =
    focus?.kind === "product"
      ? (state?.products || []).find((item) => item.id === focus.id)
      : undefined;
  const focusedVariant =
    focus?.kind === "variant"
      ? (state?.variants || []).find((item) => item.id === focus.id)
      : undefined;
  const stockHistory =
    stockExtra && focusedStock && stockExtra.id === focusedStock.id
      ? stockExtra
      : null;
  const focusedSupplier = focusedStock
    ? (state?.suppliers || []).find(
        (row) => row.id === focusedStock.supplier_id,
      ) ||
      (stockHistory?.supplier?.id === focusedStock.supplier_id
        ? stockHistory.supplier
        : null)
    : null;
  const stockVariant = focusedStock?.variant_id
    ? (state?.variants || []).find((row) => row.id === focusedStock.variant_id)
    : undefined;
  const productionRemaining = can("sales", "manager")
    ? (state?.summary?.production_remaining ??
      active.reduce(
        (sum, order) =>
          sum + order.items.reduce((a, item) => a + produceLeft(item), 0),
        0,
      ))
    : production.reduce((sum, task) => sum + produceLeft(task.item), 0);
  const packingRemaining = can("sales", "manager")
    ? (state?.summary?.packing_remaining ??
      active.reduce(
        (sum, order) => sum + Math.max(0, order.units - order.packed),
        0,
      ))
    : packing.reduce(
        (sum, task) =>
          sum + (task.item ? task.item.quantity - task.item.packed : 0),
        0,
      );
  const overdueCount = can("sales", "manager")
    ? (state?.summary?.overdue ?? orders.filter(late).length)
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
  const filteredOrders =
    page === "orders"
      ? orders
      : orders.filter(
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
  const sortedOrders =
    page === "orders" || !orderSort
      ? filteredOrders
      : [...filteredOrders].sort((a, b) =>
          compareOrders(a, b, orderSort.key, orderSort.dir),
        );
  function toggleOrderSort(key: OrderSortKey) {
    setOrderSort((current) =>
      current?.key === key
        ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }
  const filteredTasks = tasks.filter(
    (t) =>
      (page === "shipping" ? isShipping(t.kind) : t.kind === page) &&
      (filter === "all"
        ? t.status !== "done"
        : filter === "blocked"
          ? t.blockers.length > 0
          : t.status === filter) &&
      (t.order_number + " " + t.product_name + " " + (t.customer_name || ""))
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const shippingCards = groupShipping(tasks).filter((card) => {
    const haystack = [
      card.head.order_number,
      card.head.customer_name,
      card.head.customer_email,
      card.head.customer_phone,
      card.head.address,
      ...card.items.map((item) => item.name),
    ]
      .join(" ")
      .toLowerCase();
    return (
      haystack.includes(query.toLowerCase()) &&
      (filter === "all" ? card.status !== "done" : card.status === filter)
    );
  });
  const title =
    page === "account"
      ? t(lang, "settings")
      : nav.find((n) => n.id === page)?.title || t(lang, "overview");
  const action = (path: string, data: unknown = {}) =>
    void perform(path, data, false);
  const orderTable = (list: Order[], sortable = false) =>
    list.length ? (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {orderColumns.map((column) =>
                sortable ? (
                  <th
                    key={column.key}
                    className="sortable"
                    aria-sort={
                      orderSort?.key === column.key
                        ? orderSort.dir === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <button
                      type="button"
                      onClick={() => toggleOrderSort(column.key)}
                    >
                      {column.label}
                      {orderSort?.key === column.key &&
                        (orderSort.dir === "asc" ? (
                          <ChevronUp size={12} aria-hidden="true" />
                        ) : (
                          <ChevronDown size={12} aria-hidden="true" />
                        ))}
                    </button>
                  </th>
                ) : (
                  <th key={column.key}>{column.label}</th>
                ),
              )}
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
                <td className="order-products">
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
                  <small>{flavorText(o)}</small>
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
                    <b>{o.packed}</b> / {o.units} wysłane
                  </div>
                  <small>
                    z magazynu {o.allocated} · wyprodukowane {o.produced}
                  </small>
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
  const spaces = (state?.workspaces || []).filter((item) => item.active);
  const currentSpace =
    spaces.find((item) => item.id === state?.workspace_id) || spaces[0];
  const orgName = state?.organization?.name || "POPME";
  const chooseSpace = (id: number) => {
    void api("workspaces/current/", { id }, requestKey())
      .then(() => {
        setSelected(null);
        setFocus(null);
        return load();
      })
      .catch((err) => setError(errorText(err)));
  };
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
          <span className="workspace-icon">
            {(currentSpace?.name || orgName).slice(0, 1).toUpperCase()}
          </span>
          <div>
            {spaces.length > 1 ? (
              <select
                aria-label="Przestrzeń produkcyjna"
                value={currentSpace?.id || ""}
                onChange={(e) => chooseSpace(Number(e.target.value))}
              >
                {spaces.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            ) : (
              currentSpace?.name || orgName
            )}
            <small>
              {spaces.length > 1 ? orgName : "Przestrzeń produkcyjna"}
            </small>
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
                {n.id === "orders" && (state?.summary?.active || active.length) > 0 && (
                  <b>{state?.summary?.active ?? active.length}</b>
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
          <button
            type="button"
            className={"user-open" + (page === "account" ? " selected" : "")}
            aria-label={t(lang, "openSettings")}
            onClick={() => go("account")}
          >
            <span className="avatar">{user.name.slice(0, 2).toUpperCase()}</span>
            <span>
              <strong>{user.name}</strong>
              <small>{user.roles.map((r) => roleNames[r]).join(", ")}</small>
            </span>
          </button>
          <button
            className="user-logout"
            title={t(lang, "logout")}
            aria-label={t(lang, "logout")}
            onClick={logoutClick}
          >
            <LogOut size={17} />
          </button>
        </div>
        {appVersion && <p className="app-version">POPMES {appVersion}</p>}
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
            {orgName} <ChevronRight size={13} /> <strong>{title}</strong>
          </div>
          <div className={"sync " + (offline ? "bad" : "")}>
            <span />
            {offline ? "Brak synchronizacji" : "Dane na bieżąco"}
          </div>
          <button
            type="button"
            className="mode-toggle"
            aria-pressed={user.appearance === "dark"}
            aria-label={
              user.appearance === "dark" ? t(lang, "light") : t(lang, "dark")
            }
            onClick={toggleAppearance}
          >
            {user.appearance === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <span className="top-date">
            {new Date().toLocaleDateString(dateLocale(), {
              day: "numeric",
              month: "long",
              year: "numeric",
              timeZone: clock.zone,
            })}
          </span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {page === "dashboard"
                  ? t(lang, "eyebrowHome")
                  : t(lang, "eyebrowOps")}
              </div>
              <h1>
                {page === "dashboard"
                  ? t(lang, "hello").replace(
                      "{name}",
                      user.name.split(" ")[0],
                    )
                  : title}
              </h1>
              <p>
                {page === "dashboard"
                  ? t(lang, "blurbDashboard")
                  : page === "account"
                    ? t(lang, "settingsLead")
                    : page === "production"
                      ? t(lang, "blurbProduction")
                      : page === "shipping"
                        ? t(lang, "blurbShipping")
                        : page === "orders"
                          ? t(lang, "blurbOrders")
                          : page === "stock"
                            ? t(lang, "blurbStock")
                            : page === "admin"
                              ? t(lang, "blurbAdmin")
                              : t(lang, "blurbDefault")}
              </p>
            </div>
            {can("sales", "manager") &&
              ["dashboard", "orders"].includes(page) && (
                <button
                  className="primary"
                  onClick={() => open({ kind: "order" })}
                >
                  <Plus size={17} /> {t(lang, "newOrder")}
                </button>
              )}
            {["catalog", "customers", "admin"].includes(page) &&
              can(
                ...(page === "admin"
                  ? ["admin"]
                  : page === "customers"
                    ? ["sales", "manager"]
                    : ["admin", "manager"]),
              ) && (
                <button
                  className="primary"
                  onClick={() =>
                    open({
                      kind: page === "admin" ? "user" : "catalog",
                      catalog: page === "customers" ? "customers" : catalogTab,
                    })
                  }
                >
                  <Plus size={17} />
                  {page === "admin"
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
              {page === "account" && account && (
                <div className="account-page">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void perform("account/", account, false);
                    }}
                  >
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>{t(lang, "yourData")}</h2>
                        </div>
                      </div>
                      <div className="account-body">
                    <div className="form-grid">
                      <Field label={t(lang, "name")}>
                        <input
                          required
                          value={account.name}
                          onChange={(e) =>
                            setAccount({ ...account, name: e.target.value })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "login")}>
                        <input value={user.username} readOnly />
                      </Field>
                      <Field label={t(lang, "email")}>
                        <input
                          type="email"
                          value={account.email}
                          autoComplete="email"
                          onChange={(e) =>
                            setAccount({ ...account, email: e.target.value })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "phone")}>
                        <input
                          value={account.phone}
                          autoComplete="tel"
                          onChange={(e) =>
                            setAccount({ ...account, phone: e.target.value })
                          }
                        />
                      </Field>
                    </div>
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>{t(lang, "address")}</h2>
                          <p>{t(lang, "addressHint")}</p>
                        </div>
                      </div>
                      <div className="account-body">
                    <div className="form-grid account-address">
                      <Field label={t(lang, "street")} wide>
                        <input
                          value={account.street}
                          autoComplete="street-address"
                          onChange={(e) =>
                            setAccount({ ...account, street: e.target.value })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "postal")}>
                        <input
                          value={account.postal_code}
                          autoComplete="postal-code"
                          onChange={(e) =>
                            setAccount({
                              ...account,
                              postal_code: e.target.value,
                            })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "city")}>
                        <input
                          value={account.city}
                          autoComplete="address-level2"
                          onChange={(e) =>
                            setAccount({ ...account, city: e.target.value })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "country")}>
                        <input
                          value={account.country}
                          autoComplete="country-name"
                          onChange={(e) =>
                            setAccount({ ...account, country: e.target.value })
                          }
                        />
                      </Field>
                    </div>
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>{t(lang, "preferences")}</h2>
                          <p>{t(lang, "languageHint")}</p>
                        </div>
                      </div>
                      <div className="account-body">
                    <div className="form-grid account-prefs">
                      <Field label={t(lang, "language")}>
                        <select
                          value={account.language}
                          onChange={(e) =>
                            setAccount({
                              ...account,
                              language: e.target.value === "en" ? "en" : "pl",
                            })
                          }
                        >
                          <option value="pl">Polski</option>
                          <option value="en">English</option>
                        </select>
                      </Field>
                      <Field label={t(lang, "timezone")}>
                        <select
                          value={account.timezone}
                          onChange={(e) =>
                            setAccount({ ...account, timezone: e.target.value })
                          }
                        >
                          {zoneChoices.map((zone) => (
                            <option key={zone.id} value={zone.id}>
                              {lang === "en" ? zone.en : zone.pl}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label={t(lang, "startPage")}>
                        <select
                          value={account.start_page}
                          onChange={(e) =>
                            setAccount({
                              ...account,
                              start_page: e.target.value,
                            })
                          }
                        >
                          {nav
                            .filter((item) => item.show)
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.title}
                              </option>
                            ))}
                        </select>
                      </Field>
                      <Field label={t(lang, "appearance")} wide>
                        <div className="appearance-choices">
                          <button
                            type="button"
                            aria-pressed={account.appearance !== "dark"}
                            onClick={() =>
                              setAccount({ ...account, appearance: "light" })
                            }
                          >
                            <Sun size={16} /> {t(lang, "light")}
                          </button>
                          <button
                            type="button"
                            aria-pressed={account.appearance === "dark"}
                            onClick={() =>
                              setAccount({ ...account, appearance: "dark" })
                            }
                          >
                            <Moon size={16} /> {t(lang, "dark")}
                          </button>
                        </div>
                      </Field>
                    </div>
                    <div className="account-actions">
                      <button className="primary" type="submit" disabled={busy}>
                        {t(lang, "save")}
                      </button>
                    </div>
                      </div>
                    </section>
                  </form>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void perform("account/password/", passwords, false).then(
                        (result) => {
                          if (result)
                            setPasswords({
                              current_password: "",
                              password: "",
                              password_repeat: "",
                            });
                        },
                      );
                    }}
                  >
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>{t(lang, "passwordSection")}</h2>
                          <p>{t(lang, "passwordHint")}</p>
                        </div>
                      </div>
                      <div className="account-body">
                    <div className="form-grid">
                      <Field label={t(lang, "currentPassword")} wide>
                        <input
                          type="password"
                          required
                          autoComplete="current-password"
                          value={passwords.current_password}
                          onChange={(e) =>
                            setPasswords({
                              ...passwords,
                              current_password: e.target.value,
                            })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "newPassword")}>
                        <input
                          type="password"
                          required
                          minLength={10}
                          autoComplete="new-password"
                          value={passwords.password}
                          onChange={(e) =>
                            setPasswords({
                              ...passwords,
                              password: e.target.value,
                            })
                          }
                        />
                      </Field>
                      <Field label={t(lang, "repeatPassword")}>
                        <input
                          type="password"
                          required
                          minLength={10}
                          autoComplete="new-password"
                          value={passwords.password_repeat}
                          onChange={(e) =>
                            setPasswords({
                              ...passwords,
                              password_repeat: e.target.value,
                            })
                          }
                        />
                      </Field>
                    </div>
                    <div className="account-actions">
                      <button className="primary" type="submit" disabled={busy}>
                        {t(lang, "changePassword")}
                      </button>
                    </div>
                      </div>
                    </section>
                  </form>
                </div>
              )}
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
                          ? (state?.summary?.active ?? active.length)
                          : tasks.filter((t) => t.status !== "done").length
                      }
                      sub="Wspólny plan zespołu"
                      icon={<ClipboardList />}
                    />
                    <Metric
                      label="Do wyprodukowania"
                      value={
                        can("sales", "manager", "production")
                          ? fmt.format(productionRemaining)
                          : "—"
                      }
                      sub="opakowań"
                      icon={<Factory />}
                    />
                    <Metric
                      label="Do wysyłki"
                      value={
                        can("sales", "manager", "packing")
                          ? fmt.format(packingRemaining)
                          : "—"
                      }
                      sub="opakowań jeszcze niewysłanych"
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
                                  : "shipping",
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
                          {(() => {
                            const seen = new Set<string>();
                            return tasks
                              .filter((t) => t.status !== "done")
                              .filter((t) => {
                                const key = isShipping(t.kind)
                                  ? `ship-${t.order_id}`
                                  : `task-${t.id}`;
                                if (seen.has(key)) return false;
                                seen.add(key);
                                return true;
                              })
                              .slice(0, 5);
                          })().map((t) => (
                              <button
                                key={t.id}
                                onClick={() =>
                                  go(isShipping(t.kind) ? "shipping" : t.kind)
                                }
                              >
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
                                  <strong>
                                    {isShipping(t.kind)
                                      ? t.customer_name || t.order_number
                                      : t.product_name}
                                  </strong>
                                  <small>
                                    {t.order_number} ·{" "}
                                    {t.kind === "production"
                                      ? `${t.item?.quantity ?? 0} opak.`
                                      : (t.items || [])
                                          .map(
                                            (item) =>
                                              `${item.quantity} × ${item.name}`,
                                          )
                                          .join(", ") || "Do wysyłki"}
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
                          <strong>Wyprodukuj opakowania</strong>
                          <small>Gotowe paczki popcornu, nie kilogramy</small>
                        </div>
                        <Factory size={19} />
                      </div>
                      <div className="flow-step">
                        <span>03</span>
                        <div>
                          <strong>Oznacz wysyłkę</strong>
                          <small>Zaznacz, kiedy opakowania wyjechały</small>
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
                        "producing",
                        "awaiting_shipment",
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
                  {orderTable(sortedOrders, true)}
                  {(state?.orders_page?.count || 0) > (state?.orders_page?.limit || 50) && (
                    <div className="pager">
                      <button
                        type="button"
                        className="text-button"
                        disabled={ordersOffset <= 0}
                        onClick={() =>
                          setOrdersOffset((current) =>
                            Math.max(0, current - (state?.orders_page?.limit || 50)),
                          )
                        }
                      >
                        Poprzednie
                      </button>
                      <span>
                        {ordersOffset + 1}–
                        {Math.min(
                          ordersOffset + orders.length,
                          state?.orders_page?.count || 0,
                        )}{" "}
                        z {state?.orders_page?.count}
                      </span>
                      <button
                        type="button"
                        className="text-button"
                        disabled={
                          ordersOffset + (state?.orders_page?.limit || 50) >=
                          (state?.orders_page?.count || 0)
                        }
                        onClick={() =>
                          setOrdersOffset(
                            (current) => current + (state?.orders_page?.limit || 50),
                          )
                        }
                      >
                        Następne
                      </button>
                    </div>
                  )}
                </section>
              )}
              {page === "shipping" && (
                <>
                  <div className="queue-summary">
                    <span>
                      <i className="online-dot" /> {shippingCards.length}{" "}
                      zamówień w widoku
                    </span>
                    <span>Całe zamówienie, bez dzielenia na smaki</span>
                  </div>
                  <section className="panel toolbar-panel">
                    <Toolbar
                      query={query}
                      setQuery={setQuery}
                      placeholder="Szukaj numeru, klienta, smaku lub adresu…"
                    >
                      <select
                        aria-label="Filtr wysyłek"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        {[
                          ["all", "Do wysłania"],
                          ["ready", "Gotowe do wysłania"],
                          ["waiting", "Czeka na produkcję"],
                          ["blocked", "Wstrzymane"],
                          ["done", "Wysłane"],
                        ].map(([k, n]) => (
                          <option key={k} value={k}>
                            {n}
                          </option>
                        ))}
                      </select>
                    </Toolbar>
                  </section>
                  <div className="task-grid">
                    {shippingCards.map((card) => (
                      <article className="task-card" key={card.head.order_id}>
                        <div className="task-top">
                          <span>{card.head.order_number}</span>
                          {card.head.priority === "urgent" ? (
                            <span className="urgent">
                              <Zap size={13} />
                              Pilne
                            </span>
                          ) : (
                            <span className="task-date">
                              <Clock3 size={12} />
                              {dt(card.head.due_at)}
                            </span>
                          )}
                        </div>
                        <div className="task-title">
                          <span
                            className="flavor-icon"
                            style={{ background: "#f4efe8", color: "#8a5a2b" }}
                          >
                            <Truck size={22} />
                          </span>
                          <div>
                            <h2>
                              {card.head.customer_name || "Bez klienta"}
                            </h2>
                            <p>
                              {deliveryLabel(card.head.delivery, true)}
                            </p>
                            <Badge status={orderStage(card.items)} />
                          </div>
                        </div>
                        <ul className="ship-lines">
                          {card.items.map((item) => (
                            <li key={item.id}>
                              <strong>{fmt.format(item.quantity)} szt.</strong>
                              <span>
                                {item.name}
                                <small>
                                  {" "}
                                  · {fmt.format(Number(item.weight_g))} g
                                  {item.packed > 0 &&
                                  item.packed < item.quantity
                                    ? ` · wysłano ${fmt.format(item.packed)}`
                                    : ""}
                                </small>
                              </span>
                            </li>
                          ))}
                        </ul>
                        <div className="ship-contact">
                          <p>
                            <small>Adres wysyłki</small>
                            {card.head.address ||
                              (card.head.delivery === "pickup"
                                ? "Odbiór osobisty"
                                : "Brak adresu")}
                          </p>
                          <p>
                            <small>E-mail</small>
                            {card.head.customer_email || "Brak e-maila"}
                          </p>
                          <p>
                            <small>Telefon</small>
                            {card.head.customer_phone || "Brak telefonu"}
                          </p>
                        </div>
                        {card.status === "waiting" && (
                          <div className="task-block">
                            <CircleAlert size={14} />
                            Czeka na produkcję
                          </div>
                        )}
                        {card.status === "blocked" && (
                          <div className="task-block">
                            <CircleAlert size={14} />
                            {card.blockers
                              .filter((reason) => reason !== "Czeka na produkcję")
                              .join(" · ")}
                          </div>
                        )}
                        <div className="task-actions">
                          <button
                            className="primary"
                            disabled={busy || card.status !== "ready"}
                            onClick={() =>
                              action(`orders/${card.head.order_id}/ship/`)
                            }
                          >
                            <Check size={16} /> Wysłano
                          </button>
                          <button
                            onClick={() => setSelected(card.head.order_id)}
                          >
                            Więcej szczegółów
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                  {!shippingCards.length && (
                    <section className="panel">
                      <Empty
                        title="Brak zamówień w tym widoku"
                        text="Zmień filtr albo dokończ produkcję."
                      />
                    </section>
                  )}
                </>
              )}
              {page === "production" && (
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
                      <article
                        className={
                          "task-card" +
                          (t.item?.custom_label ? " with-logo" : "")
                        }
                        key={t.id}
                      >
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
                              background:
                                (t.item?.custom_label ? "#14627a" : t.color) +
                                "22",
                              color: t.item?.custom_label ? "#14627a" : t.color,
                            }}
                          >
                            <Popcorn size={26} />
                          </span>
                          <div>
                            <h2>{t.item?.name || t.product_name}</h2>
                            <p>
                              {t.kind === "production" ? (
                                t.item ? (
                                  <>
                                    <strong className="pack-weight">
                                      {fmt.format(Number(t.item.weight_g))} g
                                    </strong>
                                    {" · "}
                                    {t.item.packaging}
                                  </>
                                ) : (
                                  "Starsze zlecenie w kilogramach"
                                )
                              ) : (
                                deliveryLabel(t.delivery, true)
                              )}
                            </p>
                          </div>
                        </div>
                        {t.customer_name && (
                          <div className="client-note">{t.customer_name}</div>
                        )}
                        <div className="task-count">
                          <strong>
                            {fmt.format(
                              t.kind === "production"
                                ? (t.item?.produced ?? 0)
                                : (t.item?.packed ?? 0),
                            )}
                          </strong>
                          <span>
                            /{" "}
                            {fmt.format(
                              t.kind === "production"
                                ? produceLeft(t.item) + (t.item?.produced ?? 0)
                                : (t.item?.quantity ?? 0),
                            )}{" "}
                            opak.
                          </span>
                          <Badge status={t.status} />
                        </div>
                        <Progress
                          value={
                            t.kind === "production"
                              ? (t.item?.produced ?? 0)
                              : (t.item?.packed ?? 0)
                          }
                          total={
                            t.kind === "production"
                              ? produceLeft(t.item) + (t.item?.produced ?? 0)
                              : (t.item?.quantity ?? 0)
                          }
                        />
                        <div className="task-info">
                          <span>
                            {t.kind === "production"
                              ? "Pozostało do wyprodukowania"
                              : "Gotowe do wysyłki"}
                          </span>
                          <strong>
                            {fmt.format(
                              t.kind === "production"
                                ? produceLeft(t.item)
                                : shipReady(t.item),
                            )}
                          </strong>
                        </div>
                        {t.kind === "production" && (t.item?.allocated ?? 0) > 0 && (
                          <p className="instruction">
                            Z magazynu: {fmt.format(t.item?.allocated ?? 0)} opak.
                            Produkujesz tylko brakującą resztę.
                          </p>
                        )}
                        {isShipping(t.kind) && t.address && (
                          <p className="instruction">{t.address}</p>
                        )}
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
                              disabled={
                                busy ||
                                t.blockers.length > 0 ||
                                (t.kind === "production" && !t.item)
                              }
                              onClick={() => open({ kind: "report", task: t })}
                            >
                              <Check size={16} />
                              {t.kind === "production"
                                ? "Zgłoś opakowania"
                                : "Oznacz jako wysłane"}
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
                              aria-label={`Szczegóły ${p.name}`}
                              onClick={() =>
                                setFocus({ kind: "product", id: p.id })
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
                              <th>W magazynie</th>
                              <th>Receptura</th>
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
                                <tr
                                  key={v.id}
                                  tabIndex={0}
                                  onClick={() =>
                                    setFocus({ kind: "variant", id: v.id })
                                  }
                                  onKeyDown={(e) => {
                                    if (
                                      e.key === "Enter" &&
                                      e.target === e.currentTarget
                                    )
                                      setFocus({ kind: "variant", id: v.id });
                                  }}
                                >
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
                                    <strong>
                                      {fmt.format(Number(v.stock_available || 0))}{" "}
                                      szt
                                    </strong>
                                    <small>
                                      stan {fmt.format(Number(v.stock_quantity || 0))}
                                    </small>
                                  </td>
                                  <td>
                                    {can("manager") ? (
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          open({
                                            kind: "recipe",
                                            entity: v,
                                          });
                                        }}
                                      >
                                        {v.recipe?.length
                                          ? ingredientLabel(v.recipe.length)
                                          : "Ustaw"}
                                      </button>
                                    ) : v.recipe?.length ? (
                                      <small>{ingredientLabel(v.recipe.length)}</small>
                                    ) : (
                                      <small>Brak</small>
                                    )}
                                  </td>
                                  <td>
                                    {can("admin", "manager") && (
                                      <button
                                        className="icon-button"
                                        aria-label={`Edytuj ${v.name}`}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          open({
                                            kind: "catalog",
                                            catalog: "variants",
                                            entity: v,
                                          });
                                        }}
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
              {page === "admin" && orgForm && (
                <div className="account-page">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void perform("organization/", orgForm, false);
                    }}
                  >
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>Organizacja</h2>
                          <p>
                            Nazwa jest widoczna w menu. Domyślny język dostają
                            nowe konta. Każdy może zmienić swój w ustawieniach.
                          </p>
                        </div>
                      </div>
                      <div className="account-body">
                        <div className="form-grid">
                          <Field label="Nazwa organizacji">
                            <input
                              required
                              value={orgForm.name}
                              onChange={(e) =>
                                setOrgForm({ ...orgForm, name: e.target.value })
                              }
                            />
                          </Field>
                          <Field label="Domyślny język aplikacji">
                            <select
                              value={orgForm.default_language}
                              onChange={(e) =>
                                setOrgForm({
                                  ...orgForm,
                                  default_language:
                                    e.target.value === "en" ? "en" : "pl",
                                })
                              }
                            >
                              <option value="pl">Polski</option>
                              <option value="en">English</option>
                            </select>
                          </Field>
                        </div>
                      </div>
                    </section>
                    <section className="panel">
                      <div className="panel-head">
                        <div>
                          <h2>Motyw kolorów</h2>
                          <p>Kolor przycisków i akcentów w całej aplikacji.</p>
                        </div>
                      </div>
                      <div className="account-body">
                        <div className="theme-choices">
                          {themes.map((theme) => (
                            <button
                              key={theme.id}
                              type="button"
                              aria-pressed={orgForm.theme === theme.id}
                              onClick={() =>
                                setOrgForm({ ...orgForm, theme: theme.id })
                              }
                            >
                              <span
                                className="theme-swatch"
                                style={{ background: theme.color }}
                              />
                              {theme.name}
                            </button>
                          ))}
                        </div>
                        <div className="account-actions">
                          <button className="primary" type="submit" disabled={busy}>
                            Zapisz organizację
                          </button>
                        </div>
                      </div>
                    </section>
                  </form>
                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <h2>Przestrzenie produkcyjne</h2>
                        <p>
                          Każda przestrzeń ma własne zamówienia i produkcję.
                          Nowa startuje pusta. Domyślnej nie wyłączysz.
                        </p>
                      </div>
                    </div>
                    <div className="account-body">
                      <ul className="space-list">
                        {(state?.workspaces || []).map((item) => (
                          <li key={item.id}>
                            <strong>{item.name}</strong>
                            {item.primary && <span className="tag">Domyślna</span>}
                            {!item.active && (
                              <span className="tag">Nieaktywna</span>
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                setSpaceForm({
                                  id: item.id,
                                  name: item.name,
                                  active: item.active,
                                  primary: item.primary,
                                })
                              }
                            >
                              Edytuj
                            </button>
                          </li>
                        ))}
                      </ul>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          void perform(
                            "workspaces/",
                            {
                              ...(spaceForm.id ? { id: spaceForm.id } : {}),
                              name: spaceForm.name,
                              ...(spaceForm.id ? { active: spaceForm.active } : {}),
                            },
                            false,
                          ).then((result) => {
                            if (result)
                              setSpaceForm({
                                name: "",
                                active: true,
                                primary: false,
                              });
                          });
                        }}
                      >
                        <div className="form-grid">
                          <Field label="Nazwa przestrzeni">
                            <input
                              required
                              value={spaceForm.name}
                              onChange={(e) =>
                                setSpaceForm({
                                  ...spaceForm,
                                  name: e.target.value,
                                })
                              }
                            />
                          </Field>
                          {spaceForm.id && !spaceForm.primary && (
                            <label className="check-field">
                              <input
                                type="checkbox"
                                checked={spaceForm.active}
                                onChange={(e) =>
                                  setSpaceForm({
                                    ...spaceForm,
                                    active: e.target.checked,
                                  })
                                }
                              />
                              Przestrzeń aktywna
                            </label>
                          )}
                        </div>
                        <div className="account-actions">
                          {spaceForm.id && (
                            <button
                              type="button"
                              onClick={() =>
                                setSpaceForm({
                                  name: "",
                                  active: true,
                                  primary: false,
                                })
                              }
                            >
                              Anuluj
                            </button>
                          )}
                          <button className="primary" type="submit" disabled={busy}>
                            {spaceForm.id ? "Zapisz przestrzeń" : "Dodaj przestrzeń"}
                          </button>
                        </div>
                      </form>
                    </div>
                  </section>
                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <h2>Użytkownicy i uprawnienia</h2>
                        <p>
                          Dodaj konto i zaznacz role. Jedna osoba może mieć ich
                          kilka. Edycja zmienia login, hasło, role i aktywność.
                        </p>
                      </div>
                    </div>
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
                </div>
              )}
              {page === "stock" && (
                <>
                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <h2>Magazyn</h2>
                        <p>
                          Kliknij surowiec albo produkt, żeby zobaczyć szczegóły.
                          Nazwę, kategorię i dostawcę zmienisz w edycji.
                        </p>
                      </div>
                      {can("manager") && (
                        <div className="task-actions">
                          <button onClick={() => open({ kind: "category" })}>
                            Nowa kategoria
                          </button>
                          <button onClick={() => open({ kind: "stock-product" })}>
                            Nowy produkt
                          </button>
                          <button onClick={() => open({ kind: "supplier" })}>
                            Nowy dostawca
                          </button>
                          <button
                            className="primary"
                            onClick={() => open({ kind: "receipt" })}
                          >
                            Przyjęcie towaru
                          </button>
                        </div>
                      )}
                    </div>
                    <Toolbar
                      query={query}
                      setQuery={setQuery}
                      placeholder="Szukaj pozycji magazynowej…"
                    />
                  </section>
                  {(state.categories || []).map((category) => {
                    const rows = (state.stock || []).filter(
                      (item) =>
                        item.category_id === category.id &&
                        (item.name + item.code)
                          .toLowerCase()
                          .includes(query.toLowerCase()),
                    );
                    if (!rows.length && query) return null;
                    return (
                      <section className="panel" key={category.id}>
                        <div className="panel-head">
                          <div>
                            <h2>{category.name}</h2>
                            <p>
                              {category.system
                                ? "To produkty z katalogu. Wolna ilość jest przydzielana do zamówień, a brak trafia na produkcję."
                                : "Pozycje tej kategorii. Przyjęcie towaru zwiększa stan."}
                            </p>
                          </div>
                        </div>
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Pozycja</th>
                                <th>Stan</th>
                                <th>Dostępne</th>
                                {!category.system && <th>Dostawca</th>}
                                {can("manager") && <th />}
                              </tr>
                            </thead>
                            <tbody>
                              {rows.map((item) => (
                                <tr
                                  key={item.id}
                                  tabIndex={0}
                                  onClick={() =>
                                    setFocus({ kind: "stock", id: item.id })
                                  }
                                  onKeyDown={(e) => {
                                    if (
                                      e.key === "Enter" &&
                                      e.target === e.currentTarget
                                    )
                                      setFocus({ kind: "stock", id: item.id });
                                  }}
                                >
                                  <td>
                                    <strong>{item.name}</strong>
                                    <small>{item.code}</small>
                                  </td>
                                  <td>
                                    <strong>
                                      {fmt.format(Number(item.quantity))}{" "}
                                      {item.unit}
                                    </strong>
                                    {Number(item.reserved) > 0 && (
                                      <small>
                                        zarezerwowane{" "}
                                        {fmt.format(Number(item.reserved))}
                                      </small>
                                    )}
                                  </td>
                                  <td>
                                    <strong>
                                      {fmt.format(Number(item.available))}{" "}
                                      {item.unit}
                                    </strong>
                                  </td>
                                  {!category.system && (
                                    <td>
                                      <strong>{item.supplier_name || "—"}</strong>
                                      {can("manager") && (
                                        <button
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            open({
                                              kind: "supplier-assign",
                                              stockItem: item,
                                            });
                                          }}
                                        >
                                          Dostawca
                                        </button>
                                      )}
                                    </td>
                                  )}
                                  {can("manager") && (
                                    <td>
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          open({
                                            kind: "level",
                                            stockItem: item,
                                          });
                                        }}
                                      >
                                        Ustal stan
                                      </button>
                                    </td>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        {!rows.length && (
                          <Empty
                            title="Pusta kategoria"
                            text="Dodaj produkt albo zmień wyszukiwanie."
                          />
                        )}
                      </section>
                    );
                  })}
                  {!(state.categories || []).length && (
                    <section className="panel">
                      <Empty
                        title="Brak kategorii"
                        text="Dodaj pierwszą kategorię magazynu."
                      />
                    </section>
                  )}
                </>
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
                  {deliveryLabel(detail.delivery)}
                </strong>
              </div>
              <div>
                <small>Priorytet</small>
                <strong>
                  {detail.priority === "urgent" ? "Pilne" : "Standardowy"}
                </strong>
              </div>
              <div>
                <small>E-mail</small>
                <strong>{detail.customer.email || "—"}</strong>
              </div>
              <div>
                <small>Telefon</small>
                <strong>{detail.customer.phone || "—"}</strong>
              </div>
            </div>
            {detail.address && <p className="instruction">{detail.address}</p>}
            {detail.hold_reason && (
              <div className="error">Wstrzymane: {detail.hold_reason}</div>
            )}
            <div className="detail-actions">
              {can("sales", "manager") && detail.status === "draft" && (
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
              {can("sales", "manager") &&
                !["draft", "cancelled", "issued"].includes(detail.status) && (
                <button onClick={() => open({ kind: "amend", order: detail })}>
                  <Pencil size={15} />
                  Zmień zamówienie
                </button>
              )}
              {can("sales", "manager") && detail.status === "completed" && (
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
                    {i.packed} / {i.quantity} wysłane
                  </strong>
                </div>
                <Progress value={i.packed} total={i.quantity} />
                <small>
                  Z magazynu {i.allocated} · wyprodukowane {i.produced} · gotowe
                  do wysyłki {shipReady(i)}
                </small>
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
                      Pobierz · {i.label.filename}
                    </a>
                  )}
                  {i.label &&
                    !i.label.approved &&
                    !["cancelled", "issued"].includes(detail.status) && (
                      <button
                        disabled={busy}
                        onClick={() => {
                          const uncovered = i.allocated + i.produced - i.packed;
                          const settle =
                            i.label!.version > 1 &&
                            uncovered > 0 &&
                            window.confirm(
                              "Zamówienie ma opakowania poprzedniej grafiki. Rozliczyć je do magazynu przy ich grafice? Anuluj zostawia je na zamówieniu: nowa etykieta ich nie zmienia i nie zostaną wysłane jako nowa grafika.",
                            );
                          action(
                            `labels/${i.label!.id}/approve/`,
                            settle ? { settle_previous: true } : {},
                          );
                        }}
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
              ["Dla wysyłki", detail.packing_notes],
              ["Uwagi wewnętrzne", detail.internal_notes],
            ]
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div className="note-block" key={k}>
                  <small>{k}</small>
                  <p>{v}</p>
                </div>
              ))}
            {(detail.shipments.length > 0 || detail.packed > 0) && (
              <>
                <h3>Wysyłki</h3>
                {detail.shipments.length ? (
                  detail.shipments.map((shipment) => (
                    <div className="report-row" key={shipment.id}>
                      <div>
                        <strong>
                          {shipment.number} · {shipment.address}
                        </strong>
                        <p>
                          {shipment.lines
                            .map((line) => `${line.units} × ${line.name}`)
                            .join(", ")}
                        </p>
                        <small>{dt(shipment.created_at)}</small>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="form-help">Brak przesyłek.</p>
                )}
              </>
            )}
            <h3>Raporty wykonania</h3>
            {detail.reports.length ? (
              detail.reports.map((r) => (
                <div
                  className={"report-row " + (r.corrected ? "corrected" : "")}
                  key={r.id}
                >
                  <div>
                    <strong>
                      {r.kind === "production" ? "Produkcja" : "Wysyłka"} ·{" "}
                      {r.product_name}
                    </strong>
                    <p>
                      {r.units} opak.
                      {r.grams !== "0" && r.grams !== "0.000"
                        ? ` · ${kg(r.grams)}`
                        : ""}
                      {r.corrected ? " · SKORYGOWANO" : ""}
                    </p>
                    <small>
                      {r.user} · {dt(r.created_at)}
                      {r.shipment ? ` · ${r.shipment}` : ""}
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
      {(focusedStock || focusedProduct || focusedVariant) && (
        <div className="drawer-backdrop" onClick={() => setFocus(null)}>
          <section
            className="drawer"
            onClick={(e) => e.stopPropagation()}
            aria-label="Szczegóły pozycji"
          >
            <div className="drawer-head">
              <div className="eyebrow">
                {focusedStock
                  ? focusedStock.variant_id
                    ? "SZCZEGÓŁY PRODUKTU"
                    : "SZCZEGÓŁY POZYCJI"
                  : focusedProduct
                    ? "SZCZEGÓŁY SMAKU"
                    : "SZCZEGÓŁY PRODUKTU"}
              </div>
              <button
                className="icon-button"
                aria-label="Zamknij szczegóły"
                onClick={() => setFocus(null)}
              >
                <X />
              </button>
            </div>
            {focusedStock && (
              <>
                <h2>{focusedStock.name}</h2>
                <div className="drawer-customer">
                  {focusedStock.code}
                  <span>
                    {(state?.categories || []).find(
                      (category) => category.id === focusedStock.category_id,
                    )?.name || "Bez kategorii"}
                  </span>
                </div>
                <div className="detail-meta">
                  <div>
                    <small>Stan</small>
                    <strong>
                      {fmt.format(Number(focusedStock.quantity))}{" "}
                      {focusedStock.unit}
                    </strong>
                  </div>
                  <div>
                    <small>Zarezerwowane</small>
                    <strong>
                      {fmt.format(Number(focusedStock.reserved))}{" "}
                      {focusedStock.unit}
                    </strong>
                  </div>
                  <div>
                    <small>Dostępne</small>
                    <strong>
                      {fmt.format(Number(focusedStock.available))}{" "}
                      {focusedStock.unit}
                    </strong>
                  </div>
                  {(stockVariant || stockHistory?.variant) && (
                    <>
                      <div>
                        <small>SKU</small>
                        <strong>
                          {stockVariant?.sku || stockHistory?.variant?.sku}
                        </strong>
                      </div>
                      <div>
                        <small>Smak</small>
                        <strong>
                          {stockHistory?.variant?.product_name ||
                            (state?.products || []).find(
                              (product) => product.id === stockVariant?.product,
                            )?.name ||
                            "—"}
                        </strong>
                      </div>
                      <div>
                        <small>Gramatura</small>
                        <strong>
                          {fmt.format(
                            Number(
                              stockVariant?.weight_g ||
                                stockHistory?.variant?.weight_g,
                            ),
                          )}{" "}
                          g
                        </strong>
                      </div>
                      <div>
                        <small>Opakowanie</small>
                        <strong>
                          {stockVariant?.packaging ||
                            stockHistory?.variant?.packaging}
                        </strong>
                      </div>
                      <div>
                        <small>Etykieta</small>
                        <strong>
                          {(
                            stockVariant?.custom_label ??
                            stockHistory?.variant?.custom_label
                          )
                            ? "Personalizowana"
                            : "Standardowa"}
                        </strong>
                      </div>
                    </>
                  )}
                </div>
                {(stockVariant?.instruction ||
                  stockHistory?.variant?.instruction) && (
                  <p className="instruction">
                    {stockVariant?.instruction ||
                      stockHistory?.variant?.instruction}
                  </p>
                )}
                <div className="detail-actions">
                  {can("manager") && !focusedStock.variant_id && (
                    <button
                      className="primary"
                      onClick={() =>
                        open({ kind: "stock-edit", stockItem: focusedStock })
                      }
                    >
                      Edytuj
                    </button>
                  )}
                  {can("admin", "manager") && stockVariant && (
                    <button
                      className="primary"
                      onClick={() =>
                        open({
                          kind: "catalog",
                          catalog: "variants",
                          entity: stockVariant,
                        })
                      }
                    >
                      Edytuj
                    </button>
                  )}
                  {can("manager") && stockVariant && (
                    <button
                      onClick={() =>
                        open({ kind: "recipe", entity: stockVariant })
                      }
                    >
                      Receptura
                    </button>
                  )}
                  {can("manager") && (
                    <button
                      onClick={() =>
                        open({ kind: "level", stockItem: focusedStock })
                      }
                    >
                      Ustal stan
                    </button>
                  )}
                  {(stockVariant?.product ||
                    stockHistory?.variant?.product_id) && (
                    <button
                      onClick={() =>
                        setFocus({
                          kind: "product",
                          id:
                            stockVariant?.product ||
                            stockHistory?.variant?.product_id ||
                            0,
                        })
                      }
                    >
                      Smak
                    </button>
                  )}
                </div>
                {!focusedStock.variant_id && (
                  <>
                    <h3>Dostawca</h3>
                    {focusedSupplier ? (
                      <>
                        <div className="detail-meta">
                          <div>
                            <small>Nazwa</small>
                            <strong>{focusedSupplier.name}</strong>
                          </div>
                          <div>
                            <small>Osoba kontaktowa</small>
                            <strong>{focusedSupplier.contact || "—"}</strong>
                          </div>
                          <div>
                            <small>E-mail</small>
                            <strong>{focusedSupplier.email || "—"}</strong>
                          </div>
                          <div>
                            <small>Telefon</small>
                            <strong>{focusedSupplier.phone || "—"}</strong>
                          </div>
                        </div>
                        {can("manager") && (
                          <div className="detail-actions">
                            <button
                              onClick={() =>
                                open({
                                  kind: "supplier",
                                  supplier: focusedSupplier,
                                })
                              }
                            >
                              Edytuj dostawcę
                            </button>
                          </div>
                        )}
                      </>
                    ) : (
                      <p className="muted">Brak dostawcy.</p>
                    )}
                    <h3>W recepturach</h3>
                    {stockHistory ? (
                      stockHistory.used_in.length ? (
                        stockHistory.used_in.map((row) => (
                          <div className="detail-item" key={row.variant_id}>
                            <button
                              className="text-button"
                              onClick={() =>
                                setFocus({
                                  kind: "variant",
                                  id: row.variant_id,
                                })
                              }
                            >
                              {row.name}
                            </button>
                            <small>
                              {fmt.format(Number(row.quantity))}{" "}
                              {focusedStock.unit} na opakowanie
                            </small>
                          </div>
                        ))
                      ) : (
                        <p className="muted">
                          Nie jest składnikiem żadnej receptury.
                        </p>
                      )
                    ) : (
                      <p className="muted">Wczytuję receptury.</p>
                    )}
                  </>
                )}
                {stockVariant && (
                  <>
                    <h3>Receptura</h3>
                    {stockVariant.recipe?.length ? (
                      stockVariant.recipe.map((line) => {
                        const material = (state?.stock || []).find(
                          (item) => item.id === line.stock_id,
                        );
                        return (
                          <div className="detail-item" key={line.stock_id}>
                            <button
                              className="text-button"
                              disabled={!material}
                              onClick={() =>
                                material &&
                                setFocus({ kind: "stock", id: material.id })
                              }
                            >
                              {material?.name || "Pozycja magazynowa"}
                            </button>
                            <small>
                              {fmt.format(Number(line.quantity))}{" "}
                              {material?.unit || ""} na opakowanie
                            </small>
                          </div>
                        );
                      })
                    ) : (
                      <p className="muted">
                        Brak receptury. Produkcja nie zużywa surowców.
                      </p>
                    )}
                  </>
                )}
                <h3>
                  <History size={17} /> Ruchy magazynowe
                </h3>
                {stockHistory ? (
                  stockHistory.moves.length ? (
                    <div className="timeline">
                      {stockHistory.moves.map((move) => (
                        <div key={move.id}>
                          <i />
                          <strong>
                            {Number(move.delta) > 0 ? "+" : ""}
                            {fmt.format(Number(move.delta))} {focusedStock.unit}
                          </strong>
                          <small>
                            po ruchu{" "}
                            {fmt.format(Number(move.quantity_after))}{" "}
                            {focusedStock.unit} · {move.user} ·{" "}
                            {dt(move.created_at)}
                          </small>
                          <small>{move.reason}</small>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Brak ruchów magazynowych.</p>
                  )
                ) : historyFailed ? (
                  <p className="muted">Nie udało się wczytać historii.</p>
                ) : (
                  <p className="muted">Wczytuję historię ruchów.</p>
                )}
              </>
            )}
            {focusedProduct && (
              <>
                <h2>{focusedProduct.name}</h2>
                <div className="detail-meta">
                  <div>
                    <small>Kod</small>
                    <strong>{focusedProduct.code}</strong>
                  </div>
                  <div>
                    <small>Status</small>
                    <strong>
                      {focusedProduct.active ? "Aktywny" : "Archiwalny"}
                    </strong>
                  </div>
                  <div>
                    <small>Kolor</small>
                    <strong>{focusedProduct.color}</strong>
                  </div>
                </div>
                {focusedProduct.instruction && (
                  <p className="instruction">{focusedProduct.instruction}</p>
                )}
                <div className="detail-actions">
                  {can("admin", "manager") && (
                    <button
                      className="primary"
                      onClick={() =>
                        open({
                          kind: "catalog",
                          catalog: "products",
                          entity: focusedProduct,
                        })
                      }
                    >
                      Edytuj
                    </button>
                  )}
                </div>
                <h3>Warianty</h3>
                {(state?.variants || []).filter(
                  (variant) => variant.product === focusedProduct.id,
                ).length ? (
                  (state?.variants || [])
                    .filter((variant) => variant.product === focusedProduct.id)
                    .map((variant) => (
                      <div className="detail-item" key={variant.id}>
                        <button
                          className="text-button"
                          onClick={() =>
                            setFocus({ kind: "variant", id: variant.id })
                          }
                        >
                          {variant.name}
                        </button>
                        <small>
                          {variant.sku} · {fmt.format(Number(variant.weight_g))}{" "}
                          g · dostępne{" "}
                          {fmt.format(Number(variant.stock_available || 0))} szt
                        </small>
                      </div>
                    ))
                ) : (
                  <p className="muted">Brak wariantów tego smaku.</p>
                )}
              </>
            )}
            {focusedVariant && (
              <>
                <h2>{focusedVariant.name}</h2>
                <div className="drawer-customer">
                  {focusedVariant.sku}
                  {!focusedVariant.active && <span>Archiwalny</span>}
                </div>
                <div className="detail-meta">
                  <div>
                    <small>Gramatura</small>
                    <strong>
                      {fmt.format(Number(focusedVariant.weight_g))} g
                    </strong>
                  </div>
                  <div>
                    <small>Opakowanie</small>
                    <strong>{focusedVariant.packaging}</strong>
                  </div>
                  <div>
                    <small>Etykieta</small>
                    <strong>
                      {focusedVariant.custom_label
                        ? "Personalizowana"
                        : "Standardowa"}
                    </strong>
                  </div>
                  <div>
                    <small>W magazynie</small>
                    <strong>
                      {fmt.format(Number(focusedVariant.stock_quantity || 0))}{" "}
                      szt
                    </strong>
                  </div>
                  <div>
                    <small>Dostępne</small>
                    <strong>
                      {fmt.format(Number(focusedVariant.stock_available || 0))}{" "}
                      szt
                    </strong>
                  </div>
                  <div>
                    <small>Smak</small>
                    <strong>
                      {(state?.products || []).find(
                        (product) => product.id === focusedVariant.product,
                      )?.name || "—"}
                    </strong>
                  </div>
                </div>
                {focusedVariant.instruction && (
                  <p className="instruction">{focusedVariant.instruction}</p>
                )}
                <div className="detail-actions">
                  {can("admin", "manager") && (
                    <button
                      className="primary"
                      onClick={() =>
                        open({
                          kind: "catalog",
                          catalog: "variants",
                          entity: focusedVariant,
                        })
                      }
                    >
                      Edytuj
                    </button>
                  )}
                  {can("manager") && (
                    <button
                      onClick={() =>
                        open({ kind: "recipe", entity: focusedVariant })
                      }
                    >
                      Receptura
                    </button>
                  )}
                  <button
                    onClick={() =>
                      setFocus({
                        kind: "product",
                        id: focusedVariant.product,
                      })
                    }
                  >
                    Smak
                  </button>
                  {(state?.stock || []).find(
                    (item) => item.variant_id === focusedVariant.id,
                  ) && (
                    <button
                      onClick={() => {
                        const item = (state?.stock || []).find(
                          (row) => row.variant_id === focusedVariant.id,
                        );
                        if (item) setFocus({ kind: "stock", id: item.id });
                      }}
                    >
                      Magazyn
                    </button>
                  )}
                </div>
                <h3>Receptura</h3>
                {focusedVariant.recipe?.length ? (
                  focusedVariant.recipe.map((line) => {
                    const material = (state?.stock || []).find(
                      (item) => item.id === line.stock_id,
                    );
                    return (
                      <div className="detail-item" key={line.stock_id}>
                        <button
                          className="text-button"
                          disabled={!material}
                          onClick={() =>
                            material &&
                            setFocus({ kind: "stock", id: material.id })
                          }
                        >
                          {material?.name || "Pozycja magazynowa"}
                        </button>
                        <small>
                          {fmt.format(Number(line.quantity))} {material?.unit || ""}{" "}
                          na opakowanie
                        </small>
                      </div>
                    );
                  })
                ) : (
                  <p className="muted">
                    Brak receptury. Produkcja nie zużywa surowców.
                  </p>
                )}
              </>
            )}
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
                  if (
                    lines.some(
                      (line) =>
                        line.product_id &&
                        !matchVariant(state.variants, line),
                    )
                  ) {
                    setError(
                      "Nie ma takiego popcornu. Zmień smak, gramaturę albo logo.",
                    );
                    return;
                  }
                  const resolved = lines.flatMap((line, index) => {
                    const variant = matchVariant(state.variants, line);
                    return variant
                      ? [{ variant, quantity: Number(line.quantity), index }]
                      : [];
                  });
                  path = "orders/save/";
                  data = {
                    ...d,
                    id: modal.order?.id,
                    version: modal.order?.version,
                    customer_id: d.customer_id ? Number(d.customer_id) : null,
                    due_at: fromWarsaw(String(d.due_at || "")),
                    items: resolved.map((line) => ({
                      variant_id: line.variant.id,
                      quantity: line.quantity,
                    })),
                    confirm:
                      (e.nativeEvent as SubmitEvent).submitter?.getAttribute(
                        "value",
                      ) === "confirm",
                  };
                  const multipart = new FormData();
                  multipart.append("payload", JSON.stringify(data));
                  resolved.forEach((line, uploadIndex) => {
                    const file = f.get(`label_${line.index}`);
                    if (file instanceof File && file.size)
                      multipart.append(`label_${uploadIndex}`, file);
                  });
                  data = multipart;
                } else if (modal.kind === "report") {
                  const t = modal.task!;
                  path = `tasks/${t.id}/report/`;
                  data = {
                    units: Number(d.units),
                    note: d.note,
                  };
                } else if (modal.kind === "catalog") {
                  path = `catalog/${modal.catalog}/`;
                  data = {
                    ...d,
                    ...(modal.entity ? { id: modal.entity.id } : {}),
                    active: modal.entity ? f.has("active") : true,
                    ...(modal.catalog === "customers"
                      ? {
                          delivery_addresses: JSON.parse(
                            String(d.delivery_addresses || "[]"),
                          ),
                        }
                      : {}),
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
                    restore_mass: false,
                  };
                } else if (modal.kind === "level") {
                  path = `stock/${modal.stockItem!.id}/`;
                  data = { quantity: d.quantity, reason: d.reason };
                } else if (modal.kind === "category") {
                  path = "stock/categories/";
                  data = { name: d.name };
                } else if (modal.kind === "stock-product") {
                  path = "stock/products/";
                  data = {
                    category_id: Number(d.category_id),
                    name: d.name,
                    unit: d.unit,
                    supplier_id: d.supplier_id ? Number(d.supplier_id) : null,
                  };
                } else if (modal.kind === "supplier") {
                  path = modal.supplier
                    ? `suppliers/${modal.supplier.id}/`
                    : "suppliers/";
                  data = {
                    name: d.name,
                    contact: d.contact,
                    email: d.email,
                    phone: d.phone,
                  };
                } else if (modal.kind === "stock-edit") {
                  path = `stock/${modal.stockItem!.id}/edit/`;
                  data = {
                    name: d.name,
                    category_id: Number(d.category_id),
                    unit: d.unit,
                    supplier_id: d.supplier_id ? Number(d.supplier_id) : null,
                  };
                } else if (modal.kind === "supplier-assign") {
                  path = `stock/${modal.stockItem!.id}/supplier/`;
                  data = {
                    supplier_id: d.supplier_id ? Number(d.supplier_id) : null,
                  };
                } else if (modal.kind === "recipe") {
                  path = "recipes/";
                  data = {
                    variant_id: (modal.entity as Variant).id,
                    lines: recipeLines
                      .filter((line) => line.stock_id && line.quantity)
                      .map((line) => ({
                        stock_id: line.stock_id,
                        quantity: String(line.quantity).replace(",", "."),
                      })),
                  };
                } else if (modal.kind === "receipt") {
                  path = "stock/receipt/";
                  data = {
                    stock_id: Number(d.stock_id),
                    quantity: d.quantity,
                    reason: d.reason,
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
                        value={customerId || ""}
                        onChange={(e) => setCustomerId(Number(e.target.value))}
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
                        value={deliveryMethod}
                        onChange={(e) => setDeliveryMethod(e.target.value)}
                      >
                        <option value="courier">Kurier</option>
                        <option value="locker">Paczkomat</option>
                        <option value="pickup">Odbiór osobisty</option>
                        <option value="other">Inny</option>
                      </select>
                    </Field>
                    <Field
                      label={
                        deliveryMethod === "locker"
                          ? "Paczkomat (wymagany)"
                          : deliveryMethod === "courier"
                            ? "Adres dostawy (wymagany dla kuriera)"
                            : "Adres dostawy"
                      }
                      wide
                    >
                      <select
                        name="delivery_address_id"
                        key={customerId}
                        defaultValue={
                          customerId === modal.order?.customer_id
                            ? modal.order.delivery_address_id
                            : ""
                        }
                      >
                        <option value="">Wybierz lokalizację klienta</option>
                        {(
                          state.customers.find((c) => c.id === customerId)
                            ?.delivery_addresses || []
                        ).map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name} · {a.address}
                          </option>
                        ))}
                      </select>
                      <small>
                        {deliveryMethod === "locker"
                          ? "Dodaj paczkomat w adresie klienta: nazwa punktu i lokalizacja."
                          : "Adresy dodasz w edycji klienta. Dla odbioru osobistego wybór jest opcjonalny."}
                      </small>
                    </Field>
                  </div>
                  <div className="form-section-head">
                    <h3>Co produkujemy?</h3>
                    <button
                      type="button"
                      className="text-button"
                      disabled={packWeight == null}
                      onClick={() =>
                        setLines([
                          ...lines,
                          {
                            product_id: 0,
                            weight_g: packWeight || 30,
                            logo: false,
                            quantity: 1,
                          },
                        ])
                      }
                    >
                      <Plus size={14} />
                      Dodaj pozycję
                    </button>
                  </div>
                  <div className="weight-picker" role="group" aria-label="Gramatura">
                    <span>Gramatura</span>
                    {PACK_WEIGHTS.map((grams) => (
                      <button
                        key={grams}
                        type="button"
                        className={packWeight === grams ? "active" : ""}
                        aria-pressed={packWeight === grams}
                        onClick={() => {
                          setPackWeight(grams);
                          setLines((current) =>
                            current.length
                              ? current
                              : [
                                  {
                                    product_id: 0,
                                    weight_g: grams,
                                    logo: false,
                                    quantity: 1,
                                  },
                                ],
                          );
                        }}
                      >
                        {grams} g
                      </button>
                    ))}
                  </div>
                  {!lines.length && (
                    <p className="form-help">
                      Najpierw wybierz gramaturę. Potem pojawią się smak, ilość
                      i opcja popcornu z logo.
                    </p>
                  )}
                  {lines.map((l, index) => {
                    const flavors = state.products.filter(
                      (product) =>
                        (product.active || product.id === l.product_id) &&
                        state.variants.some(
                          (variant) =>
                            variant.product === product.id &&
                            Number(variant.weight_g) === Number(l.weight_g) &&
                            variant.custom_label === l.logo &&
                            (variant.active || product.id === l.product_id),
                        ),
                    );
                    const weights = PACK_WEIGHTS.includes(Number(l.weight_g))
                      ? PACK_WEIGHTS
                      : [...PACK_WEIGHTS, Number(l.weight_g)].sort(
                          (a, b) => a - b,
                        );
                    return (
                      <div className="order-line" key={index}>
                        <select
                          aria-label={`Smak ${index + 1}`}
                          value={l.product_id}
                          onChange={(e) =>
                            setLines(
                              lines.map((row, rowIndex) =>
                                rowIndex === index
                                  ? {
                                      ...row,
                                      product_id: Number(e.target.value),
                                    }
                                  : row,
                              ),
                            )
                          }
                        >
                          <option value="0">
                            {flavors.length
                              ? "Wybierz smak"
                              : "Brak smaku w tej gramaturze"}
                          </option>
                          {flavors.map((product) => (
                            <option key={product.id} value={product.id}>
                              {product.name}
                            </option>
                          ))}
                        </select>
                        <select
                          aria-label={`Gramatura ${index + 1}`}
                          value={l.weight_g}
                          onChange={(e) => {
                            const weight_g = Number(e.target.value);
                            setLines(
                              lines.map((row, rowIndex) => {
                                if (rowIndex !== index) return row;
                                const next = { ...row, weight_g };
                                if (
                                  next.product_id &&
                                  !matchVariant(state.variants, next)
                                )
                                  next.product_id = 0;
                                return next;
                              }),
                            );
                          }}
                        >
                          {weights.map((grams) => (
                            <option key={grams} value={grams}>
                              {grams} g
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
                              lines.map((row, rowIndex) =>
                                rowIndex === index
                                  ? {
                                      ...row,
                                      quantity: e.target.value.replace(
                                        /^0+(?=\d)/,
                                        "",
                                      ),
                                    }
                                  : row,
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
                        <label className="check-field">
                          <input
                            type="checkbox"
                            checked={l.logo}
                            onChange={(e) => {
                              const logo = e.target.checked;
                              setLines(
                                lines.map((row, rowIndex) => {
                                  if (rowIndex !== index) return row;
                                  const next = { ...row, logo };
                                  if (
                                    next.product_id &&
                                    !matchVariant(state.variants, next)
                                  )
                                    next.product_id = 0;
                                  return next;
                                }),
                              );
                            }}
                          />
                          Popcorn z logo
                        </label>
                        {l.logo && (
                          <label className="field wide">
                            <span>
                              Grafika / etykieta dla pozycji {index + 1}
                            </span>
                            <input
                              type="file"
                              name={`label_${index}`}
                              accept=".pdf,.png,.jpg,.jpeg"
                            />
                            <small>
                              PDF, PNG lub JPG do 20 MB. Po zapisaniu zatwierdź
                              grafikę w szczegółach zamówienia.
                            </small>
                          </label>
                        )}
                      </div>
                    );
                  })}
                  <div className="order-total">
                    <span>Łączna liczba opakowań</span>
                    <strong>
                      {fmt.format(
                        lines.reduce((a, l) => a + Number(l.quantity || 0), 0),
                      )}{" "}
                      szt.
                    </strong>
                  </div>
                  <div className="form-grid">
                    <Field label="Uwagi dla produkcji">
                      <textarea
                        name="production_notes"
                        defaultValue={modal.order?.production_notes}
                      />
                    </Field>
                    <Field label="Uwagi dla wysyłki">
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
                    Zamówienie najpierw zabiera wolny popcorn z magazynu. Produkcja
                    robi tylko brakującą liczbę opakowań. Wysyłka oznacza, że
                    paczki już wyjechały. Grafika z logo musi być zatwierdzona,
                    zanim powstaną opakowania.
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
                    <Field
                      label={
                        modal.task!.kind === "production"
                          ? "Wyprodukowane opakowania"
                          : "Wysłane opakowania"
                      }
                    >
                      <input
                        name="units"
                        aria-label={
                          modal.task!.kind === "production"
                            ? "Wyprodukowane opakowania"
                            : "Wysłane opakowania"
                        }
                        type="number"
                        min="1"
                        step="1"
                        max={
                          modal.task!.kind === "production"
                            ? Math.max(1, produceLeft(modal.task!.item))
                            : Math.max(1, shipReady(modal.task!.item))
                        }
                        defaultValue={
                          modal.task!.kind === "production"
                            ? Math.max(1, produceLeft(modal.task!.item))
                            : Math.max(1, shipReady(modal.task!.item))
                        }
                        required
                        autoFocus
                      />
                      <small>
                        {modal.task!.kind === "production"
                          ? "Tylko brakująca liczba. To, co jest w magazynie, nie wraca na produkcję."
                          : "Tyle gotowych opakowań oznaczasz jako wysłane."}
                      </small>
                      {modal.task!.kind === "production" &&
                        (state.variants.find(
                          (variant) =>
                            variant.id === modal.task!.item?.variant_id,
                        )?.recipe.length || 0) > 0 && (
                          <small>
                            Receptura na jedno opakowanie:{" "}
                            {state.variants
                              .find(
                                (variant) =>
                                  variant.id === modal.task!.item?.variant_id,
                              )
                              ?.recipe.map((line) => {
                                const material = state.stock.find(
                                  (item) => item.id === line.stock_id,
                                );
                                return `${material?.name || "składnik"} ${line.quantity} ${material?.unit || ""}`;
                              })
                              .join(", ")}
                            . Stan tych pozycji spadnie automatycznie.
                          </small>
                        )}
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
                      ? "Zgłoś opakowania gotowe po etykiecie, zamknięciu i studzeniu."
                      : modal.task!.address
                        ? "Adres: " + modal.task!.address
                        : "Możesz wysłać tylko opakowania z magazynu albo już wyprodukowane."}
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
                  <h3>Uprawnienia</h3>
                  <p className="form-help">
                    Zaznacz, co ta osoba może robić. Role możesz później zmienić.
                  </p>
                  <div className="role-list">
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
                        <span>
                          <strong>{v}</strong>
                          <small>{roleHints[k]}</small>
                        </span>
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
                        label={`${i.name} (wyprodukowano ${i.produced})`}
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
                    <Field label="Uwagi dla wysyłki">
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
                    {modal.report!.units} opak. Oryginał pozostanie w historii.
                    Cofnięcie wysyłki wraca opakowania do magazynu jako zarezerwowane
                    dla tego zamówienia.
                  </p>
                  <Field label="Przyczyna korekty">
                    <textarea name="reason" required />
                  </Field>
                </>
              )}
              {modal.kind === "category" && (
                <Field label="Nazwa kategorii">
                  <input name="name" required autoFocus maxLength={80} />
                </Field>
              )}
              {modal.kind === "supplier" && (
                <>
                  <Field label="Nazwa dostawcy">
                    <input
                      name="name"
                      required
                      autoFocus
                      maxLength={180}
                      defaultValue={modal.supplier?.name}
                    />
                  </Field>
                  <Field label="Osoba kontaktowa">
                    <input
                      name="contact"
                      maxLength={180}
                      defaultValue={modal.supplier?.contact}
                    />
                  </Field>
                  <Field label="E-mail">
                    <input
                      name="email"
                      type="email"
                      defaultValue={modal.supplier?.email}
                    />
                  </Field>
                  <Field label="Telefon">
                    <input
                      name="phone"
                      maxLength={50}
                      defaultValue={modal.supplier?.phone}
                    />
                  </Field>
                </>
              )}
              {modal.kind === "supplier-assign" && modal.stockItem && (
                <>
                  <p className="form-help">
                    {modal.stockItem.name}. Dostawcę dodajesz przyciskiem Nowy
                    dostawca.
                  </p>
                  <Field label="Dostawca">
                    <select
                      name="supplier_id"
                      defaultValue={modal.stockItem.supplier_id || ""}
                      autoFocus
                    >
                      <option value="">Bez dostawcy</option>
                      {(state?.suppliers || []).map((supplier) => (
                        <option key={supplier.id} value={supplier.id}>
                          {supplier.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </>
              )}
              {modal.kind === "recipe" && (
                <>
                  <p className="form-help">
                    Ilość na jedno opakowanie {(modal.entity as Variant).name}.
                    Przy zgłoszeniu produkcji stan tych pozycji spadnie sam.
                    Pusta receptura nic nie zużywa.
                  </p>
                  <div className="form-section-head">
                    <h3>Składniki</h3>
                    <button
                      type="button"
                      className="text-button"
                      onClick={() =>
                        setRecipeLines([
                          ...recipeLines,
                          { stock_id: 0, quantity: "" },
                        ])
                      }
                    >
                      <Plus size={14} />
                      Dodaj składnik
                    </button>
                  </div>
                  {recipeLines.map((line, index) => {
                    const material = (state?.stock || []).find(
                      (item) => item.id === line.stock_id,
                    );
                    return (
                      <div className="order-line" key={index}>
                        <select
                          aria-label={`Składnik ${index + 1}`}
                          value={line.stock_id}
                          onChange={(e) =>
                            setRecipeLines(
                              recipeLines.map((row, rowIndex) =>
                                rowIndex === index
                                  ? { ...row, stock_id: Number(e.target.value) }
                                  : row,
                              ),
                            )
                          }
                        >
                          <option value="0">Wybierz pozycję magazynową</option>
                          {(state?.stock || [])
                            .filter((item) => !item.variant_id)
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name} ({item.unit})
                              </option>
                            ))}
                        </select>
                        <input
                          aria-label={`Ilość składnika ${index + 1}`}
                          type="number"
                          min="0.001"
                          step={material?.unit === "szt" ? "1" : "0.001"}
                          value={line.quantity}
                          placeholder={material?.unit || "ilość"}
                          onChange={(e) =>
                            setRecipeLines(
                              recipeLines.map((row, rowIndex) =>
                                rowIndex === index
                                  ? { ...row, quantity: e.target.value }
                                  : row,
                              ),
                            )
                          }
                        />
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`Usuń składnik ${index + 1}`}
                          onClick={() =>
                            setRecipeLines(
                              recipeLines.filter(
                                (_, rowIndex) => rowIndex !== index,
                              ),
                            )
                          }
                        >
                          <X size={15} />
                        </button>
                      </div>
                    );
                  })}
                </>
              )}
              {modal.kind === "stock-product" && (
                <>
                  <Field label="Kategoria">
                    <select name="category_id" required defaultValue="">
                      <option value="" disabled>
                        Wybierz kategorię
                      </option>
                      {(state?.categories || [])
                        .filter((category) => !category.system)
                        .map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                  <Field label="Nazwa">
                    <input name="name" required autoFocus maxLength={180} />
                  </Field>
                  <Field label="Jednostka">
                    <select name="unit" defaultValue="szt">
                      <option value="szt">sztuki</option>
                      <option value="kg">kilogramy</option>
                    </select>
                  </Field>
                  <Field label="Dostawca">
                    <select name="supplier_id" defaultValue="">
                      <option value="">Bez dostawcy</option>
                      {(state?.suppliers || []).map((supplier) => (
                        <option key={supplier.id} value={supplier.id}>
                          {supplier.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <p className="form-help">
                    Popcorn, który sprzedajesz, dodajesz w katalogu produktów.
                    Tu dodajesz surowce, opakowania i inne pozycje.
                  </p>
                </>
              )}
              {modal.kind === "stock-edit" && modal.stockItem && (
                <>
                  <Field label="Nazwa">
                    <input
                      name="name"
                      required
                      autoFocus
                      maxLength={180}
                      defaultValue={modal.stockItem.name}
                    />
                  </Field>
                  <Field label="Kategoria">
                    <select
                      name="category_id"
                      required
                      defaultValue={modal.stockItem.category_id || ""}
                    >
                      <option value="" disabled>
                        Wybierz kategorię
                      </option>
                      {(state?.categories || [])
                        .filter((category) => !category.system)
                        .map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                  {Number(modal.stockItem.quantity) === 0 &&
                  Number(modal.stockItem.reserved) === 0 ? (
                    <Field label="Jednostka">
                      <select name="unit" defaultValue={modal.stockItem.unit}>
                        <option value="szt">sztuki</option>
                        <option value="kg">kilogramy</option>
                      </select>
                    </Field>
                  ) : (
                    <Field label="Jednostka">
                      <input
                        name="unit"
                        defaultValue={modal.stockItem.unit}
                        readOnly
                      />
                    </Field>
                  )}
                  <Field label="Dostawca">
                    <select
                      name="supplier_id"
                      defaultValue={modal.stockItem.supplier_id || ""}
                    >
                      <option value="">Bez dostawcy</option>
                      {(state?.suppliers || []).map((supplier) => (
                        <option key={supplier.id} value={supplier.id}>
                          {supplier.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <p className="form-help">
                    Kod {modal.stockItem.code} zostaje bez zmian. Gotowy popcorn
                    edytujesz w katalogu.
                    {Number(modal.stockItem.quantity) !== 0 ||
                    Number(modal.stockItem.reserved) !== 0
                      ? " Jednostkę zmienisz, gdy stan i rezerwacja są zerowe."
                      : ""}
                  </p>
                </>
              )}
              {modal.kind === "receipt" && (
                <>
                  <Field label="Pozycja">
                    <select name="stock_id" required defaultValue="">
                      <option value="" disabled>
                        Wybierz produkt
                      </option>
                      {(state?.categories || []).map((category) => (
                        <optgroup key={category.id} label={category.name}>
                          {(state?.stock || [])
                            .filter((item) => item.category_id === category.id)
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name} ({item.unit})
                              </option>
                            ))}
                        </optgroup>
                      ))}
                    </select>
                  </Field>
                  <Field label="Ilość z dostawy">
                    <input
                      name="quantity"
                      type="number"
                      min="0.001"
                      step="0.001"
                      required
                      autoFocus
                    />
                  </Field>
                  <Field label="Opis dostawy">
                    <textarea
                      name="reason"
                      required
                      placeholder="Na przykład: faktura, dostawca, data"
                    />
                  </Field>
                </>
              )}
              {modal.kind === "level" && modal.stockItem && (
                <>
                  <p className="form-help">
                    {modal.stockItem.name}. Aktualny stan:{" "}
                    {fmt.format(Number(modal.stockItem.quantity))}{" "}
                    {modal.stockItem.unit}.
                  </p>
                  <Field
                    label={
                      modal.stockItem.unit === "kg"
                        ? "Nowy stan (kg)"
                        : "Nowy stan (sztuki)"
                    }
                  >
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step={modal.stockItem.unit === "kg" ? "0.001" : "1"}
                      defaultValue={
                        modal.stockItem.unit === "kg"
                          ? modal.stockItem.quantity
                          : String(Number(modal.stockItem.quantity))
                      }
                      required
                      autoFocus
                    />
                  </Field>
                  <Field label="Powód">
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
            ? "Zgłoś gotowe opakowania"
            : "Oznacz wysyłkę",
        category: "Nowa kategoria",
        supplier: m.supplier ? "Edytuj dostawcę" : "Nowy dostawca",
        "supplier-assign": "Dostawca surowca",
        recipe: "Receptura",
        "stock-product": "Nowy produkt magazynowy",
        "stock-edit": "Edytuj pozycję",
        receipt: "Przyjęcie towaru",
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
        level: "Ustal stan magazynowy",
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
            <Field label="Adres firmy / rozliczeniowy" wide>
              <textarea name="address" defaultValue={c?.address} />
            </Field>
            <DeliveryAddresses initial={c?.delivery_addresses || []} />
          </>
        )}
      </div>
      {entity ? (
        <label className="check-field">
          <input type="checkbox" name="active" defaultChecked={entity.active} />
          Aktywny — dostępny przy nowych zamówieniach
        </label>
      ) : (
        <p className="form-help">Nowy wpis będzie automatycznie aktywny.</p>
      )}
    </>
  );
}

function DeliveryAddresses({
  initial,
}: {
  initial: Customer["delivery_addresses"];
}) {
  const [addresses, setAddresses] = useState(initial);
  return (
    <div className="wide">
      <div className="form-section-head">
        <h3>Adresy dostawy / sklepy</h3>
        <button
          type="button"
          className="text-button"
          onClick={() =>
            setAddresses([
              ...addresses,
              { id: requestKey(), name: "", address: "" },
            ])
          }
        >
          Dodaj adres dostawy
        </button>
      </div>
      <input
        type="hidden"
        name="delivery_addresses"
        value={JSON.stringify(addresses)}
      />
      {addresses.map((a, index) => (
        <div key={a.id} className="form-grid">
          <Field label={`Nazwa lokalizacji ${index + 1}`}>
            <input
              required
              value={a.name}
              onChange={(e) =>
                setAddresses(
                  addresses.map((x) =>
                    x.id === a.id ? { ...x, name: e.target.value } : x,
                  ),
                )
              }
            />
          </Field>
          <Field label={`Adres dostawy ${index + 1}`}>
            <textarea
              required
              value={a.address}
              onChange={(e) =>
                setAddresses(
                  addresses.map((x) =>
                    x.id === a.id ? { ...x, address: e.target.value } : x,
                  ),
                )
              }
            />
          </Field>
          <button
            type="button"
            className="text-button"
            onClick={() => setAddresses(addresses.filter((x) => x.id !== a.id))}
          >
            Usuń lokalizację {index + 1}
          </button>
        </div>
      ))}
    </div>
  );
}
