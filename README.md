# 知识蒸馏工作台

本项目是一个**本地优先的知识蒸馏编译工作台**：把用户明确选择的 Markdown/TXT 资料，经过来源快照、Evidence 审核、Capability/Mechanism 组织、SkillPlan 编译、导出和场景评测，整理成可追溯、可审核、可复用的 AI Skill。

## 当前状态

- MVP：已完成 S1–S5 本地闭环。
- GitHub：`https://github.com/fanfan9396-oss/-123`
- 当前分支：`main`
- 当前版本：`0.1.0 MVP`
- 部署形态：Windows 本机、loopback、本地 SQLite。
- 许可证：尚未选择正式开源许可证；在正式选择前，不默认授予再分发、修改或商业使用许可。

## 产品流程

```text
本地 Markdown/TXT
  → 不可变 Source/Excerpt 快照
  → Evidence 候选与人工审核
  → Capability / Mechanism
  → SkillPlan
  → GeneratedSkill 编译预览
  → SKILL.md / references / source-map 导出
  → Scenario
  → Evaluation
  → QualityReport
```

测试通过只表示当前场景或结构检查通过，不代表 Skill 在所有现实场景中有效，也不代表蒸馏内容客观为真。

## 主要能力

- 本地项目和蒸馏任务管理；
- Markdown/TXT 资料导入、规范化、SHA-256 指纹和来源快照；
- Evidence 创建、来源绑定、人工审核和 source-map；
- Capability/Mechanism 聚类与审核；
- SkillPlan 审批和节点级 Evidence 映射；
- `SKILL.md`、`references/capabilities.md`、`references/source-map.json` 编译与导出；
- Scenario 场景集、人工 Evaluation 和版本指纹；
- 确定性 QualityReport：可追溯性、边界、导出结构、许可证/隐私风险检查。

## 安全和数据边界

- 默认只处理用户在浏览器中明确选择的文件；不会按服务端路径扫描资料。
- 原始资料快照保存在本地 SQLite；不会自动上传到外部模型或第三方服务。
- 当前版本不包含登录、多人协作、云同步、公开 API、队列、公网部署或自动自进化。
- 外部模型适配器尚未启用；不要把密钥写入源码、数据库、日志或生成物。
- `data/`、`output/`、`dev-docs/` 和 `AGENTS.md` 是本地/内部内容，不会进入公开代码提交。

## 环境要求

推荐：

- Windows 10/11；
- Python 3.12+；
- Node.js 20+；
- npm 10+；
- 可用浏览器（Chrome、Edge 或其他现代浏览器）。

## 快速启动

在项目根目录执行：

```powershell
# 1. 安装 Python 依赖
python -m pip install -r backend\requirements.txt

# 2. 安装前端依赖并构建静态资源
cd frontend
npm install
npm run check
npm run build
cd ..

# 3. 启动本地服务
python backend\run.py
```

启动后访问：

```text
http://127.0.0.1:8000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

预期返回类似：

```json
{"status":"ok","schema_version":8}
```

也可以直接运行：

```powershell
.\scripts\start-workbench.ps1
```

前提是已经安装 `backend\requirements.txt` 中的 Python 依赖，并且前端已经执行过 `npm run build`。

## 验证项目

推荐在项目根目录执行：

```powershell
.\scripts\verify-local.ps1
```

等价命令：

```powershell
cd backend
python -B -m unittest discover -s tests
python -B -m compileall app tests
cd ..

cd frontend
npm run check
npm run build
cd ..
```

当前验收基线：

- Python unittest：31/31；
- TypeScript check：通过；
- Vite build：通过；
- Python compileall：通过；
- S5 真实浏览器流程：通过。

## 开发目录

```text
backend/       FastAPI、SQLite、迁移和测试
frontend/      React、TypeScript、Vite
scripts/       Windows 启动与本地验证脚本
data/          本地 SQLite 和运行数据，默认忽略
output/        本地导出和验收产物，默认忽略
dev-docs/      内部开发真源，默认忽略
```

## 当前明确不做

本仓库当前不承诺：

- 公网部署或在线 SaaS；
- 自动调用外部模型；
- 自动批准或自动修改 approved Evidence/Capability/SkillPlan；
- 自动把评测失败变成知识修订；
- 多人协作、账号、支付、云同步；
- 对受版权或隐私约束资料的公开再分发。

## 许可证说明

本项目目前尚未选择正式开源许可证。若要复制、修改、再分发或用于商业用途，请先取得项目维护者明确许可，直到仓库添加正式 LICENSE 文件。

## 反馈

请在 GitHub Issue 中提供：

1. 操作系统和 Python/Node 版本；
2. 执行的命令；
3. 完整错误信息；
4. 是否使用了真实资料（不要上传私密原文或密钥）；
5. 最小可复现步骤。
