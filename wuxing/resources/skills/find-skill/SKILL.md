---
name: find-skill
description: 发现并安装新技能——用户需要寻找技能或不知该用什么时使用（查询 SkillRadar，人工确认后安装）
level: domain
version: 0.1
---

# Find Skill

> 唯一内置技能：帮助新用户发现适合自己的 skill 并安装。

## 你要做什么

当你被告知「找技能 / 需要什么技能 / 帮我装个技能」时，按下述三步执行：

1. **提取信息**：从用户问题中提取任务目标（必选）、任务约束（可选）、关键词 3-10 个（逗号分隔）、候选数量（默认 5）。
2. **查询**：切换到本技能所在目录（包含本 SKILL.md），执行：
   ```bash
   python scripts/discover.py --goal "<任务目标>" --keywords "<k1,k2>" [--constraints "<约束>"] [--max-results 5]
   ```
   查询源为 SkillRadar Discover（可用配置 `skill_radar_url` 覆盖，默认 https://api.skillradar.quest）。
3. **展示与确认**：
   - 将候选结果（名称+描述）展示给用户；
   - **必须获得用户明确同意后才安装**（除非 auto_confirm=True——人工介入哲学：安装影响后续所有任务）；
   - 用户确认后，按候选的安装说明下载并写入 `~/.wuxing/skills/<name>/`（SKILL.md + scripts/），安装完成后验证注册表可见。

## 注意

- 查询失败（网络/服务不可达）：如实告知用户，不要伪造候选。
- 安装前校验 SKILL.md frontmatter（name/description 必填），破损则拒绝安装。
