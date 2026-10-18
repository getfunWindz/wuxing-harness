import { asset } from '@kit.AssetStoreKit';
import { util } from '@kit.ArkTS';

/**
 * 令牌安全存储：HarmonyOS 关键资产存储（AssetStore），系统级加密，不落明文。
 * 失败向上抛（配置页显式提示），不静默降级。
 */
const ALIAS: string = 'wuxing.shell.token';

function toBytes(text: string): Uint8Array {
  return new util.TextEncoder().encodeInto(text);
}

function toText(data: Uint8Array): string {
  return util.TextDecoder.create('utf-8', { ignoreBOM: true }).decodeToString(data);
}

export class TokenVault {
  static async save(value: string): Promise<void> {
    try {
      await asset.remove(TokenVault.aliasQuery());
    } catch (err) {
      // 旧条目不存在（24000002）——忽略；其它错误在 add 时暴露
    }
    const attr: asset.AssetMap = new Map();
    attr.set(asset.Tag.SECRET, toBytes(value));
    attr.set(asset.Tag.ALIAS, toBytes(ALIAS));
    attr.set(asset.Tag.ACCESSIBILITY, asset.Accessibility.DEVICE_FIRST_UNLOCKED);
    await asset.add(attr);
  }

  static async load(): Promise<string | null> {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, toBytes(ALIAS));
    query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ALL);
    try {
      const result: Array<asset.AssetMap> = await asset.query(query);
      if (result.length === 0) {
        return null;
      }
      const secret = result[0].get(asset.Tag.SECRET) as Uint8Array | undefined;
      return secret === undefined ? null : toText(secret);
    } catch (err) {
      // 未找到（24000002）或资产损坏：按「无已保存令牌」处理，由配置页提示重填
      return null;
    }
  }

  static async clear(): Promise<void> {
    try {
      await asset.remove(TokenVault.aliasQuery());
    } catch (err) {
      // 无可删条目：忽略
    }
  }

  private static aliasQuery(): asset.AssetMap {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, toBytes(ALIAS));
    return query;
  }
}
