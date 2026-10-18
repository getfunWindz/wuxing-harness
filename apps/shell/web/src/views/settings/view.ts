/** 设置视图（P2-S3b/S4/S5）：模型与供应商 + 机制调优。
    —— 唯一致命规则：写入走 settings 服务（revision/冲突/写只读凭据）；失败可见。 */
import { h, mount, svgIcon } from "../../render/dom.ts";
import { createFold, type FoldInstance } from "../../render/fold.ts";
import { onLangChange, t, getLang, setLang } from "../i18n.ts";
import type { AboutDto, AssemblyPresetDto, AssemblyPresetListDto, BrowserAllowListDto, BrowserAllowRevokeDto, BrowserIdentityClearDto, BrowserIdentityDto, ConfigDto, CredentialDto, DecisionListDto, DomainPromptsDto, DomainPromptsSaveDto, InteractionPrefsDto, MaintenanceDto, SessionPresetDto, WorkspaceDto } from "../../protocol/generated.ts";
import { isConfigConflict, type SettingsService } from "../../runtime/services/settings.ts";
import { MECHANISM_FIELDS, SETTINGS_SECTIONS, deriveFields, fieldDesc, fieldSourceKey, providerCredentialRef, realShapeCredentialRefs, type FieldSpecLike } from "./model.ts";
import { ICON_CLOSE } from "../icons.ts";
import { DOCK_VIEW_IDS, loadDockViews, setDockViews } from "../dock.ts";
interface ProviderModel { id: string; display_name?: string }
interface ProviderEntry {
  type?: string;
  base_url?: string;
  credential_ref?: string;
  display_name?: string;
  models?: ProviderModel[];
}
interface CatalogEntry {
  id: string; name: string; base_url: string; type: string;
  env?: string; hosts?: string[]; docs?: string;
}
interface ProviderDraft {
  type: string;
  key: string;
  base_url: string;
  display_name: string;
  credential_ref?: string;
  matched: string | null;
  nameTouched: boolean;
  models: ProviderModel[];
}
interface ModelOption { value: string; label: string }

export interface MaintenancePort {
  maintenance(wsId?: string): Promise<MaintenanceDto>;
  maintenanceClean(target: string, wsId?: string): Promise<{ ok: boolean; removed: readonly string[] }>;
  browserAllow(): Promise<BrowserAllowListDto>;
  browserAllowRevoke(address: string, fingerprint: string,
    kind?: string): Promise<BrowserAllowRevokeDto>;
  browserIdentity(wsId?: string): Promise<BrowserIdentityDto>;
  browserIdentityClear(key: string): Promise<BrowserIdentityClearDto>;
  domainPrompts(wsId?: string): Promise<DomainPromptsDto>;
  domainPromptsSave(body: {
    scope: "user" | "workspace";
    ws?: string;
    values: Record<string, { notes?: string; addendum?: string }>;
  }): Promise<DomainPromptsSaveDto>;
  interaction(wsId?: string): Promise<InteractionPrefsDto>;
  interactionSave(body: {
    scope: "user" | "workspace";
    ws?: string;
    values: Record<string, unknown>;
  }): Promise<InteractionPrefsDto>;
  decisions(wsId?: string): Promise<DecisionListDto>;
}

/** M7 C1（MG-15）：关于与诊断端口（只读）。 */
export interface AboutPort {
  about(): Promise<AboutDto>;
}

/** M7 C2（MG-16）：工作区设置端口（当前工作区 auto_confirm）。 */
export interface WorkspacePort {
  list(): readonly WorkspaceDto[];
  setAutoConfirm(id: string, autoConfirm: boolean): Promise<void>;
}

/** E2-UI：装配面端口（预设清单/解析态 + 会话绑定；写经服务总线，失败全局可见）。 */
export interface AssemblyPort {
  /** 目标会话名（活动会话或惰性待定名——与模式选择器同口径）。 */
  target(): string;
  presets(): Promise<AssemblyPresetListDto>;
  session(): Promise<SessionPresetDto>;
  setSession(name: string): Promise<SessionPresetDto>;
}

export interface SettingsViewDeps {
  settings: SettingsService;
  maintenance: MaintenancePort;
  activeWorkspaceId: () => string | null;
  /** 悬浮任务卡显示开关（设置中心可重开） */
  floatCardEnabled: () => boolean;
  onFloatCardChange(enabled: boolean): void;
  /** 界面主题切换（引擎配置双写后即时应用） */
  onUiThemeChange(theme: string): void;
  about: AboutPort;
  workspaces: WorkspacePort;
  assembly: AssemblyPort;
}
export interface SettingsView {
  open(): Promise<void>;
  close(): void;
}

const emptyDraft = (entry: ProviderEntry | undefined): ProviderDraft => ({
  type: entry?.type ?? "openai",
  key: "",
  base_url: entry?.base_url ?? "",
  display_name: entry?.display_name ?? "",
  ...(typeof entry?.credential_ref === "string" ? { credential_ref: entry.credential_ref } : {}),
  matched: null,
  nameTouched: false,
  models: Array.isArray(entry?.models) ? entry.models.map((m) => ({ ...m })) : [],
});

