/** 设置数据层（P2-S2）：配置（含 revision 冲突）/ 凭据（写只读）/ 供应商目录 / 模型发现。
    —— 唯一出网经 connection/rest；失败经命令总线可见（不吞）。 */
import type {
  ConfigDto,
  CredentialDto,
  DiscoverModelsDto,
  ProviderCatalogDto,
} from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { WritableRestClient } from "../connection/rest.ts";

/** GET /api/v1/config/schema 的响应形状（字段声明）。 */
export interface FieldSpecLike {
  readonly name: string;
  readonly type: string;
  readonly enum?: readonly string[] | null;
  readonly default?: unknown;
}

/** PUT /api/v1/config 的响应形状（写入结果——含新 revision）。 */
export interface ConfigWriteResult {
  ok: boolean;
  scope: string;
  path: string;
  written: string[];
  revision: string;
}

export interface SettingsService {
  readConfig(): Promise<ConfigDto>;
  writeConfig(
    values: Record<string, unknown>,
    opts?: { replace?: readonly string[]; revision?: string },
  ): Promise<ConfigWriteResult>;
  credentialGet(ref: string): Promise<CredentialDto>;
  credentialSet(ref: string, value: string): Promise<CredentialDto>;
  credentialDelete(ref: string): Promise<CredentialDto>;
  catalog(): Promise<ProviderCatalogDto>;
  schema(): Promise<{ fields: readonly FieldSpecLike[] }>;
  discover(payload: {
    base_url: string;
    type: string;
    key?: string;
    credential_ref?: string;
  }): Promise<DiscoverModelsDto>;
}

/** 冲突识别（视图不得直连 connection 层——错误形状判定收在服务层）。 */
export function isConfigConflict(err: unknown): boolean {
  return (
    typeof err === "object" && err !== null && "code" in err
    && (err as { code?: unknown }).code === "config/conflict"
  );
}

export function createSettingsService(deps: {
  rest: WritableRestClient;
  commands: CommandBus;
}): SettingsService {
  const cred = (ref: string): string => `/api/v1/credentials/${encodeURIComponent(ref)}`;
  return {
    readConfig: () =>
      deps.commands.run("settings.read", () =>
        deps.rest.get<ConfigDto>("/api/v1/config")),

    writeConfig: (values, opts = {}) =>
      deps.commands.run("settings.write", () => {
        const body: Record<string, unknown> = { values };
        if (opts.replace && opts.replace.length > 0) body.replace = [...opts.replace];
        if (opts.revision !== undefined) body.revision = opts.revision;
        return deps.rest.put<ConfigWriteResult>("/api/v1/config?scope=user", body);
      }),

    credentialGet: (ref) =>
      deps.commands.run("settings.credential", () =>
        deps.rest.get<CredentialDto>(cred(ref))),

    credentialSet: (ref, value) =>
      deps.commands.run("settings.credential", () =>
        deps.rest.put<CredentialDto>(cred(ref), { value })),

    credentialDelete: (ref) =>
      deps.commands.run("settings.credential", () =>
        deps.rest.del<CredentialDto>(cred(ref))),

    catalog: () =>
      deps.commands.run("settings.catalog", () =>
        deps.rest.get<ProviderCatalogDto>("/api/v1/providers/catalog")),

    schema: () =>
      deps.commands.run("settings.schema", () =>
        deps.rest.get<{ fields: readonly FieldSpecLike[] }>("/api/v1/config/schema")),

    discover: (payload) =>
      deps.commands.run("settings.discover", () =>
        deps.rest.post<DiscoverModelsDto>("/api/v1/providers/discover", payload)),
  };
}
