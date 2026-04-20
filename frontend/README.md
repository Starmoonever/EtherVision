# 前端说明

`frontend/` 是本仓库的前端应用目录，负责消费统一后端 API，并按协议提供个人仓位分析与市场风险视图。

当前前端不是单一 Aave 页面，已经包含：

- Aave
- Compound
- Morpho
- JustLend

## 技术栈

- React 18
- TypeScript
- Vite
- pnpm

## 安装依赖

```bash
cd frontend
pnpm install
```

## 运行前提

- Node.js 18+
- `pnpm`
- 可访问的后端 API

如果后端尚未启动，请先按根 [README.md](../README.md) 或 [backend/README.md](../backend/README.md) 启动后端。

## 环境变量

前端通过 `VITE_API_BASE_URL` 连接后端。

默认情况下可在 `.env` 或本地覆盖文件中设置。推荐在 `frontend/.env.local` 中覆盖本地环境值：

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api
```

如果后端运行在其他地址，改成对应地址即可。

注意：

- `.env.local` 不应提交
- `VITE_*` 变量会在构建时注入
- 修改 API 地址后，如需生产产物生效，需要重新构建

## 启动开发服务器

```bash
cd frontend
pnpm dev
```

如需局域网访问：

```bash
pnpm dev --host
```

默认开发地址通常是 `http://localhost:5173`。

## 构建与预览

### 生产构建

```bash
pnpm build
```

构建产物位于 `frontend/dist/`。

### 本地预览

```bash
pnpm preview
```

如需局域网访问：

```bash
pnpm preview --host
```

## 目录结构

```text
frontend/
├── README.md
├── package.json
├── src/
│   ├── api/
│   ├── components/
│   ├── hooks/
│   ├── protocols/
│   ├── shared/
│   ├── theme/
│   └── App.tsx
└── public/
```

### 关键目录

- `src/App.tsx`
  - 应用根组件
  - 负责协议切换和主视图切换
- `src/protocols/`
  - 协议注册表
  - 决定每个协议如何挂载到主应用
- `src/api/`
  - 后端 API 客户端
  - 已按协议和功能拆分
- `src/components/`
  - 图表、输入组件、个人看板、市场看板
- `src/shared/`
  - 共享组件、类型与通用逻辑
- `src/theme/`
  - 主题变量与样式 token

## 当前页面组织方式

应用顶层由两个维度驱动：

- 协议切换
- 视图切换，例如个人分析与市场分析

当前协议相关 UI 已拆分为多套组件，不应再把前端文档写成“只有 Aave 的面板”。

## API 依赖

前端通过统一后端 API 获取数据。实际接口由 `src/api/` 中的各个客户端封装。

常见分类包括：

- 用户当前仓位
- 市场风险图表
- 历史价格
- 历史回放
- Morpho 市场静态配置与实时状态
- Morpho 搜索历史
- Compound 与 JustLend 的专用接口

其中 Morpho 市场页当前依赖两类接口：

- 市场列表：用于拉取 `market_id`、抵押/借款代币、LLTV、oracle、IRM 等静态配置
- 市场状态：用于拉取总抵押、总债务、Supply APY、Borrow APY、风险标记与清算参考价等实时字段

维护时建议：

1. 先看 `src/api/`
2. 再看 `src/protocols/registry.ts`
3. 最后看具体页面组件

## 开发建议

### 新增协议页面

通常需要同时检查：

- `src/protocols/registry.ts`
- `src/api/` 下的请求封装
- 对应协议组件
- 顶部切换与布局兼容性

### 改图表或交互

优先核对：

- 组件是否只服务某一个协议
- API 返回字段是否已被多个组件共享
- 样式 token 是否已有统一变量可复用

### 改接口地址或联调方式

同步更新：

- 本文件
- 根 `README.md`

如果改的是后端行为，还应更新 `backend/README.md`。

## 部署说明

前端构建产物是纯静态资源，可部署到任意静态托管环境。

部署前确认：

- `VITE_API_BASE_URL` 已指向正确后端
- 后端已开放对应协议 API
- 若使用前端路由回退，静态服务需把未知路径回退到 `index.html`

## 常见坑

### 1. 不要把前端当成单协议页面

当前应用已经通过协议注册表统一承载多个协议。改根组件或导航时，先确认不会破坏其他协议页面。

### 2. 环境变量是构建时注入

只改运行环境而不重新构建，生产产物不会自动更新 API 地址。

### 3. API 客户端已经分层

优先改 `src/api/`，不要把请求逻辑散落到图表组件里。

### 4. 文档保持分层

- 仓库入口与启动总览：根 `README.md`
- 前端运行与结构：本文件
- 后端运行与接口来源：`backend/README.md`
