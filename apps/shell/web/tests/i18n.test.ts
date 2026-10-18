import { test } from "node:test";
import assert from "node:assert/strict";

import { DICTS, getLang, onLangChange, setLang, t } from "../src/views/i18n.ts";

test("字典键集合一致（zh/en 不允许静默缺翻译）", () => {
  const zh = Object.keys(DICTS.zh).sort();
  const en = Object.keys(DICTS.en).sort();
  assert.deepEqual(en, zh, `zh-only=${zh.filter((k) => !en.includes(k))} en-only=${en.filter((k) => !zh.includes(k))}`);
});

test("t()：默认中文 + {param} 插值 + 未知键回退键名", () => {
  setLang("zh");
  assert.equal(t("settings.prov.save"), "保存");
  assert.equal(t("settings.prov.deleteConfirm", { name: "demo" }),
               "删除「demo」？需重新添加才能使用");
  assert.equal(t("settings.nonexistent.key"), "settings.nonexistent.key");
});

test("语言切换：取值生效 + 订阅者被通知 + 可退订", () => {
  setLang("zh");
  let fired = 0;
  const off = onLangChange(() => { fired += 1; });
  setLang("en");
  assert.equal(getLang(), "en");
  assert.equal(t("settings.prov.save"), "Save");
  assert.equal(fired, 1);
  off();
  setLang("zh");
  assert.equal(fired, 1, "退订后不再通知");
  assert.equal(t("settings.prov.save"), "保存");
});

const CONFIRM_SCOPE = [
  "dock.purgeConfirm", "dock.skills.removeOk", "rail.session.deleteOk",
  "settings.maint.clearEventsConfirm", "settings.maint.cleanCacheConfirm",
  "settings.browserAllow.revokeConfirm", "settings.browserIdentity.clearConfirm",
  "settings.prov.deleteConfirm", "stream.confirmTitle", "stream.confirmReason",
  "stream.rejectPlaceholder", "stream.answerTitle",
] as const;

test("确认面文案：禁术语 + 后果可见（通俗化 lint）", () => {
  const banned = ["碎片", "单元", "域", "指纹", "准入", "阈值", "溯源", "DAG"];
  for (const key of CONFIRM_SCOPE) {
    const value = DICTS.zh[key];
    assert.ok(value !== undefined, `缺键 ${key}`);
    for (const term of banned) {
      assert.ok(!value.includes(term), `${key} 含禁词「${term}」：${value}`);
    }
  }
  assert.equal(DICTS.zh["dock.purgeConfirm"], "彻底删除（不可恢复）");
  assert.equal(DICTS.zh["settings.browserIdentity.clearConfirm"],
               "清除（相关站点需重新登录）");
});