function hostOf(url: string): string {
  const m = /^https?:\/\/([^/:?#]+)/i.exec(url.trim());
  return m?.[1]?.toLowerCase() ?? "";
}

function slugId(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
}

function keyFailure(value: string): string {
  const v = value.trim();
  if (v === "") return "";
  if (!/^[\x21-\x7E]+$/.test(v)) return t("settings.err.keyChars");
  if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(v)) return t("settings.err.keyEnvLine");
  return "";
}

export function createSettingsView(host: HTMLElement, deps: SettingsViewDeps): SettingsView {
  const overlay = h("div", { class: "settings-overlay",
    attrs: { hidden: "hidden", role: "dialog", "aria-modal": "true",
             "aria-label": t("settings.title") } });
  // U5（2026-09-28）：键盘可达性——初始聚焦 + 焦点归还 + Tab 陷阱（模态语义）
  // 注意：存 data-st 选择器而非元素引用——主界面重渲染会替换节点（引用失效）
  let lastFocusedSelector: string | null = null;
  overlay.addEventListener("keydown", (ev) => {
    if (ev.key !== "Tab") return;
    const focusables = [...overlay.querySelectorAll<HTMLElement>(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex=\"-1\"])",
    )].filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);
    if (focusables.length === 0) return;
    const first = focusables[0]!;
    const last = focusables[focusables.length - 1]!;
    const active = document.activeElement;
    if (ev.shiftKey && (active === first || !overlay.contains(active))) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && (active === last || !overlay.contains(active))) {
      ev.preventDefault();
      first.focus();
    }
  });
  const card = h("div", { class: "settings-card" });
  overlay.appendChild(card);
  host.appendChild(overlay);
  onLangChange(() => {
    if (open) render();
  });

  let open = false;
  let section = "model";
  let config: ConfigDto | null = null;
  let schema: readonly FieldSpecLike[] = [];
  let catalog: CatalogEntry[] = [];
  let statuses: Record<string, CredentialDto> = {};
  let expanded: string | null = null;
  let drafts: Record<string, ProviderDraft> = {};
  let picker: { id: string; models: ProviderModel[]; query: string; selected: Record<string, boolean> } | null = null;
  let confirmDel: string | null = null;
  /** 当前渲染周期的 provider 折叠实例表（互斥收起用；重渲染即重建）。 */
  const foldInstances = new Map<string, FoldInstance>();
  let busy = false;
  let error: Record<string, string> = {};
  let conflict = false;
  let notice = "";
  let dockHint = "";
  let searchQuery = "";
  let maint: MaintenanceDto | null = null;
  let maintBusy = false;
  let maintError = "";
  let maintNotice = "";
  let maintConfirm: string | null = null;
  // O2-2 P3：浏览器允许条目（回环动态授权运维）
  let allowEntries: BrowserAllowListDto["entries"] | null = null;
  let allowBusy = false;
  let allowError = "";
  let allowNotice = "";
  let allowConfirm: string | null = null;
  // O2-2 §11.5-①：浏览器身份（memory/persist + 持久条目清除）
  let identityData: BrowserIdentityDto | null = null;
  let storagePathDraft = "";
  let identityBusy = false;
  let identityError = "";
  let identityNotice = "";
  let identityConfirm: string | null = null;
  // 重大优化清单 #3：域提示词（设置「域提示词」分区）
  let promptData: DomainPromptsDto | null = null;
  let promptScope: "user" | "workspace" = "user";
  let promptBusy = false;
  let promptError = "";
  let promptNotice = "";
  let promptDrafts: Record<string, { notes: string; addendum: string }> = {};
  let interactionData: InteractionPrefsDto | null = null;
  let interactionScope: "user" | "workspace" = "user";
  let interactionBusy = false;
  let interactionError = "";
  let interactionNotice = "";
  let interactionDraft: Record<string, unknown> = {};
  let decisionData: DecisionListDto | null = null;
  let decisionsBusy = false;
  let decisionsError = "";
  let about: AboutDto | null = null;
  let aboutBusy = false;
  let aboutError = "";
  let aboutNotice = "";
  let assemblyPresets: AssemblyPresetDto[] | null = null;
  let assemblySession: SessionPresetDto | null = null;
  let assemblyBusy = false;
  let assemblyError = "";
  let assemblyNotice = "";
  let wsBusy = false;
  let wsNotice = "";
  let wsError = "";

  const providers = (): Record<string, ProviderEntry> =>
    (config?.values.providers as Record<string, ProviderEntry> | undefined) ?? {};
  const revision = (): string => config?.revision ?? "";

  const refOf = (id: string, entry: ProviderEntry): string =>
    providerCredentialRef(id, entry);

  const draftOf = (id: string): ProviderDraft => {
    if (!drafts[id]) drafts[id] = emptyDraft(providers()[id]);
    return drafts[id]!;
  };

  const modelOptions = (): ModelOption[] => {
    const out: ModelOption[] = [];
    for (const [pid, entry] of Object.entries(providers())) {
      for (const m of entry.models ?? []) {
        out.push({ value: `${pid}/${m.id}`, label: `${entry.display_name || pid} · ${m.id}` });
      }
    }
    return out;
  };

  const fail = (id: string, message: string): void => {
    if (message) error[id] = message; else delete error[id];
  };

  const describeError = (err: unknown): { message: string; conflict: boolean } => {
    if (isConfigConflict(err)) {
      return { message: t("settings.conflict"), conflict: true };
    }
    return { message: err instanceof Error ? err.message : String(err), conflict: false };
  };

  async function refresh(): Promise<void> {
    config = await deps.settings.readConfig();
    await loadStatuses();
    render();
  }

  async function loadStatuses(): Promise<void> {
    const refs = new Set<string>();
    for (const [pid, entry] of Object.entries(providers())) refs.add(refOf(pid, entry));
    // 真实形状化凭据状态（设置提示用——与引擎解析同口径）
    for (const ref of realShapeCredentialRefs(config?.values)) refs.add(ref);
    await Promise.all([...refs].map(async (ref) => {
      try {
        statuses[ref] = await deps.settings.credentialGet(ref);
      } catch (err) {
        void err; // 状态未确认——保持中性（不冒充已配置）
      }
    }));
  }

  /* ---------- 渲染 ---------- */

  function render(): void {
    mount(card,
      h("div", { class: "st-nav" },
        h("div", { class: "st-nav-title", text: t("settings.nav.group") }),
        ...SETTINGS_SECTIONS.map((s) =>
          h("button", {
            class: s.id === section ? "st-nav-item on" : "st-nav-item",
            attrs: { type: "button", "data-st": `nav:${s.id}` },
            text: t(s.titleKey),
            onClick: () => { section = s.id; render(); },
          }))),
      h("div", { class: "st-main" },
        h("div", { class: "st-head" },
          h("div", { class: "st-title", text: t("settings.title") }),
          h("input", {
            class: "st-search st-input",
            attrs: { type: "search", "data-st": "st-search", id: "st-search", name: "settings-search",
                     placeholder: t("settings.search"), spellcheck: "false" },
            value: searchQuery,
            onInput: (ev: Event) => { searchQuery = (ev.target as HTMLInputElement).value; render(); },
          }),
          h("button", {
            class: "st-close", attrs: { type: "button", "data-st": "close" },
            onClick: () => { close(); },
          }, svgIcon(ICON_CLOSE))),
        h("div", { class: "st-body" },
          notice !== "" ? h("div", { class: "st-notice", text: notice }) : null,
          ...bodyFor())),
    );
  }

  function bodyFor(): HTMLElement[] {
    if (section === "model") return modelSection();
    if (section === "modes") return modesSection();
    if (section === "assembly") return assemblySection();
    if (section === "prompts") return promptsSection();
    if (section === "interaction") return interactionSection();
    if (section === "decisions") return decisionsSection();
    if (section === "mechanism") return mechanismSection();
    if (section === "data") return dataSection();
    if (section === "workspace") return workspaceSection();
    if (section === "about") return aboutSection();
    return appearanceSection();
  }

  /* ---------- 数据与维护（B3：旧壳 maint 分区分区迁移——GET /api/v1/maintenance） ---------- */

  function loadMaintenance(): void {
    maintBusy = true;
    maintError = "";
    render();
    const wsId = deps.activeWorkspaceId();
    void deps.maintenance.maintenance(wsId ?? undefined).then(
      (dto) => {
        maint = dto;
        maintBusy = false;
        render();
      },
      (err: unknown) => {
        maintBusy = false;
        maintError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function runClean(target: string): void {
    maintConfirm = null;
    maintBusy = true;
    maintNotice = "";
    render();
    const wsId = deps.activeWorkspaceId();
    void deps.maintenance.maintenanceClean(target, wsId ?? undefined).then(
      () => {
        maintBusy = false;
        maint = null; // 清理后重新取数（删除计数即时反映）
        loadMaintenance();
      },
      (err: unknown) => {
        maintBusy = false;
        maintError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function fmtBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  /* ---------- O2-2 P3：浏览器允许条目（GET /api/v1/browser/allow） ---------- */

  function loadBrowserAllow(): void {
    allowBusy = true;
    allowError = "";
    render();
    void deps.maintenance.browserAllow().then(
      (dto) => {
        allowEntries = [...dto.entries];
        allowBusy = false;
        render();
      },
      (err: unknown) => {
        allowBusy = false;
        allowError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function revokeBrowserAllow(address: string, fingerprint: string,
    kind = "loopback"): void {
    allowConfirm = null;
    allowBusy = true;
    allowNotice = "";
    render();
    void deps.maintenance.browserAllowRevoke(address, fingerprint, kind).then(
      (dto) => {
        allowBusy = false;
        allowNotice = t("settings.browserAllow.revoked", { n: dto.removed });
        loadBrowserAllow(); // 撤销后重新取数（列表即时反映）
      },
      (err: unknown) => {
        allowBusy = false;
        allowError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  /* ---------- O2-2 §11.5-①：浏览器身份（GET/POST /api/v1/browser/identity） ---------- */

  function loadBrowserIdentity(): void {
    identityBusy = true;
    identityError = "";
    render();
    void deps.maintenance.browserIdentity(deps.activeWorkspaceId() ?? undefined).then(
      (dto) => {
        identityData = dto;
        storagePathDraft = dto.storage_state?.path ?? storagePathDraft;
        identityBusy = false;
        render();
      },
      (err: unknown) => {
        identityBusy = false;
        identityError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function changeIdentityMode(mode: string): void {
    void writeValues({ browser_identity_mode: mode }, {}).then(() => {
      loadBrowserIdentity(); // 写后重取（mode 生效值）
    });
  }

  function saveStoragePath(): void {
    void writeValues({ browser_storage_state_path: storagePathDraft.trim() }, {}).then(() => {
      loadBrowserIdentity(); // 写后重取（摘要/计数刷新）
    });
  }

  function clearBrowserIdentity(key: string): void {
    identityConfirm = null;
    identityBusy = true;
    identityError = "";
    identityNotice = "";
    render();
    void deps.maintenance.browserIdentityClear(key).then(
      () => {
        identityBusy = false;
        identityNotice = t("settings.browserIdentity.cleared");
        loadBrowserIdentity(); // 复读注册表（列表即时反映）
      },
      (err: unknown) => {
        identityBusy = false;
        identityError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function maintRow(label: string, hint: string, control: HTMLElement | null): HTMLElement {
    return h("div", { class: "st-field" },
      h("div", { class: "st-field-main" },
        h("div", { class: "st-label", text: label }),
        h("div", { class: "st-hint", text: hint })),
      control === null ? null : h("div", { class: "st-control" }, control));
  }

  /* ---------- M7 C1（MG-15）：关于与诊断 ---------- */

  function loadAbout(): void {
    aboutBusy = true;
    aboutError = "";
    render();
    void deps.about.about().then(
      (dto) => { about = dto; aboutBusy = false; render(); },
      (err: unknown) => {
        aboutBusy = false;
        aboutError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  async function copyAbout(): Promise<void> {
    if (about === null) return;
    const text = [
      `WUXING shell ${about.shell_version} · API v${about.api_version}`,
      `python: ${about.python}`,
      `platform: ${about.platform}`,
      `data_dir: ${about.data_dir}`,
      `log_dir: ${about.log_dir}`,
      `workspaces: ${about.workspace_count}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      aboutNotice = t("settings.about.copied");
    } catch (err) {
      aboutNotice = err instanceof Error ? err.message : String(err);
    }
    render();
  }

  function aboutSection(): HTMLElement[] {
    if (about === null && !aboutBusy && aboutError === "") {
      queueMicrotask(() => { loadAbout(); }); // 首进触发取数（异步，不阻塞本次渲染）
    }
    const out: HTMLElement[] = [h("div", { class: "st-note", text: t("settings.about.note") })];
    if (aboutBusy && about === null) out.push(h("div", { class: "st-hint", text: t("settings.about.loading") }));
    if (aboutError !== "") out.push(h("div", { class: "st-err", text: t("settings.about.failed", { msg: aboutError }) }));
    if (aboutNotice !== "") out.push(h("div", { class: "st-notice", text: aboutNotice }));
    if (about !== null) {
      out.push(maintRow(t("settings.about.shellVersion"), `${about.shell_version} · API v${about.api_version}`, null));
      out.push(maintRow(t("settings.about.python"), about.python, null));
      out.push(maintRow(t("settings.about.platform"), about.platform, null));
      out.push(maintRow(t("settings.about.dataDir"), about.data_dir, null));
      out.push(maintRow(t("settings.about.logDir"), about.log_dir, null));
      out.push(maintRow(t("settings.about.workspaces"), String(about.workspace_count), null));
      out.push(h("div", { class: "st-note", text: t("settings.about.assemblies") }));
      if (about.assemblies.length === 0) {
        out.push(h("div", { class: "st-hint", text: t("settings.about.assemblyNone") }));
      }
      for (const a of about.assemblies) {
        out.push(maintRow(a.id, a.path, null));
        if (a.degraded.length > 0) {
          const list = a.degraded.map((d) => `[${d.component}/${d.name}] ${d.reason}`).join("；");
          out.push(h("div", { class: "st-err", text: t("settings.about.assemblyDegraded", { list }) }));
        }
      }
      out.push(h("div", { class: "st-row" },
        h("button", {
          class: "st-btn ghost", attrs: { type: "button", "data-st": "about-copy" },
          text: t("settings.about.copy"),
          onClick: () => { void copyAbout(); },
        })));
    }
    return out;
  }

  /* ---------- E2-UI：装配（预设清单 + 会话绑定 + 全局默认） ---------- */

  function loadAssembly(): void {
    assemblyBusy = true;
    assemblyError = "";
    render();
    void Promise.all([deps.assembly.presets(), deps.assembly.session()]).then(
      ([list, session]) => {
        assemblyPresets = [...list.presets];
        assemblySession = session;
        assemblyBusy = false;
        render();
      },
      (err: unknown) => {
        assemblyBusy = false;
        assemblyError = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function setSessionBinding(name: string): void {
    if (assemblyBusy) return;
    assemblyBusy = true;
    assemblyNotice = "";
    render();
    void deps.assembly.setSession(name).then(
      (dto) => {
        assemblySession = dto;
        assemblyBusy = false;
        assemblyNotice = name === ""
          ? t("settings.assembly.boundDefault")
          : t("settings.assembly.bound", { name });
        render();
      },
      (err: unknown) => {
        assemblyBusy = false;
        assemblyNotice = err instanceof Error ? err.message : String(err);
        render();
      },
    );
  }

  function assemblySection(): HTMLElement[] {
    if (assemblyPresets === null && !assemblyBusy && assemblyError === "") {
      queueMicrotask(() => { loadAssembly(); }); // 首进触发取数（异步，不阻塞本次渲染）
    }
    const out: HTMLElement[] = [
      h("div", { class: "st-note", attrs: { "data-st": "settings-assembly" },
                 text: t("settings.assembly.note") }),
    ];
    if (assemblyBusy && assemblyPresets === null) {
      out.push(h("div", { class: "st-hint", text: t("settings.assembly.loading") }));
    }
    if (assemblyError !== "") {
      out.push(h("div", { class: "st-err",
                          text: t("settings.assembly.failed", { msg: assemblyError }) }));
    }
    if (assemblyNotice !== "") {
      out.push(h("div", { class: "st-notice", text: assemblyNotice }));
    }
    const presets = assemblyPresets ?? [];
    const names = presets.map((p) => p.name);
    // 会话绑定（目标会话 = 活动会话或待定新会话名；写后服务端 reload 引擎）
    const bound = assemblySession?.name ?? "";
    out.push(maintRow(t("settings.assembly.session"),
      t("settings.assembly.sessionHint", { session: deps.assembly.target() }),
      h("select", {
        class: "st-input st-narrow",
        attrs: { "data-st": "assembly-session",
                 id: "assembly-session", name: "assembly-session",
                 ...(assemblyBusy ? { disabled: "disabled" } : {}) },
        onChange: (ev: Event) => {
          setSessionBinding((ev.target as HTMLSelectElement).value);
        },
      },
        h("option", {
          attrs: { value: "", ...(bound === "" ? { selected: "selected" } : {}) },
          text: t("settings.assembly.followDefault"),
        }),
        ...names.map((name) => h("option", {
          attrs: { value: name, ...(name === bound ? { selected: "selected" } : {}) },
          text: name,
        })))));
    // 全局默认（config assembly_preset——用户级；未知值以临时项保显）
    const fallback = String(config?.values.assembly_preset ?? "standard");
    out.push(maintRow(t("settings.assembly.default"),
      t("settings.assembly.defaultHint"),
      h("select", {
        class: "st-input st-narrow",
        attrs: { "data-st": "assembly-default",
                 id: "assembly-default", name: "assembly-default",
                 ...(busy ? { disabled: "disabled" } : {}) },
        onChange: (ev: Event) => {
          void writeValues({ assembly_preset: (ev.target as HTMLSelectElement).value },
                           { replace: ["assembly_preset"] });
        },
      },
        ...(names.includes(fallback)
          ? []
          : [h("option", { attrs: { value: fallback }, text: fallback })]),
        ...names.map((name) => h("option", {
          attrs: { value: name, ...(name === fallback ? { selected: "selected" } : {}) },
          text: name,
        })))));
    // 清单（描述/继承链/指纹；损坏带原因）
    out.push(h("div", { class: "st-note", text: t("settings.assembly.list") }));
    if (presets.length === 0 && !assemblyBusy && assemblyError === "") {
      out.push(h("div", { class: "st-hint", text: t("settings.assembly.empty") }));
    }
    for (const p of presets) {
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label" },
            h("span", { text: p.name }),
            p.builtin
              ? h("span", { class: "st-source", text: t("settings.assembly.builtin") })
              : null,
            p.error !== ""
              ? h("span", { class: "st-source", text: t("settings.assembly.broken") })
              : null),
          h("div", { class: "st-hint", text: p.description }),
          p.error !== ""
            ? h("div", { class: "st-err", attrs: { "data-st": `assembly-err:${p.name}` },
                         text: p.error })
            : h("div", {
                class: "st-hint dim",
                text: `${t("settings.assembly.chain")}：${p.chain.join(" → ")}`
                  + ` · ${t("settings.assembly.hash")}：${p.hash}`,
              }))));
    }
    return out;
  }

  /* ---------- M7 C2（MG-16）：工作区设置（当前工作区） ---------- */

  function workspaceSection(): HTMLElement[] {
    const id = deps.activeWorkspaceId();
    const ws = deps.workspaces.list().find((w) => w.id === id) ?? null;
    const out: HTMLElement[] = [h("div", { class: "st-note", text: t("settings.ws.note") })];
    if (ws === null) {
      out.push(h("div", { class: "st-hint", text: t("settings.ws.none") }));
      return out;
    }
    out.push(maintRow(t("settings.ws.name"), ws.name, null));
    out.push(maintRow(t("settings.ws.path"), ws.path, null));
    out.push(maintRow(t("settings.ws.autoConfirm"),
      ws.auto_confirm ? t("settings.ws.stateOn") : t("settings.ws.stateOff"),
      h("button", {
        class: "st-btn ghost",
        attrs: { type: "button", "data-st": "ws-auto-confirm", ...(wsBusy ? { disabled: "disabled" } : {}) },
        text: ws.auto_confirm ? t("settings.ws.disable") : t("settings.ws.enable"),
        onClick: () => { void toggleAutoConfirm(ws.id, !ws.auto_confirm); },
      })));
    if (wsNotice !== "") out.push(h("div", { class: "st-notice", text: wsNotice }));
    if (wsError !== "") out.push(h("div", { class: "st-err", text: wsError }));
    return out;
  }

  async function toggleAutoConfirm(id: string, flag: boolean): Promise<void> {
    wsBusy = true;
    wsError = "";
    wsNotice = "";
    render();
    try {
      await deps.workspaces.setAutoConfirm(id, flag);
      wsNotice = t("settings.ws.updated");
    } catch (err) {
      wsError = err instanceof Error ? err.message : String(err);
    }
    wsBusy = false;
    render();
  }

  /* ---------- 重大优化清单 #3：域提示词（GET/POST /api/v1/prompts/domains） ---------- */

  function primePromptDrafts(dto: DomainPromptsDto): void {
    promptDrafts = {};
    for (const e of dto.entries) {
      promptDrafts[e.domain] = promptScope === "workspace"
        ? { notes: e.notes_workspace, addendum: e.addendum_workspace }
        : { notes: e.notes_user, addendum: e.addendum_user };
    }
  }

  function loadPrompts(): void {
    promptBusy = true;
    promptError = "";
    render();
    const wsId = deps.activeWorkspaceId() ?? undefined;
    void deps.maintenance.domainPrompts(wsId).then(
      (dto) => {
        promptData = dto;
        primePromptDrafts(dto);
        promptBusy = false;
        render();
      },
      (err: unknown) => {
        promptBusy = false;
        promptError = err instanceof Error ? err.message : String(err);
        render();
      });
  }

  function savePrompts(): void {
    if (promptData === null) return;
    const wsId = deps.activeWorkspaceId();
    if (promptScope === "workspace" && wsId === null) {
      promptError = t("settings.prompts.noWorkspace");
      render();
      return;
    }
    const values: Record<string, { notes: string; addendum: string }> = {};
    for (const e of promptData.entries) {
      const d = promptDrafts[e.domain] ?? { notes: "", addendum: "" };
      values[e.domain] = { notes: d.notes, addendum: d.addendum };
    }
    promptBusy = true;
    promptError = "";
    promptNotice = "";
    render();
    void deps.maintenance.domainPromptsSave({
      scope: promptScope,
      ...(promptScope === "workspace" && wsId !== null ? { ws: wsId } : {}),
      values,
    }).then(
      (dto) => {
        promptData = dto;
        promptNotice = t("settings.prompts.saved");
        promptBusy = false;
        render();
      },
      (err: unknown) => {
        promptBusy = false;
        promptError = err instanceof Error ? err.message : String(err);
        render();
      });
  }

  function promptSourceLabel(source: string): string {
    if (source === "user") return t("settings.field.sourceUser");
    if (source === "workspace") return t("settings.field.sourceWorkspace");
    if (source === "default") return t("settings.field.sourceDefault");
    return t("settings.prompts.sourceNone");
  }

  function promptTextarea(domain: string, key: "notes" | "addendum"): HTMLElement {
    return h("textarea", {
      class: "st-input",
      attrs: {
        rows: "3", spellcheck: "false",
        "data-st": `prompt-${key}:${domain}`,
      },
      value: promptDrafts[domain]?.[key] ?? "",
      onInput: (ev: Event) => {
        const el = ev.target as HTMLTextAreaElement;
        promptDrafts[domain] = {
          ...(promptDrafts[domain] ?? { notes: "", addendum: "" }),
          [key]: el.value,
        };
      },
    });
  }

  /* ---------- #2 T-5：决策历史（GET .../decisions，只读） ---------- */

  function loadDecisions(): void {
    decisionsBusy = true;
    decisionsError = "";
    render();
    const wsId = deps.activeWorkspaceId() ?? undefined;
    if (wsId === undefined) {
      decisionsBusy = false;
      render();
      return;
    }
    void deps.maintenance.decisions(wsId).then(
      (dto) => { decisionData = dto; decisionsBusy = false; render(); },
      (err: unknown) => {
        decisionsBusy = false;
        decisionsError = err instanceof Error ? err.message : String(err);
        render();
      });
  }

  function decisionKindLabel(kind: string): string {
    const key = `settings.decisions.kind.${kind}`;
    const label = t(key);
    return label === key ? kind : label;   // 未知回退原文（不造假）
  }

  function decisionStatusLabel(status: string): string {
    const key = `settings.decisions.status.${status}`;
    const label = t(key);
    return label === key ? status : label;
  }

  function decisionsSection(): HTMLElement[] {
    const wsId = deps.activeWorkspaceId();
    if (wsId === null) {
      return [h("div", { class: "st-note",
                          text: t("settings.decisions.noWorkspace") })];
    }
    if (decisionData === null && !decisionsBusy && decisionsError === "") {
      queueMicrotask(() => { loadDecisions(); }); // 首进触发取数
    }
    const out: HTMLElement[] = [
      h("div", { class: "st-note", text: t("settings.decisions.hint") }),
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-hint",
                      text: decisionsBusy ? t("settings.maint.loading") : "" })),
        h("div", { class: "st-control" },
          h("button", {
            class: "st-btn",
            attrs: { type: "button", "data-st": "decisions-refresh" },
            text: t("settings.decisions.refresh"),
            onClick: () => { loadDecisions(); },
          }))),
    ];
    if (decisionsError !== "") {
      out.push(h("div", { class: "st-err",
                           text: t("settings.decisions.failed", { msg: decisionsError }) }));
    }
    if (decisionData !== null) {
      for (const p of decisionData.problems) {
        out.push(h("div", { class: "st-err",
                             text: t("settings.decisions.problems", { msg: p }) }));
      }
      if (decisionData.entries.length === 0) {
        out.push(h("div", { class: "st-hint", text: t("settings.decisions.empty") }));
      }
      for (const e of decisionData.entries) {
        const when = Number.isFinite(e.ts) && e.ts > 0
          ? new Date(e.ts * 1000).toLocaleString() : "";
        out.push(h("div", { class: "st-field" },
          h("div", { class: "st-field-main" },
            h("div", { class: "st-label",
                        text: `${decisionKindLabel(e.kind)} · ` +
                              `${decisionStatusLabel(e.status)} · ${e.object}` }),
            h("div", { class: "st-hint", text: e.reason || "" }),
            h("div", { class: "st-hint dim", text: when })),
          h("div", { class: "st-control" })));
      }
    }
    return out;
  }

  /* ---------- #2 Phase 1.5：交互偏好（GET/POST /api/v1/interaction） ---------- */

  function primeInteractionDraft(): void {
    interactionDraft = {};
    if (interactionData !== null) {
      const src = interactionScope === "workspace"
        ? interactionData.workspace : interactionData.user;
      interactionDraft = { ...src };
    }
  }

  function loadInteraction(): void {
    interactionBusy = true;
    interactionError = "";
    render();
    const wsId = deps.activeWorkspaceId() ?? undefined;
    void deps.maintenance.interaction(wsId).then(
      (dto) => {
        interactionData = dto;
        primeInteractionDraft();
        interactionBusy = false;
        render();
      },
      (err: unknown) => {
        interactionBusy = false;
        interactionError = err instanceof Error ? err.message : String(err);
        render();
      });
  }

  function saveInteraction(): void {
    if (interactionData === null) return;
    const wsId = deps.activeWorkspaceId();
    if (interactionScope === "workspace" && wsId === null) {
      interactionError = t("settings.prompts.noWorkspace");
      render();
      return;
    }
    const effective = interactionData.effective;
    const val = (key: string): unknown =>
      key in interactionDraft ? interactionDraft[key] : effective[key];
    const values = {
      confirm_verbosity: String(val("confirm_verbosity") ?? "standard"),
      details_default_open: Boolean(val("details_default_open")),
      remember_details_choice: Boolean(val("remember_details_choice")),
      confirm_notify: Boolean(val("confirm_notify")),
    };
    interactionBusy = true;
    interactionError = "";
    interactionNotice = "";
    render();
    void deps.maintenance.interactionSave({
      scope: interactionScope,
      ...(interactionScope === "workspace" && wsId !== null ? { ws: wsId } : {}),
      values,
    }).then(
      (dto) => {
        interactionData = dto;
        interactionNotice = t("settings.interaction.saved");
        interactionBusy = false;
        render();
      },
      (err: unknown) => {
        interactionBusy = false;
        interactionError = err instanceof Error ? err.message : String(err);
        render();
      });
  }

  function interactionSourceLabel(source: string): string {
    if (source === "user") return t("settings.interaction.sourceUser");
    if (source === "workspace") return t("settings.interaction.sourceWorkspace");
    return t("settings.interaction.sourceDefault");
  }

  /** T-2：系统通知权限态（无 Notification API → unsupported）。 */
  function notifyPermissionState(): string {
    return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
  }

  function notifyPermissionText(state: string): string {
    if (state === "granted") return t("settings.interaction.notifyPermGranted");
    if (state === "denied") return t("settings.interaction.notifyPermDenied");
    if (state === "unsupported") return t("settings.interaction.notifyPermUnsupported");
    return t("settings.interaction.notifyPermDefault");
  }

  function interactionSection(): HTMLElement[] {
    if (interactionData === null && !interactionBusy && interactionError === "") {
      queueMicrotask(() => { loadInteraction(); }); // 首进触发取数
    }
    const wsId = deps.activeWorkspaceId();
    const d = interactionData;
    const effective = d?.effective ?? {};
    const sources = d?.sources ?? {};
    const draftVal = (key: string): unknown =>
      key in interactionDraft ? interactionDraft[key] : effective[key];
    const verbosity = String(draftVal("confirm_verbosity") ?? "standard");
    const detailsOpen = Boolean(draftVal("details_default_open"));
    const remember = Boolean(draftVal("remember_details_choice"));
    const effText = (key: string): string => {
      const v = effective[key];
      const shown = typeof v === "boolean"
        ? (v ? t("settings.interaction.on") : t("settings.interaction.off"))
        : String(v ?? "");
      return t("settings.interaction.effective", {
        value: shown, source: interactionSourceLabel(String(sources[key] ?? "default")),
      });
    };
    const checkbox = (key: string, checked: boolean, st: string): HTMLElement =>
      h("input", {
        class: "st-input",
        attrs: { type: "checkbox", "data-st": st, id: st, name: st,
                 ...(checked ? { checked: "checked" } : {}) },
        onChange: (ev: Event) => {
          interactionDraft[key] = (ev.target as HTMLInputElement).checked;
        },
      });
    const out: HTMLElement[] = [
      h("div", { class: "st-note", text: t("settings.interaction.hint") }),
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.prompts.scopeLabel") }),
          h("div", { class: "st-hint", text: t("settings.prompts.scopeHint") })),
        h("div", { class: "st-control" },
          h("select", {
            class: "st-input",
            attrs: { "data-st": "interaction-scope", id: "interaction-scope", name: "interaction-scope" },
            onChange: (ev: Event) => {
              interactionScope = (ev.target as HTMLSelectElement).value as "user" | "workspace";
              primeInteractionDraft();
              render();
            },
          },
            h("option", {
              attrs: { value: "user", ...(interactionScope === "user" ? { selected: "selected" } : {}) },
              text: t("settings.prompts.scopeUser"),
            }),
            h("option", {
              attrs: { value: "workspace", ...(interactionScope === "workspace" ? { selected: "selected" } : {}) },
              text: t("settings.prompts.scopeWorkspace"),
            })))),
    ];
    if (interactionBusy && interactionData === null) {
      out.push(h("div", { class: "st-hint", text: t("settings.prompts.loading") }));
    }
    if (interactionError !== "") {
      out.push(h("div", { class: "st-err", text: t("settings.prompts.failed", { msg: interactionError }) }));
    }
    if (interactionNotice !== "") {
      out.push(h("div", { class: "st-notice", text: interactionNotice }));
    }
    if (d !== null) {
      for (const p of d.problems) {
        out.push(h("div", { class: "st-err", text: t("settings.prompts.problems", { msg: p }) }));
      }
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.interaction.verbosity") }),
          h("div", { class: "st-hint dim", text: effText("confirm_verbosity") })),
        h("div", { class: "st-control" },
          h("select", {
            class: "st-input",
            attrs: { "data-st": "interaction-verbosity", id: "interaction-verbosity", name: "interaction-verbosity" },
            onChange: (ev: Event) => {
              interactionDraft["confirm_verbosity"] = (ev.target as HTMLSelectElement).value;
            },
          },
            h("option", {
              attrs: { value: "standard", ...(verbosity === "standard" ? { selected: "selected" } : {}) },
              text: t("settings.interaction.verbosityStandard"),
            }),
            h("option", {
              attrs: { value: "concise", ...(verbosity === "concise" ? { selected: "selected" } : {}) },
              text: t("settings.interaction.verbosityConcise"),
            })))));
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.interaction.detailsOpen") }),
          h("div", { class: "st-hint dim", text: effText("details_default_open") })),
        h("div", { class: "st-control" },
          checkbox("details_default_open", detailsOpen, "interaction-details-open"))));
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.interaction.remember") }),
          h("div", { class: "st-hint dim", text: effText("remember_details_choice") })),
        h("div", { class: "st-control" },
          checkbox("remember_details_choice", remember, "interaction-remember"))));
      const notifyOn = Boolean(draftVal("confirm_notify"));
      const perm = notifyPermissionState();
      const notifyBox = h("input", {
        class: "st-input",
        attrs: { type: "checkbox", "data-st": "interaction-notify",
                 id: "interaction-notify", name: "interaction-notify",
                 ...(notifyOn ? { checked: "checked" } : {}),
                 ...(perm === "unsupported" ? { disabled: "disabled" } : {}) },
        onChange: (ev: Event) => {
          const on = (ev.target as HTMLInputElement).checked;
          interactionDraft["confirm_notify"] = on;
          if (on && notifyPermissionState() === "default") {
            void Notification.requestPermission().then(
              () => { render(); }, () => { render(); });
          } else {
            render();
          }
        },
      });
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.interaction.notify") }),
          h("div", { class: "st-hint dim", text: t("settings.interaction.notifyHint") }),
          h("div", { class: "st-hint dim", text: notifyPermissionText(perm) })),
        h("div", { class: "st-control" },
          ...(perm === "default"
            ? [notifyBox, h("button", {
                class: "st-btn",
                attrs: { type: "button", "data-st": "interaction-notify-grant" },
                text: t("settings.interaction.notifyGrant"),
                onClick: () => {
                  void Notification.requestPermission().then(
                    () => { render(); }, () => { render(); });
                },
              })]
            : [notifyBox]))));
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-hint",
                      text: wsId === null && interactionScope === "workspace"
                        ? t("settings.prompts.noWorkspace") : "" })),
        h("div", { class: "st-control" },
          h("button", {
            class: "st-btn",
            attrs: { type: "button", "data-st": "interaction-save" },
            text: t("settings.interaction.save"),
            onClick: () => { saveInteraction(); },
          }))));
    }
    return out;
  }

  function promptsSection(): HTMLElement[] {
    if (promptData === null && !promptBusy && promptError === "") {
      queueMicrotask(() => { loadPrompts(); }); // 首进触发取数（异步，不阻塞本次渲染）
    }
    const wsId = deps.activeWorkspaceId();
    const out: HTMLElement[] = [
      h("div", { class: "st-note", text: t("settings.prompts.hint") }),
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.prompts.scopeLabel") }),
          h("div", { class: "st-hint", text: t("settings.prompts.scopeHint") })),
        h("div", { class: "st-control" },
          h("select", {
            class: "st-input",
            attrs: { "data-st": "prompt-scope", id: "prompt-scope", name: "prompt-scope" },
            onChange: (ev: Event) => {
              promptScope = (ev.target as HTMLSelectElement).value as "user" | "workspace";
              if (promptData !== null) primePromptDrafts(promptData);
              render();
            },
          },
            h("option", {
              attrs: { value: "user", ...(promptScope === "user" ? { selected: "selected" } : {}) },
              text: t("settings.prompts.scopeUser"),
            }),
            h("option", {
              attrs: { value: "workspace", ...(promptScope === "workspace" ? { selected: "selected" } : {}) },
              text: t("settings.prompts.scopeWorkspace"),
            })))),
    ];
    if (promptBusy && promptData === null) {
      out.push(h("div", { class: "st-hint", text: t("settings.prompts.loading") }));
    }
    if (promptError !== "") {
      out.push(h("div", { class: "st-err", text: t("settings.prompts.failed", { msg: promptError }) }));
    }
    if (promptNotice !== "") {
      out.push(h("div", { class: "st-notice", text: promptNotice }));
    }
    if (promptData !== null) {
      for (const p of promptData.problems) {
        out.push(h("div", { class: "st-err", text: t("settings.prompts.problems", { msg: p }) }));
      }
      for (const entry of promptData.entries) {
        const title = `${t(`settings.prompts.domain.${entry.domain}`)}（${entry.domain}）`;
        out.push(h("div", { class: "st-field" },
          h("div", { class: "st-field-main" },
            h("div", { class: "st-label", text: title }),
            h("div", { class: "st-hint", text: t("settings.prompts.notes") }),
            h("div", { class: "st-hint dim",
                        text: `${t("settings.prompts.builtin")}${entry.builtin_notes} · ` +
                              t("settings.prompts.effective", { source: promptSourceLabel(entry.notes_source) }) })),
          h("div", { class: "st-control" }, promptTextarea(entry.domain, "notes"))));
        out.push(h("div", { class: "st-field" },
          h("div", { class: "st-field-main" },
            h("div", { class: "st-label", text: t("settings.prompts.addendum") }),
            h("div", { class: "st-hint dim",
                        text: t("settings.prompts.effective", { source: promptSourceLabel(entry.addendum_source) }) })),
          h("div", { class: "st-control" },
            promptTextarea(entry.domain, "addendum"),
            h("button", {
              class: "st-btn ghost",
              attrs: { type: "button", "data-st": `prompt-restore:${entry.domain}` },
              text: t("settings.prompts.restore"),
              onClick: () => {
                promptDrafts[entry.domain] = { notes: "", addendum: "" };
                render();
              },
            }))));
      }
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-hint",
                      text: wsId === null && promptScope === "workspace"
                        ? t("settings.prompts.noWorkspace") : "" })),
        h("div", { class: "st-control" },
          h("button", {
            class: "st-btn",
            attrs: { type: "button", "data-st": "prompt-save" },
            text: t("settings.prompts.save"),
            onClick: () => { savePrompts(); },
          }))));
    }
    return out;
  }

  function dataSection(): HTMLElement[] {
    if (maint === null && !maintBusy && maintError === "") {
      queueMicrotask(() => { loadMaintenance(); }); // 首进触发取数（异步，不阻塞本次渲染）
    }
    if (allowEntries === null && !allowBusy && allowError === "") {
      queueMicrotask(() => { loadBrowserAllow(); }); // O2-2 P3：允许条目懒加载
    }
    if (identityData === null && !identityBusy && identityError === "") {
      queueMicrotask(() => { loadBrowserIdentity(); }); // §11.5-①：身份懒加载
    }
    const wsId = deps.activeWorkspaceId();
    const ws = maint?.workspace ?? null;
    const out: HTMLElement[] = [
      h("div", { class: "st-note", text: t("settings.maint.note") }),
    ];
    if (maintBusy && maint === null) out.push(h("div", { class: "st-hint", text: t("settings.maint.loading") }));
    if (maintError !== "") out.push(h("div", { class: "st-err", text: t("settings.maint.failed", { msg: maintError }) }));
    if (maintNotice !== "") out.push(h("div", { class: "st-notice", text: maintNotice }));
    if (maint !== null) {
      out.push(maintRow(t("settings.maint.userDir"), maint.user_dir, null));
      out.push(maintRow(t("settings.maint.shellDir"), maint.shell_dir, null));
      out.push(maintRow(t("settings.maint.events"),
        `${maint.events.path} · ${fmtBytes(maint.events.size)}`,
        maintConfirm === "shell_events"
          ? h("button", {
            class: "st-btn danger", attrs: { type: "button", "data-st": "maint-clean-ok:shell_events" },
            text: t("settings.maint.clearEventsConfirm"),
            onClick: () => { runClean("shell_events"); },
          })
          : h("button", {
            class: "st-btn ghost", attrs: { type: "button", "data-st": "maint-clean:shell_events" },
            text: t("settings.maint.clearEvents"),
            onClick: () => { maintConfirm = "shell_events"; render(); },
          })));
      out.push(maintRow(t("settings.maint.skills"),
        `${maint.skills.path} · ${maint.skills.count}`, null));
      if (wsId !== null) {
        const cacheText = ws === null
          ? t("settings.maint.noWorkspace")
          : ws!.caches.map((c) => `${c.name} ${fmtBytes(c.size)}`).join(" · ");
        out.push(maintRow(t("settings.maint.wsCaches"), cacheText,
          maintConfirm === "workspace_cache"
            ? h("button", {
              class: "st-btn danger", attrs: { type: "button", "data-st": "maint-clean-ok:workspace_cache" },
              text: t("settings.maint.cleanCacheConfirm"),
              onClick: () => { runClean("workspace_cache"); },
            })
            : h("button", {
              class: "st-btn ghost", attrs: { type: "button", "data-st": "maint-clean:workspace_cache" },
              text: t("settings.maint.cleanCache"),
              onClick: () => { maintConfirm = "workspace_cache"; render(); },
            })));
      }
    }
    // O2-2 P3：浏览器允许条目（回环动态授权）——列表 + 逐条撤销（两步确认）
    out.push(h("div", { class: "st-note", attrs: { "data-st": "browser-allow" },
                         text: t("settings.browserAllow.title") }));
    out.push(h("div", { class: "st-hint",
                         text: t("settings.browserAllow.hint") }));
    if (allowBusy && allowEntries === null) {
      out.push(h("div", { class: "st-hint",
                           text: t("settings.browserAllow.loading") }));
    }
    if (allowError !== "") {
      out.push(h("div", { class: "st-err",
                           text: t("settings.browserAllow.failed", { msg: allowError }) }));
    }
    if (allowNotice !== "") {
      out.push(h("div", { class: "st-notice", text: allowNotice }));
    }
    if (allowEntries !== null) {
      if (allowEntries.length === 0) {
        out.push(h("div", { class: "st-hint",
                             text: t("settings.browserAllow.empty") }));
      }
      for (const entry of allowEntries) {
        const kind = entry.kind === "lan" ? "lan" : "loopback";
        const kindLabel = kind === "lan"
          ? t("settings.browserAllow.kindLan")
          : t("settings.browserAllow.kindLoopback");
        const key = `${entry.address}|${kind}`;
        const detail = kind === "lan"
          ? `${(entry.resolved_ips as unknown[]).map(String).join(", ") || "-"}`
          : entry.fingerprint.slice(0, 12);
        out.push(maintRow(
          entry.address,
          `${kindLabel} · ${entry.label || t("settings.browserAllow.unknown")} · ` +
          `${detail} · ` +
          `${entry.last_seen_at || entry.first_approved_at}`,
          allowConfirm === key
            ? h("button", {
              class: "st-btn danger",
              attrs: { type: "button",
                       "data-st": `browser-allow-revoke-ok:${entry.address}` },
              text: t("settings.browserAllow.revokeConfirm"),
              onClick: () => { revokeBrowserAllow(entry.address, entry.fingerprint, kind); },
            })
            : h("button", {
              class: "st-btn ghost",
              attrs: { type: "button",
                       "data-st": `browser-allow-revoke:${entry.address}` },
              text: t("settings.browserAllow.revoke"),
              onClick: () => { allowConfirm = key; render(); },
            })));
      }
    }
    // O2-2 §11.5-①：浏览器身份（memory/persist 档 + 持久条目清除）
    out.push(h("div", { class: "st-note", attrs: { "data-st": "browser-identity" },
                         text: t("settings.browserIdentity.title") }));
    out.push(h("div", { class: "st-hint",
                         text: t("settings.browserIdentity.hint") }));
    if (identityBusy && identityData === null) {
      out.push(h("div", { class: "st-hint",
                           text: t("settings.browserIdentity.loading") }));
    }
    if (identityError !== "") {
      out.push(h("div", { class: "st-err",
                           text: t("settings.browserIdentity.failed", { msg: identityError }) }));
    }
    if (identityNotice !== "") {
      out.push(h("div", { class: "st-notice", text: identityNotice }));
    }
    if (identityData !== null) {
      for (const p of identityData.problems) {
        out.push(h("div", { class: "st-err",
                             text: t("settings.browserIdentity.problems", { msg: p }) }));
      }
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.browserIdentity.mode") }),
          h("div", { class: "st-hint",
                      text: identityData.current_key
                        ? `${t("settings.browserIdentity.current")}${identityData.current_key}`
                        : t("settings.browserIdentity.noWorkspace") })),
        h("div", { class: "st-control" },
          h("select", {
            class: "st-input",
            attrs: { "data-st": "browser-identity-mode", id: "browser-identity-mode", name: "browser-identity-mode" },
            onChange: (ev: Event) => { changeIdentityMode((ev.target as HTMLSelectElement).value); },
          },
            h("option", {
              attrs: { value: "memory", ...(identityData.mode === "memory" ? { selected: "selected" } : {}) },
              text: t("settings.browserIdentity.modeMemory"),
            }),
            h("option", {
              attrs: { value: "persist", ...(identityData.mode === "persist" ? { selected: "selected" } : {}) },
              text: t("settings.browserIdentity.modePersist"),
            }),
            h("option", {
              attrs: { value: "storage-state", ...(identityData.mode === "storage-state" ? { selected: "selected" } : {}) },
              text: t("settings.browserIdentity.modeStorageState"),
            })))));
      if (identityData.mode === "storage-state") {
        const storage = identityData.storage_state;
        out.push(h("div", { class: "st-field" },
          h("div", { class: "st-field-main" },
            h("div", { class: "st-label", text: t("settings.browserIdentity.storagePath") }),
            h("div", { class: "st-hint", text: t("settings.browserIdentity.storagePathHint") })),
          h("div", { class: "st-control" },
            h("input", {
              class: "st-input",
              attrs: { type: "text", "data-st": "browser-storage-path",
                       id: "browser-storage-path", name: "browser-storage-path",
                       placeholder: t("settings.browserIdentity.storagePathPlaceholder"),
                       value: storagePathDraft },
              onInput: (ev: Event) => {
                storagePathDraft = (ev.target as HTMLInputElement).value;
              },
            }))));
        out.push(h("div", { class: "st-field" },
          h("div", { class: "st-field-main" },
            h("div", { class: "st-label", text: t("settings.browserIdentity.storageStatus") }),
            h("div", { class: "st-hint",
                        text: storage === null
                          ? t("settings.browserIdentity.storageNone")
                          : storage.valid
                            ? t("settings.browserIdentity.storageLoaded",
                                { c: String(storage.cookies), o: String(storage.origins) })
                            : t("settings.browserIdentity.storageInvalid", { msg: storage.error }) })),
          h("div", { class: "st-control" },
            h("button", {
              class: "st-btn",
              attrs: { type: "button", "data-st": "browser-storage-save" },
              text: t("settings.browserIdentity.storageSave"),
              onClick: () => { saveStoragePath(); },
            }))));
      }
      if (identityData.entries.length === 0) {
        out.push(h("div", { class: "st-hint",
                             text: t("settings.browserIdentity.empty") }));
      }
      for (const entry of identityData.entries) {
        out.push(maintRow(
          entry.workspace || entry.key,
          `${entry.key.slice(0, 24)} · ${entry.last_used_at || entry.first_used_at}`,
          identityConfirm === entry.key
            ? h("button", {
              class: "st-btn danger",
              attrs: { type: "button",
                       "data-st": `browser-identity-clear-ok:${entry.key}` },
              text: t("settings.browserIdentity.clearConfirm"),
              onClick: () => { clearBrowserIdentity(entry.key); },
            })
            : h("button", {
              class: "st-btn ghost",
              attrs: { type: "button",
                       "data-st": `browser-identity-clear:${entry.key}` },
              text: t("settings.browserIdentity.clear"),
              onClick: () => { identityConfirm = entry.key; render(); },
            })));
      }
    }
    return out;
  }

  function appearanceSection(): HTMLElement[] {
    const enabled = loadDockViews();
    const currentTheme = String(config?.values.ui_theme ?? "ink");
    return [
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.uiTheme.name") }),
          h("div", { class: "st-hint", text: t("settings.uiTheme.desc") })),
        h("div", { class: "st-control" },
          h("select", {
            class: "st-input", attrs: { "data-st": "ui-theme", id: "ui-theme", name: "ui-theme" },
            onChange: (ev: Event) => {
              changeTheme((ev.target as HTMLSelectElement).value);
            },
          },
            h("option", {
              attrs: { value: "ink", ...(currentTheme === "ink" ? { selected: "selected" } : {}) },
              text: t("settings.uiTheme.ink"),
            }),
            h("option", {
              attrs: { value: "plain", ...(currentTheme === "plain" ? { selected: "selected" } : {}) },
              text: t("settings.uiTheme.plain"),
            })))),
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.floatCard.name") }),
          h("div", { class: "st-hint", text: t("settings.floatCard.desc") })),
        h("div", { class: "st-control" },
          h("label", { class: "st-check" },
            h("input", {
              class: "st-check-input",
              attrs: {
                type: "checkbox", "data-st": "float-card",
                id: "float-card", name: "float-card",
                ...(deps.floatCardEnabled() ? { checked: "checked" } : {}),
              },
              onChange: (ev: Event) => {
                deps.onFloatCardChange((ev.target as HTMLInputElement).checked);
              },
            })))),
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.lang.name") }),
          h("div", { class: "st-hint", text: t("settings.lang.desc") })),
        h("div", { class: "st-control" },
          h("select", {
            class: "st-input", attrs: { "data-st": "lang", id: "lang", name: "ui-lang" },
            onChange: (ev: Event) => {
              setLang((ev.target as HTMLSelectElement).value === "en" ? "en" : "zh");
            },
          },
            h("option", {
              attrs: { value: "zh", ...(getLang() === "zh" ? { selected: "selected" } : {}) },
              text: "中文",
            }),
            h("option", {
              attrs: { value: "en", ...(getLang() === "en" ? { selected: "selected" } : {}) },
              text: "English",
            })))),
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t("settings.dockViews.name") }),
          h("div", {
            class: "st-hint",
            text: dockHint !== "" ? dockHint : t("settings.dockViews.desc"),
          })),
        h("div", { class: "st-control" },
          h("div", { class: "st-checks" }, ...DOCK_VIEW_IDS.map((id) => {
            const checked = enabled.includes(id);
            return h("label", { class: "st-check" },
              h("input", {
                class: "st-check-input",
                attrs: {
                  type: "checkbox",
                  "data-st": `dock-view:${id}`,
                  id: `dock-view-${id}`, name: "dock-view",
                  ...(checked ? { checked: "checked" } : {}),
                },
                onChange: (ev: Event) => {
                  const input = ev.target as HTMLInputElement;
                  const current = loadDockViews();
                  const next = input.checked
                    ? DOCK_VIEW_IDS.filter((view) => current.includes(view) || view === id)
                    : current.filter((view) => view !== id);
                  if (next.length === 0) {
                    input.checked = true;
                    dockHint = t("settings.dockViews.keepOne");
                    render();
                    return;
                  }
                  dockHint = "";
                  setDockViews(next);
                  render();
                },
              }),
              h("span", { text: t(`dock.${id}`) }));
          })))),
    ];
  }

  /* ---------- 模型与供应商 ---------- */

  function modelSection(): HTMLElement[] {
    const out: HTMLElement[] = [];
    out.push(h("div", { class: "st-note", text: t("settings.prov.note") }));
    if (conflict) {
      out.push(h("div", { class: "st-err" },
        h("span", { text: t("settings.conflict") }),
        h("button", {
          class: "st-btn", attrs: { type: "button", "data-st": "reload" }, text: t("settings.reload"),
          onClick: () => {
            void refresh().catch((err: unknown) => {
              notice = describeError(err).message;
              render();
            });
          },
        })));
    }
    foldInstances.clear();   // 每次重渲染重建实例表（旧实例随 DOM 卸下）
    for (const [pid, entry] of Object.entries(providers())) out.push(providerRow(pid, entry));
    if (expanded === "__draft__") out.push(providerCard("__draft__", draftOf("__draft__")));
    out.push(h("button", {
      class: "st-btn ghost", attrs: { type: "button", "data-st": "add-provider" },
      text: t("settings.prov.add"),
      onClick: () => { expanded = "__draft__"; draftOf("__draft__"); render(); },
    }));
    out.push(defaultModelRow());
    out.push(...routerRows());
    out.push(...simpleFields(["llm_max_retries", "llm_timeout"]));
    return out;
  }

  function providerRow(pid: string, entry: ProviderEntry): HTMLElement {
    const ref = refOf(pid, entry);
    const status = statuses[ref];
    const dotClass = status === undefined ? "st-dot" : status.configured ? "st-dot on" : "st-dot off";
    const row = h("div", { class: expanded === pid ? "st-provider open" : "st-provider" });
    let foldRef: FoldInstance | null = null;
    const body = providerCard(pid, draftOf(pid), () => {
      // 卡内「收起」按钮：走折叠动画（不必整页重渲染）
      foldRef?.setOpen(false);
      expanded = null;
      picker = null;
      confirmDel = null;
      row.classList.remove("open");
    });
    const head = h("button", {
      class: "st-provider-head", attrs: { type: "button", "data-st": `toggle:${pid}` },
    },
      h("span", { class: dotClass }),
      h("span", { class: "st-provider-name", text: entry.display_name || pid }),
      h("span", { class: "st-provider-meta", text: `${entry.type ?? ""}${(entry.models ?? []).length > 0 ? ` · ${t("settings.prov.modelCount", { n: (entry.models ?? []).length })}` : ""}` }),
    );
    const fold = createFold({
      head, body, open: expanded === pid,
      onToggle: (open) => {
        expanded = open ? pid : null;
        if (open) {
          draftOf(pid);
          picker = null;
          confirmDel = null;
          // 互斥：其余 provider 卡同动效收起（实例同步——不整页重渲染，保留动画）
          for (const [other, inst] of foldInstances) {
            if (other !== pid && inst.isOpen()) inst.setOpen(false);
          }
          for (const el of row.parentElement?.querySelectorAll(".st-provider.open") ?? []) {
            el.classList.remove("open");
          }
        }
        row.classList.toggle("open", open);
      },
    });
    foldRef = fold;
    foldInstances.set(pid, fold);
    row.appendChild(fold.root);
    return row;
  }

  function providerCard(id: string, d: ProviderDraft, onCollapse?: () => void): HTMLElement {
    const isDraft = id === "__draft__";
    const card = h("div", { class: "st-provider-card" });
    card.appendChild(labeled(t("settings.prov.name"), h("input", {
      class: "st-input", attrs: { type: "text", "data-st": `name:${id}`,
                                  id: `prov-name-${id}`, name: "provider-name" },
      value: d.display_name,
      onInput: (ev: Event) => {
        d.display_name = (ev.target as HTMLInputElement).value;
        d.nameTouched = true;
      },
    })));
    card.appendChild(labeled(t("settings.prov.baseUrl"), h("input", {
      class: "st-input", attrs: { type: "text", "data-st": `url:${id}`,
                                  id: `prov-url-${id}`, name: "provider-base-url",
                                  placeholder: "https://api.example.com/v1" },
      value: d.base_url,
      onInput: (ev: Event) => { d.base_url = (ev.target as HTMLInputElement).value; },
      onChange: () => { autoMatch(id); },
    })));
    if (d.matched !== null) {
      const hit = catalog.find((c) => c.id === d.matched);
      if (hit) card.appendChild(h("div", { class: "st-hint", text: t("settings.prov.matched", { name: hit.name }) }));
    }
    const keyInput = h("input", {
      class: "st-input", attrs: { type: "password", "data-st": `key:${id}`,
                                  id: `prov-key-${id}`, name: "provider-key",
                                  autocomplete: "off" },
      value: "",
      placeholder: t("settings.prov.keyPlaceholder"),
      onInput: (ev: Event) => { d.key = (ev.target as HTMLInputElement).value; },
    }) as HTMLInputElement;
    keyInput.value = d.key;
    card.appendChild(labeled(t("settings.prov.key"), keyInput));
    card.appendChild(h("details", { class: "st-adv" },
      h("summary", { text: t("settings.prov.advanced") }),
      labeled(t("settings.prov.protocol"), h("select", {
        class: "st-input", attrs: { "data-st": `type:${id}`,
                                    id: `prov-type-${id}`, name: "provider-protocol" },
        onChange: (ev: Event) => { d.type = (ev.target as HTMLSelectElement).value; },
      }, ...["deepseek", "openai", "anthropic", "responses"].map((t) =>
        h("option", { attrs: { value: t, ...(t === d.type ? { selected: "selected" } : {}) }, text: t })))),
    ));
    card.appendChild(h("div", { class: "st-fl", text: t("settings.prov.models") }));
    d.models.forEach((m, idx) => {
      card.appendChild(h("div", { class: "st-model-row" },
        h("input", {
          class: "st-input", attrs: { type: "text", "data-st": `model:${id}:${idx}`,
                                      id: `prov-model-${id}-${idx}`, name: "provider-model" },
          value: m.id,
          onInput: (ev: Event) => { m.id = (ev.target as HTMLInputElement).value; },
        }),
        h("button", {
          class: "st-mini", attrs: { type: "button", "data-st": `model-del:${id}:${idx}` }, text: "×",
          onClick: () => { d.models.splice(idx, 1); render(); },
        })));
    });
    card.appendChild(h("div", { class: "st-row" },
      h("button", {
        class: "st-btn ghost", attrs: { type: "button", "data-st": `model-add:${id}` }, text: t("settings.prov.modelAdd"),
        onClick: () => { d.models.push({ id: "" }); render(); },
      }),
      h("button", {
        class: "st-btn ghost", attrs: { type: "button", "data-st": `fetch:${id}` }, text: busy ? t("settings.prov.fetching") : t("settings.prov.fetch"),
        onClick: () => { void fetchModels(id); },
      })));
    if (picker !== null && picker.id === id) card.appendChild(pickerBox());
    const err = error[id];
    if (err !== undefined && err !== "") card.appendChild(h("div", { class: "st-err", text: err }));
    const foot = h("div", { class: "st-row" },
      h("button", {
        class: "st-btn", attrs: { type: "button", "data-st": `save:${id}` }, text: busy ? t("settings.prov.saving") : t("settings.prov.save"),
        onClick: () => { void saveProvider(id); },
      }),
      h("button", {
        class: "st-btn ghost", attrs: { type: "button", "data-st": `collapse:${id}` }, text: t("settings.prov.collapse"),
        onClick: () => {
          if (onCollapse) { onCollapse(); return; }
          expanded = null; picker = null; confirmDel = null; render();
        },
      }));
    if (!isDraft) {
      if (confirmDel === id) {
        foot.appendChild(h("button", {
          class: "st-btn danger", attrs: { type: "button", "data-st": `del-ok:${id}` },
          text: t("settings.prov.deleteConfirm", { name: d.display_name || id }),
          onClick: () => { void removeProvider(id); },
        }));
        foot.appendChild(h("button", {
          class: "st-btn ghost", attrs: { type: "button", "data-st": `del-cancel:${id}` }, text: t("settings.prov.cancel"),
          onClick: () => { confirmDel = null; render(); },
        }));
      } else {
        foot.appendChild(h("button", {
          class: "st-btn ghost", attrs: { type: "button", "data-st": `del:${id}` }, text: t("settings.prov.delete"),
          onClick: () => { confirmDel = id; render(); },
        }));
      }
    }
    card.appendChild(foot);
    return card;
  }

  function pickerBox(): HTMLElement {
    if (picker === null) return h("div", {});
    const state = picker;
    const listHost = h("div", { class: "st-pick-list" });
    const count = h("span", { class: "st-hint" });
    const visible = (): ProviderModel[] => {
      const q = state.query.trim().toLowerCase();
      return state.models.filter((m) =>
        q === "" || `${m.id} ${m.display_name ?? ""}`.toLowerCase().includes(q));
    };
    const refreshList = (): void => {
      mount(listHost, ...visible().map((m) =>
        h("label", { class: "st-pick-item" },
          h("input", {
            attrs: { type: "checkbox", id: `pick-model-${m.id}`, name: "provider-model-pick",
                     ...(state.selected[m.id] === true ? { checked: "checked" } : {}) },
            onChange: (ev: Event) => {
              if ((ev.target as HTMLInputElement).checked) state.selected[m.id] = true;
              else delete state.selected[m.id];
              count.textContent = t("settings.prov.pickSelected", { n: Object.keys(state.selected).length });
            },
          }),
          h("span", { text: `${m.id}${m.display_name !== undefined ? ` · ${m.display_name}` : ""}` }))));
      count.textContent = t("settings.prov.pickSelected", { n: Object.keys(state.selected).length });
    };
    const box = h("div", { class: "st-picker" },
      h("input", {
        class: "st-input",
        attrs: { type: "text", "data-st": "pick-search",
                 id: "pick-search", name: "model-pick-search",
                 placeholder: t("settings.prov.pickSearch") },
        value: state.query,
        onInput: (ev: Event) => {
          state.query = (ev.target as HTMLInputElement).value;
          refreshList();
        },
      }),
      h("div", { class: "st-row" },
        h("button", {
          class: "st-btn ghost", attrs: { type: "button" }, text: t("settings.prov.pickAll"),
          onClick: () => { for (const m of visible()) state.selected[m.id] = true; refreshList(); },
        }),
        h("button", {
          class: "st-btn ghost", attrs: { type: "button" }, text: t("settings.prov.pickNone"),
          onClick: () => { state.selected = {}; refreshList(); },
        }),
        count),
      listHost,
      h("div", { class: "st-row" },
        h("button", {
          class: "st-btn", attrs: { type: "button" }, text: t("settings.prov.pickAdd"),
          onClick: () => {
            const d = draftOf(state.id);
            const have = new Set(d.models.map((m) => m.id));
            for (const m of state.models) {
              if (state.selected[m.id] === true && !have.has(m.id)) { d.models.push({ ...m }); have.add(m.id); }
            }
            picker = null; render();
          },
        }),
        h("button", {
          class: "st-btn ghost", attrs: { type: "button" }, text: t("settings.prov.cancel"),
          onClick: () => { picker = null; render(); },
        })));
    refreshList();
    return box;
  }

  function defaultModelRow(): HTMLElement {
    const current = typeof config?.values.llm === "string" ? config.values.llm : "";
    return optionRow(t("settings.model.default"), current, (ev) => {
      void writeValues({ llm: (ev.target as HTMLSelectElement).value }, {});
    }, { freeInput: true });
  }

  const ROUTER_DOMAINS = ["plan", "execute", "verify", "user"] as const;

  function routerRows(): HTMLElement[] {
    const router = (config?.values.router as Record<string, string> | undefined) ?? {};
    const rows: HTMLElement[] = [h("div", { class: "st-note", text: t("settings.model.routerHint") })];
    const options = [{ value: "", label: t("settings.model.useDefault") }, ...modelOptions()];
    for (const domain of ROUTER_DOMAINS) {
      const current = typeof router[domain] === "string" ? router[domain] as string : "";
      rows.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t(`domain.${domain}`) }),
          h("div", { class: "st-hint", text: t(`settings.model.domain.${domain}.desc`) })),
        h("div", { class: "st-control" },
          withDataSt(selectOf(options, current, (ev) => {
            const value = (ev.target as HTMLSelectElement).value;
            const next = { ...router };
            if (value === "") delete next[domain];
            else next[domain] = value;
            void writeValues({ router: next }, { replace: ["router"] });
          }), `route:${domain}`))));
    }
    return rows;
  }

  function optionRow(label: string, current: string, onChange: (ev: Event) => void,
                     opts: { freeInput?: boolean } = {}): HTMLElement {
    const options = modelOptions();
    const known = options.some((o) => o.value === current);
    const extra = current !== "" && !known ? [current] : [];
    const controls: HTMLElement[] = [withDataSt(
      selectOf([...extra.map((v) => ({ value: v, label: t("settings.model.current", { v }) })), ...options],
               current, onChange), "model-default")];
    if (opts.freeInput === true) {
      // U9（O4）：未注册供应商时下拉无备选——自由输入兜底（任意 供应商id/模型id）
      const input = h("input", {
        class: "st-input",
        attrs: {
          type: "text", "data-st": "model-default-free",
          id: "model-default-free", name: "model-default-free",
          placeholder: t("settings.model.freeInput"), spellcheck: "false",
        },
        onChange: (ev: Event) => {
          const el = ev.target as HTMLInputElement;
          const value = el.value.trim();
          if (value === "" || value === current) return;
          el.value = value;
          onChange(ev);
        },
      }) as HTMLInputElement;
      controls.push(input);
    }
    return labeled(label, h("div", { class: "st-row" }, ...controls));
  }

  function selectOf(options: readonly ModelOption[], current: string, onChange: (ev: Event) => void): HTMLElement {
    return h("select", {
      class: "st-input", attrs: { "data-st": "model-select" },
      onChange,
    },
      ...(options.length === 0 ? [h("option", { attrs: { value: "" }, text: t("settings.model.none") })] : []),
      ...options.map((o) => h("option", {
        attrs: { value: o.value, ...(o.value === current ? { selected: "selected" } : {}) },
        text: o.label,
      })));
  }

  /** 给控件补 data-st + id/name（E2E/断言锚点与表单语义；selectOf 保持通用）。 */
  function withDataSt(el: HTMLElement, key: string): HTMLElement {
    el.setAttribute("data-st", key);
    if (!el.id) el.id = `field-${key.replace(/:/g, "-")}`;
    el.setAttribute("name", key);
    return el;
  }

  /** 配置来源徽标（U10）：本地化 + tooltip 解释来源层级。 */
  function sourceBadge(source: string): HTMLElement {
    const label = t(fieldSourceKey(source));
    return h("span", {
      class: "st-source",
      attrs: { title: t("settings.field.sourceTitle", { source: label }) },
      text: label,
    });
  }

  /* ---------- 机制调优 ---------- */

  /** 设置项搜索过滤（按字段名/标签子串；空查询不过滤）。 */
  function filterFields(fields: ReturnType<typeof deriveFields>): ReturnType<typeof deriveFields> {
    const q = searchQuery.trim().toLowerCase();
    if (q === "") return fields;
    return fields.filter((f) =>
      f.label.toLowerCase().includes(q) || f.name.toLowerCase().includes(q));
  }

  /** 模式分区（双模式批 1）：三项细节 + 默认/显隐/纯净自动确认（schema 驱动控件）。 */
  function modesSection(): HTMLElement[] {
    const fields = filterFields(deriveFields("modes", schema, {
      values: config?.values ?? {}, sources: config?.sources ?? {},
    }));
    const out: HTMLElement[] = [
      h("div", { class: "st-note", attrs: { "data-st": "settings-modes" }, text: t("settings.modes.note") }),
    ];
    for (const id of ["minimal-pure", "minimal-standard", "theroad"]) {
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label", text: t(`mode.label.${id}`) }),
          h("div", { class: "st-hint", text: t(`mode.desc.${id}`) }))));
    }
    for (const f of fields) {
      const def = f.defaultValue === undefined ? "—" : String(f.defaultValue);
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label" },
            f.label,
            sourceBadge(f.source)),
          h("div", { class: "st-hint", text: fieldDesc(f.name) }),
          h("div", { class: "st-hint dim", text: t("settings.mech.hint", { value: def }) })),
        h("div", { class: "st-control" }, controlFor(f))));
    }
    return out;
  }

  function mechanismSection(): HTMLElement[] {
    const fields = filterFields(deriveFields("mechanism", schema, { values: config?.values ?? {}, sources: config?.sources ?? {} }));
    const out: HTMLElement[] = [
      h("div", { class: "st-note", text: t("settings.mech.note") }),
    ];
    for (const f of fields) {
      const def = f.defaultValue === undefined ? "—" : String(f.defaultValue);
      out.push(h("div", { class: "st-field" },
        h("div", { class: "st-field-main" },
          h("div", { class: "st-label" },
            f.label,
            sourceBadge(f.source)),
          h("div", { class: "st-hint", text: fieldDesc(f.name) }),
          h("div", { class: "st-hint dim", text: t("settings.mech.hint", { value: def }) })),
        h("div", { class: "st-control" }, controlFor(f))));
      if (f.name === "use_real_shape" && f.value === true && !realShapeConfigured()) {
        out.push(h("div", {
          class: "st-hint",
          attrs: { "data-st": "hint:use_real_shape" },
          text: t("settings.mech.realShapeHint"),
        }));
      }
    }
    return out;
  }

  /** 真实形状化凭据是否已配置（任一候选 ref 已配置即算——与引擎解析同口径）。 */
  const realShapeConfigured = (): boolean =>
    realShapeCredentialRefs(config?.values)
      .some((ref) => statuses[ref]?.configured === true);

  function controlFor(f: ReturnType<typeof deriveFields>[number]): HTMLElement {
    if (f.control === "toggle") {
      const on = f.value === true;
      return h("button", {
        class: on ? "sw" : "sw off",
        attrs: { type: "button", "data-st": `field:${f.name}`, "aria-pressed": String(on), "aria-label": f.label },
        onClick: () => { void writeValues({ [f.name]: !on }, {}); },
      });
    }
    if (f.control === "number") {
      return h("input", {
        class: "st-input st-narrow", attrs: { type: "number", "data-st": `field:${f.name}`,
                                             id: `field-${f.name}`, name: f.name },
        value: String(f.value ?? ""),
        onChange: (ev: Event) => {
          const raw = (ev.target as HTMLInputElement).value;
          void writeValues({ [f.name]: f.type === "int" ? parseInt(raw, 10) : parseFloat(raw) }, {});
        },
      });
    }
    if (f.control === "select") {
      const options = f.options ?? [];
      const select = h("select", {
        class: "st-input st-narrow", attrs: { "data-st": `field:${f.name}`,
                                             id: `field-${f.name}`, name: f.name },
        onChange: (ev: Event) => {
          void writeValues({ [f.name]: (ev.target as HTMLSelectElement).value }, {});
        },
      }, ...options.map((o) => h("option", {
        attrs: { value: o, ...(o === f.value ? { selected: "selected" } : {}) },
        text: o,
      })));
      // SEC3：full-access 显式警告（危险面可见——设计 §4.3）
      if (f.name === "permission_profile" && f.value === "full-access") {
        return h("div", { class: "st-row" }, select,
          h("div", {
            class: "st-hint",
            attrs: { "data-st": "perm-profile-warning" },
            text: t("settings.permProfile.warning"),
          }));
      }
      return select;
    }
    if (f.name === "sandbox_container_template") {
      return containerTemplateControl(f);
    }
    return h("input", {
      class: "st-input", attrs: { type: "text", "data-st": `field:${f.name}`,
                                  id: `field-${f.name}`, name: f.name },
      value: String(f.value ?? ""),
      onChange: (ev: Event) => { void writeValues({ [f.name]: (ev.target as HTMLInputElement).value }, {}); },
    });
  }

  /** BOX-M2：容器模板控件（输入 + 两枚推荐模板一键填入）。 */
  function containerTemplateControl(
    f: ReturnType<typeof deriveFields>[number],
  ): HTMLElement {
    const input = h("input", {
      class: "st-input",
      attrs: {
        type: "text", "data-st": "field:sandbox_container_template",
        id: "field-sandbox_container_template",
        name: "sandbox_container_template",
      },
      value: String(f.value ?? ""),
      onChange: (ev: Event) => {
        void writeValues({ [f.name]: (ev.target as HTMLInputElement).value }, {});
      },
    }) as HTMLInputElement;
    const fill = (tpl: string) => (): void => {
      input.value = tpl;
      void writeValues({ [f.name]: tpl }, {});
    };
    return h("div", { class: "st-row" },
      input,
      h("button", {
        class: "st-btn ghost",
        attrs: { type: "button", "data-st": "tpl-fill:docker-rm" },
        text: t("settings.sandbox.tplDockerRun"),
        onClick: fill("docker run --rm -i -v {workdir}:/ws -w /ws <image> sh -c \"echo {cmd_b64} | base64 -d | sh\""),
      }),
      h("button", {
        class: "st-btn ghost",
        attrs: { type: "button", "data-st": "tpl-fill:docker-exec" },
        text: t("settings.sandbox.tplDockerExec"),
        onClick: fill("docker exec -i <container> sh -c \"echo {cmd_b64} | base64 -d | sh\""),
      }));
  }

  function simpleFields(names: readonly string[]): HTMLElement[] {
    const fields = filterFields(deriveFields("model", schema, { values: config?.values ?? {}, sources: config?.sources ?? {} }));
    return fields.filter((f) => names.includes(f.name)).map((f) =>
      h("div", { class: "st-field" },
        h("div", { class: "st-field-main" }, h("div", { class: "st-label", text: f.label })),
        h("div", { class: "st-control" }, controlFor(f))));
  }

  function labeled(label: string, control: HTMLElement): HTMLElement {
    return h("label", { class: "st-labeled" },
      h("span", { class: "st-fl", text: label }), control);
  }

  /* ---------- 动作 ---------- */

  async function writeValues(values: Record<string, unknown>, opts: { replace?: readonly string[] }): Promise<void> {
    if (busy) return;
    busy = true; conflict = false; notice = "";
    try {
      const out = await deps.settings.writeConfig(values, {
        ...(opts.replace !== undefined ? { replace: opts.replace } : {}),
        revision: revision(),
      });
      config = { ...(config ?? { values: {}, sources: {} }), revision: out.revision };
      await refresh();
    } catch (err) {
      const described = describeError(err);
      conflict = described.conflict;
      notice = described.message;
      render();
    } finally {
      busy = false;
    }
  }

  /** 主题切换（双写：引擎配置 ui_theme → 壳即时生效）。 */
  function changeTheme(value: string): void {
    void writeValues({ ui_theme: value }, {}).then(() => {
      if (String(config?.values.ui_theme ?? "") === value) {
        deps.onUiThemeChange(value);
      }
    });
  }

  function autoMatch(id: string): void {
    const d = draftOf(id);
    const host = hostOf(d.base_url);
    const hit = catalog.find((c) => (c.hosts ?? []).some((hh) => hh.split(":")[0]?.toLowerCase() === host));
    d.matched = hit?.id ?? null;
    if (hit !== undefined) {
      d.type = hit.type;
      if (typeof hit.env === "string" && hit.env !== "") d.credential_ref = hit.env;
      if (!d.nameTouched || d.display_name.trim() === "") d.display_name = hit.name;
    }
    error[id] = "";
    render();
  }

  async function fetchModels(id: string): Promise<void> {
    const d = draftOf(id);
    const kf = keyFailure(d.key);
    if (kf !== "") { fail(id, kf); render(); return; }
    const baseUrl = d.base_url.trim();
    if (!/^https?:\/\//.test(baseUrl)) { fail(id, t("settings.err.url")); render(); return; }
    busy = true; fail(id, ""); render();
    try {
      const payload: { base_url: string; type: string; key?: string; credential_ref?: string } = {
        base_url: baseUrl, type: d.type,
      };
      if (d.key !== "") payload.key = d.key;
      else if (d.credential_ref !== undefined) payload.credential_ref = d.credential_ref;
      const out = await deps.settings.discover(payload);
      const models = (out.models as unknown as ProviderModel[]) ?? [];
      if (models.length === 0) { fail(id, t("settings.err.emptyModels")); return; }
      picker = { id, models, query: "", selected: {} };
    } catch (err) {
      fail(id, t("settings.err.fetch", { msg: err instanceof Error ? err.message : String(err) }));
    } finally {
      busy = false; render();
    }
  }

  function uniqueId(base: string): string {
    const stem = slugId(base) || "provider";
    let pid = stem;
    let n = 2;
    while (providers()[pid] !== undefined) { pid = `${stem.slice(0, 29)}-${n++}`; }
    return pid;
  }

  async function saveProvider(id: string): Promise<void> {
    if (busy) return;
    const d = draftOf(id);
    const kf = keyFailure(d.key);
    if (kf !== "") { fail(id, kf); render(); return; }
    const isDraft = id === "__draft__";
    const pid = isDraft
      ? uniqueId(d.matched ?? d.display_name ?? hostOf(d.base_url) ?? "provider")
      : id;
    const entry: ProviderEntry = { type: d.type };
    const baseUrl = d.base_url.trim();
    if (baseUrl !== "") entry.base_url = baseUrl;
    const name = d.display_name.trim();
    if (name !== "") entry.display_name = name;
    if (typeof d.credential_ref === "string") entry.credential_ref = d.credential_ref;
    const models = d.models.filter((m) => m.id.trim() !== "").map((m) => ({ ...m, id: m.id.trim() }));
    if (models.length > 0) entry.models = models;
    const next = { ...providers(), [pid]: entry };
    busy = true; fail(id, ""); conflict = false; render();
    try {
      const out = await deps.settings.writeConfig({ providers: next }, { replace: ["providers"], revision: revision() });
      config = { ...(config ?? { values: {}, sources: {} }), revision: out.revision };
      if (d.key !== "" && refOf(pid, entry) !== "") {
        const ref = refOf(pid, entry);
        const saved = await deps.settings.credentialSet(ref, d.key);
        statuses[ref] = saved;
        d.key = "";
      }
      if (isDraft) delete drafts[id];
      expanded = null; picker = null; notice = t("settings.saved");
      await refresh();
    } catch (err) {
      const described = describeError(err);
      conflict = described.conflict;
      fail(pid === id ? id : pid, described.message);
      render();
    } finally {
      busy = false;
    }
  }

  async function removeProvider(id: string): Promise<void> {
    if (busy) return;
    const next = { ...providers() };
    delete next[id];
    busy = true; conflict = false; render();
    try {
      const out = await deps.settings.writeConfig({ providers: next }, { replace: ["providers"], revision: revision() });
      config = { ...(config ?? { values: {}, sources: {} }), revision: out.revision };
      delete drafts[id];
      expanded = null; confirmDel = null; notice = t("settings.deleted");
      await refresh();
    } catch (err) {
      const described = describeError(err);
      conflict = described.conflict;
      fail(id, described.message);
      confirmDel = null;
      render();
    } finally {
      busy = false;
    }
  }

  function close(): void {
    open = false;
    overlay.setAttribute("hidden", "hidden");
    // U5：焦点归还（触发打开的元素——键盘用户不丢失位置；选择器重解析）
    if (lastFocusedSelector !== null) {
      document.querySelector<HTMLElement>(lastFocusedSelector)?.focus();
    }
    lastFocusedSelector = null;
  }

  return {
    async open(): Promise<void> {
      if (open) return;
      open = true;
      // U5：记录触发元素（存 data-st 选择器——重渲染后仍可解析；关闭时归还）
      const _ae = document.activeElement;
      const _st = _ae instanceof HTMLElement ? _ae.getAttribute("data-st") : null;
      lastFocusedSelector = _st ? `[data-st="${_st}"]` : null;
      overlay.removeAttribute("hidden");
      expanded = null; picker = null; confirmDel = null; error = {}; notice = "";
      busy = true; render();
      try {
        const [schemaOut, catalogOut] = await Promise.all([
          deps.settings.schema(),
          deps.settings.catalog().catch((err: unknown) => {
            notice = t("settings.catalogFailed", { msg: err instanceof Error ? err.message : String(err) });
            return { providers: [] };
          }),
        ]);
        schema = schemaOut.fields;
        catalog = (catalogOut.providers as CatalogEntry[]) ?? [];
        await refresh();
      } catch (err) {
        notice = describeError(err).message;
        render();
      } finally {
        busy = false;
      }
      // U5：初始聚焦必须在**最终渲染之后**（refresh 会重建 DOM——先聚焦会随
      // 重建丢失）；此处 DOM 已就绪，焦点落在搜索框（键盘可直接导航）
      overlay.querySelector<HTMLInputElement>('[data-st="st-search"]')?.focus();
    },
    close,
  };
}
