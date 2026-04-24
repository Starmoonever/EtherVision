# aave_liquidation

多协议清算风险监测与仓位分析仓库。

当前仓库同时承载：

- 后端采集与 API：Aave、Compound、Morpho、JustLend、MakerDAO
- 前端看板：个人仓位分析、历史回放、市场风险图表
- PostgreSQL / ClickHouse 相关数据处理脚本与迁移

如果你是第一次接手这个仓库，建议先看本文件，再进入 [backend/README.md](backend/README.md) 和 [frontend/README.md](frontend/README.md)。

## 仓库结构

```text
aave_liquidation/
├── AGENTS.md
├── README.md
├── backend/
└── frontend/
```

### 模块划分

- `backend/`
  - 统一后端服务
  - 协议采集、数据库写入、历史回放、风险分析 API
- `frontend/`
  - React + Vite 前端
  - 消费统一后端 API，按协议切换个人与市场视图
- `AGENTS.md`
  - 仓库规则、地址存储约定、agent 注意事项

## 支持的协议模块

### Aave

- 地址同步
- 全量 / 增量仓位采集
- 历史仓位回放
- ETH 价格相关清算分析

### Compound

- 市场状态查询
- 治理参数与配置版本
- 用户仓位快照与回放

### Morpho

- Morpho Blue 当前仓位查询
- 市场与资产信息缓存

### JustLend

- 当前仓位与个人风险视图
- 交易回放与趋势分析
- 说明文案与 effect 解析

### MakerDAO

- Vault 个人仓位查询
- 抵押债务、健康因子与清算价格展示

## 运行前提

### 后端

- Python 3.12+
- `uv`
- PostgreSQL
- 可选：ClickHouse

### 前端

- Node.js 18+
- `pnpm`

## 快速开始

### 1. 安装后端依赖

```bash
cd backend
uv sync
```

### 2. 配置后端

创建并编辑：

- `backend/config.yaml`
- 如前端需要覆盖 API 地址，创建 `frontend/.env.local`

后端配置示例与字段说明见 [backend/README.md](backend/README.md)。

### 3. 启动后端 API

```bash
cd backend
uv run api
```

默认监听 `0.0.0.0:8000`。

### 4. 安装并启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

默认开发地址一般为 `http://localhost:5173`。

## 典型工作流

### 首次接手并跑通项目

1. 阅读本文件，确认仓库结构
2. 按 [backend/README.md](/Users/foxonmars/Documents/Github%20Repositories/aave_liquidation/backend/README.md) 配置后端
3. 启动 `uv run api`
4. 按 [frontend/README.md](/Users/foxonmars/Documents/Github%20Repositories/aave_liquidation/frontend/README.md) 配置并启动前端
5. 在前端确认协议切换、个人分析和市场图表可访问

### 做后端协议相关开发

1. 先确认目标协议目录：
   - `aave_crawler`
   - `compound_crawler`
   - `morpho_crawler`
   - `justlend_crawler`
2. 同步核对：
   - CLI 命令
   - API 路由
   - 数据库落表方式
   - 对应测试
3. 如改动影响运行方式、配置或行为，更新 `backend/README.md`

### 做前端开发

1. 检查 `frontend/src/protocols/registry.ts` 的协议注册
2. 检查 `frontend/src/api/` 的接口绑定
3. 检查对应页面组件与图表组件
4. 如改动影响环境变量、构建流程或页面结构，更新 `frontend/README.md`

## 文档地图

- [AGENTS.md](AGENTS.md)
  - 仓库规则、地址存储标准、agent 注意事项
- [backend/README.md](backend/README.md)
  - 后端运行、模块结构、数据库与测试说明
- [frontend/README.md](frontend/README.md)
  - 前端运行、环境变量、目录结构与联调说明

## 重要约定

- 文档统一使用简体中文
- 根 README 只做仓库入口和导航，不承担全部后端细节
- 地址存储存在历史遗留格式；后续标准以 [AGENTS.md](AGENTS.md) 为准
- 外部维护的 schema 或链上历史表，不应默认属于本仓库迁移管理范围

## 测试与校验

常用命令：

```bash
cd backend
uv run pytest tests/ -q
```

```bash
cd frontend
pnpm build
```

更细的测试、迁移与脚本说明见各子目录 README。
