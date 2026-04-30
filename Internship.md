# 实习项目总结：EtherVision 多协议 DeFi 风险监测与仓位分析系统

## 一、项目概述

本项目是我在实习期间独立完成的一个多协议 DeFi 风险监测与仓位分析系统。项目最初围绕 Aave 清算风险分析展开，随后扩展为一个统一支持 Aave、Compound、Morpho、JustLend、MakerDAO 等协议的链上数据分析平台。

系统目标是将不同 DeFi 协议中分散、复杂、实时变化的仓位数据、市场状态、价格数据、清算参数和风险指标进行统一采集、缓存、计算和展示，使用户能够从前端页面中快速理解：

- 某个地址在不同协议中的资产、债务、抵押和清算风险；
- 某个市场或协议整体的资金规模、借贷结构、健康因子分布和风险仓位；
- 链上价格变化对仓位清算风险的影响；
- 大户地址、系统仓位、特殊 Vault、RWA 与系统内部账户等非普通用户仓位的状态。

项目由后端数据采集与 API 服务、前端 React 可视化应用、数据库缓存与历史回放逻辑组成。整体上它不是一个简单的页面项目，而是一个完整的链上数据分析工具。

## 二、技术栈

### 后端

- Python 3.12
- FastAPI
- web3.py
- asyncpg
- SQLAlchemy AsyncSession
- Alembic
- PostgreSQL
- ClickHouse
- uv
- pytest

后端负责链上数据读取、协议数据解析、数据库缓存、历史回放和统一 API 暴露。

### 前端

- React 18
- TypeScript
- Vite
- pnpm
- Recharts
- ECharts
- viem
- CSS Modules / 协议级 CSS 拆分

前端负责协议切换、个人账户分析、市场宏观评估、风险表格、交互式图表和状态说明。

## 三、系统架构

项目采用前后端分离架构。

```text
链上 RPC / 外部价格源 / 数据库缓存
        ↓
Python 数据采集与服务层
        ↓
FastAPI 统一 API
        ↓
React + TypeScript 前端
        ↓
个人仓位分析 / 市场风险看板 / 历史回放 / 大户风险表
```

仓库结构如下：

```text
aave_liquidation/
├── backend/
│   ├── aave_crawler/
│   ├── compound_crawler/
│   ├── morpho_crawler/
│   ├── justlend_crawler/
│   ├── makerdao_crawler/
│   ├── crawler_shared/
│   ├── alembic/
│   └── tests/
├── frontend/
│   ├── src/api/
│   ├── src/components/
│   ├── src/protocols/
│   ├── src/shared/
│   └── src/theme/
├── README.md
├── backend/README.md
├── frontend/README.md
└── AGENTS.md
```

其中 `crawler_shared` 承载统一 API、共享数据库连接、价格查询服务和公共工具；`frontend/src/protocols` 通过协议注册表统一管理多个协议页面。

## 四、后端实现内容

### 1. 统一 API 服务

我使用 FastAPI 设计了统一的后端服务入口，将不同协议的查询能力挂载到统一 API 下。例如：

- `/api/price`
- `/api/price/period`
- `/api/justlend/position`
- `/api/justlend/positions`
- `/api/justlend/market/state`
- `/api/morpho/market/state`
- `/api/makerdao/position`
- `/api/makerdao/system/position`
- `/api/makerdao/positions`
- `/api/makerdao/ilks`

统一 API 的好处是前端可以通过一致的请求封装消费数据，不需要关心后端不同协议内部的数据来源和解析方式。

### 2. 数据库访问模式

后端同时使用两种数据库访问模式：

- SQLAlchemy AsyncSession：用于结构化 API 查询、ORM 模型和迁移管理；
- asyncpg Pool：用于批量写入、回放缓存、性能敏感查询和脚本任务。

这种设计兼顾了可维护性和性能。API 查询可以保持清晰结构，批量采集和缓存回填则可以直接使用 asyncpg 提升效率。

### 3. 统一价格服务

我实现了统一价格接口：

- `GET /api/price`
- `GET /api/price/period`

价格服务支持：

- Ethereum 资产价格查询；
- TRON 资产价格查询；
- 当前价格与历史价格；
- 15 分钟时间桶缓存；
- DeFiLlama、链上 Oracle、本地缓存、包装资产派生价格、CoinGecko 等多层兜底；
- wstETH 等包装资产通过链上汇率派生价格。

在前端 MakerDAO 价格缓冲指标中，我进一步加入了失败缓存：如果某个 `collateral_token_address` 价格请求失败，前端会在短时间内跳过重复请求，避免后端和 RPC 被无效请求刷屏。

### 4. Aave 模块

Aave 是项目最早支持的协议。我完成了：

- 用户地址同步；
- Aave V2 / V3 仓位数据采集；
- 当前仓位快照；
- 日级历史仓位；
- ETH 价格下跌场景下的清算分析；
- WETH 借款场景下 ETH 上涨导致的清算分析；
- 清算价格 `liq_price` 与 `liq_price_rise` 的区分；
- 历史回放和清算趋势图所需 API。

Aave 模块中重点处理了 V2 / V3 Oracle 单位差异、ETH 计价分支和不同资产方向导致的清算逻辑差异。

### 5. Compound 模块

Compound 模块覆盖 V2 / V3 的市场与仓位分析。我完成了：

- 市场状态查询；
- 治理参数和配置版本读取；
- 用户仓位快照；
- 当前仓位缓存；
- 历史回放；
- V2 / V3 独立缓存逻辑，避免不同版本之间复用错误数据；
- 价格、抵押率、健康状态等字段在前端展示前的标准化。

Compound 模块中一个重要工作是兼容历史数据库中地址字段的不同存储格式，并在 API 层做统一输出。

### 6. Morpho 模块

Morpho 模块主要围绕 Morpho Blue 市场、个人仓位和 Vault 分析。我完成了：

- Morpho 当前用户仓位查询；
- Morpho 市场列表分页；
- 市场详情按需懒加载；
- 单个 market id 查询；
- token 价格补充；
- Morpho Vault V1 / V2 分析页面；
- V2 warning 等级展示；
- Vault allocation 与 adapter 结构展示；
- 动态清算图表；
- 历史仓位变化图。

为了避免页面一次性请求大量市场详情，我将 Morpho 市场状态改为“展开后懒加载”。这样既降低了后端压力，也明显改善了前端首屏性能。

### 7. JustLend 模块

JustLend 模块覆盖 TRON 链上的借贷市场和用户仓位。我完成了：

- TRON Base58 地址的用户仓位查询；
- JustLend 市场列表；
- 当前市场状态；
- 市场历史状态；
- 个人账户分析；
- 大户 / 风险仓位分页表；
- 按资产、仓位类型、抵押状态和风险指标筛选排序；
- 交易级历史回放；
- 资产结构与健康因子展示；
- TRON 价格缓存与市场快照逻辑联动。

JustLend 前端中，我重点做了风险仓位主表、健康因子闪烁规则、风险说明小问号、资产筛选、分页、地址复制、抽屉详情等交互。

### 8. MakerDAO 模块

MakerDAO 是项目后期重点扩展的协议。我完成了普通 Vault、系统 urn、ilk 元数据和全局仓位总览的前后端对接。

后端接口包括：

- `GET /api/makerdao/ilks`
- `GET /api/makerdao/ilk`
- `GET /api/makerdao/position`
- `GET /api/makerdao/system/position`
- `GET /api/makerdao/positions`

前端页面包括：

- MakerDAO 个人账户分析；
- 普通仓位 / 系统仓位切换；
- 系统 urn 查询；
- 普通仓位与系统仓位独立缓存；
- Vault 数量、总抵押、总债务、健康因子、清算价格展示；
- 协议抵押资产导航；
- MakerDAO 仓位总览；
- 普通 Vault 与系统 urn 统一分页表；
- ILK 筛选、排序、仓位范围、健康状态和空仓过滤；
- URN 地址复制；
- 价格缓冲指标。

其中 MakerDAO 宏观市场评估页面做了两个核心模块：

1. 协议抵押资产导航
   用于展示 `ilk`、`vault_type`、`gem_symbol`、`gem_address`、`updated_at` 等元数据，并按 Native Crypto、RWA、Direct Deposit / D3M、Stablecoins、LP / Structured、System Internal 等类型分组。

2. 仓位总览
   通过 `/api/makerdao/positions` 分页展示普通用户 Vault 和系统 urn 仓位。主表展示 URN、Ilk、抵押价值、债务价值、健康因子、清算价格、价格缓冲和状态。

价格缓冲公式为：

```text
(当前资产价格 - 清算价格) / 当前资产价格
```

该指标用于衡量当前资产价格距离清算价格的安全空间。前端只对有 `collateral_token_address` 的仓位请求价格；没有标准 token 地址的 RWA、Allocator、系统内部仓位直接显示 `--`，避免无意义的价格请求。

## 五、前端实现内容

### 1. 协议注册表架构

前端不是单协议页面，而是通过协议注册表统一挂载多个协议：

```ts
export const protocolRegistry = [
  { id: 'aave', label: 'Aave', Root: AaveProtocolRoot },
  { id: 'compound', label: 'Compound', Root: CompoundProtocolRoot },
  { id: 'morpho', label: 'Morpho', Root: MorphoProtocolRoot },
  { id: 'justlend', label: 'JustLend', Root: JustLendProtocolRoot },
  { id: 'makerdao', label: 'MakerDAO', Root: MakerDaoProtocolRoot },
];
```

用户可以在顶部切换协议和视图，例如个人账户分析、宏观市场评估、Vault 分析等。

为了避免非当前协议页面后台发请求，我为协议 Root 和页面请求逻辑增加了 `active` 守卫，使页面只在被激活时请求数据。

### 2. API 客户端拆分

我将前端 API 按协议和功能拆分：

- `api/user.ts`
- `api/liquidation.ts`
- `api/compound.ts`
- `api/morpho.ts`
- `api/justlend.ts`
- `api/makerdao.ts`
- `api/price.ts`

每个 API 客户端负责：

- 类型定义；
- URL 参数构造；
- 请求缓存；
- inflight 去重；
- 错误处理；
- DataWithMeta 元数据返回。

例如 MakerDAO 普通仓位、系统仓位、ilk 列表、positions 总览分别使用独立缓存 key，避免不同查询之间互相污染。

### 3. 前端页面与组件

我实现了多类页面：

- 个人账户分析页面；
- 市场宏观评估页面；
- 历史回放页面；
- 大户 / 风险仓位表；
- Vault 分析页面；
- 动态清算模拟图；
- 资产结构图；
- 市场状态趋势图。

页面中包含大量可复用交互：

- 地址输入与历史记录；
- 分段按钮；
- 搜索框；
- 分页器；
- 复制地址；
- 抽屉 / 展开详情；
- 小问号指标说明；
- 健康因子颜色与闪烁提示；
- 图表 tooltip；
- 数据来源与缓存状态展示。

### 4. 样式重构

项目早期 `App.css` 中样式耦合较重，多个协议页面复用同一类名，导致视觉效果联动严重。我分阶段进行了前端样式重构：

- `App.css` 只保留应用级通用布局；
- 各协议样式收拢到 `frontend/src/protocols/{protocol}/styles.css`；
- JustLend 进一步拆分为 `controls.css`、`dashboard.css`、`analytics.css`、`portrait.css`；
- Morpho 进一步拆分为 `base.css`、`market.css`、`vault.css`、`tables.css`、`history.css`、`risk-gauges.css`；
- MakerDAO 页面使用独立样式，不直接套用 JustLend 组件，但保持一致的视觉语言。

通过这轮重构，协议页面之间的 CSS 耦合显著降低，后续新增页面时更容易控制影响范围。

### 5. 构建性能优化

前端生产构建中曾出现 chunk 过大问题。我完成了：

- Vite manualChunks 拆包；
- React、Recharts、ECharts、viem、vendor 分离；
- Morpho 动态清算图懒加载；
- ECharts 改为按需注册 LineChart、Grid、Tooltip、CanvasRenderer 等模块。

优化后构建产物不再出现主要 chunk 过大警告，页面加载和构建结构更清晰。

## 六、核心风险指标

项目中我重点实现和展示了以下风险指标：

### 1. 健康因子

健康因子用于衡量仓位距离清算的安全程度。前端对不同区间做了视觉区分：

- 高风险：黄色闪烁；
- 观察区：橙色；
- 安全区：绿色或白色；
- 无风险：显示“无风险”。

JustLend 和 MakerDAO 均提供小问号说明，解释不同颜色和闪烁状态的含义。

### 2. 清算价格

清算价格用于表示资产价格达到某个水平时仓位可能进入可清算状态。前端在 Aave、Compound、MakerDAO、Morpho 等协议中都围绕清算价格构建了风险展示。

### 3. 价格缓冲

MakerDAO 仓位总览新增价格缓冲指标：

```text
(当前资产价格 - 清算价格) / 当前资产价格
```

该指标直观表示当前价格距离清算价格还有多少比例空间。结果保留两位小数。

### 4. LTV 与清算阈值

JustLend、Morpho 等模块中，我展示了 LTV、LLTV、清算阈值和风险缓冲，用于说明借款规模相对抵押价值的压力。

### 5. 大户 / 风险仓位

JustLend 和 MakerDAO 均实现了分页仓位表，可按健康状态、资产、仓位类型、抵押状态、排序字段等条件筛选风险对象。

## 七、工程难点与解决方案

### 1. 多协议字段不统一

不同协议返回字段差异很大，例如：

- Aave 有 `liq_price` 与 `liq_price_rise`；
- Compound 分 V2 / V3；
- JustLend 使用 TRON 地址和 TRON 资产；
- MakerDAO 有普通 Vault 与系统 urn；
- Morpho 使用 market id、loan token、collateral token 和 LLTV。

我的解决方式是：

- 后端按协议保留原始语义；
- API 层做必要的统一；
- 前端每个协议维护独立类型；
- 公共交互组件抽象，业务计算不强行共用。

### 2. 地址格式复杂

项目同时涉及 Ethereum EVM 地址和 TRON Base58 地址。我在后端和前端分别处理：

- EVM 地址标准化；
- TRON 地址必须以 `T...` Base58 形式展示和存储；
- 旧数据格式兼容；
- API 查询参数标准化。

### 3. 实时价格不稳定

链上价格查询可能遇到：

- RPC 限流；
- Oracle revert；
- 包装资产汇率读取失败；
- 特殊资产无价格源；
- 502 或 404。

我在前端增加了：

- 价格请求失败静默处理；
- 失败资产短时间缓存；
- 无价格时显示 `--`；
- MakerDAO 特殊资产不使用 symbol fallback 乱查价格。

后端则通过多层价格源和缓存兜底提升可用性。

### 4. 前端请求过多

多协议页面同时挂载时，容易出现后台页面也发请求的问题。我通过 `active` 守卫和按需懒加载解决：

- 未激活协议不请求；
- Morpho 市场详情展开后才请求；
- MakerDAO ILK 筛选按 Enter 后才提交；
- 价格请求按当前页仓位去重；
- API 客户端 inflight 去重。

### 5. 样式联动问题

多个协议页面共用 CSS 类名会导致修改一个页面影响另一个页面。我通过协议级样式拆分和局部组件重写解决：

- 不直接套用 JustLend 组件到 MakerDAO；
- 保持视觉一致，但实现独立；
- App 级样式只保留基础布局；
- 协议内部组件样式各自维护。

## 八、项目成果

实习期间，我完成了一个可运行、可扩展的多协议 DeFi 风险监测系统。主要成果包括：

- 支持 Aave、Compound、Morpho、JustLend、MakerDAO 五类协议；
- 建立了统一 FastAPI 后端服务；
- 建立了前端协议注册与页面切换框架；
- 实现了个人仓位分析、市场宏观评估、历史回放和风险仓位表；
- 实现了多协议价格查询与缓存；
- 实现了 MakerDAO 普通 Vault、系统 urn 和仓位总览；
- 实现了 JustLend 大户 / 风险仓位分析；
- 实现了 Morpho 市场、Vault 和动态清算分析；
- 完成了前端样式解耦和构建拆包优化；
- 完成了 README、backend README、frontend README、AGENTS 等文档整理；
- 将项目推送到 GitHub 仓库 `EtherVision`。

## 九、项目运行方式

### 后端

```bash
cd backend
uv sync
uv run api
```

默认后端地址：

```text
http://localhost:8000
```

### 前端

```bash
cd frontend
pnpm install
pnpm dev
```

默认前端地址：

```text
http://localhost:5173
```

前端通过环境变量连接后端：

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api
```

### 校验

```bash
cd frontend
pnpm lint
pnpm build
```

```bash
cd backend
uv run pytest tests/ -q
```

## 十、个人收获

通过这个项目，我系统性完成了从链上数据读取、协议业务理解、数据库缓存、后端 API 设计到前端可视化展示的完整闭环。

我对以下能力有了明显提升：

- DeFi 借贷协议的仓位、抵押、债务、健康因子和清算机制理解；
- Ethereum 与 TRON 链上数据读取和地址格式处理；
- FastAPI 后端服务设计；
- PostgreSQL / ClickHouse 数据查询与缓存设计；
- React + TypeScript 大型前端页面组织；
- 图表、表格、分页、筛选、历史回放等复杂交互实现；
- 多协议项目的模块化和工程化拆分；
- 前端性能优化和样式解耦；
- 面向真实数据异常的容错设计。

这个项目让我从单一脚本或单一页面开发，真正进入到一个完整工程系统的设计和维护中。它不仅是一个实习项目，也是一个覆盖 DeFi 风险分析核心流程的全栈实践项目。

## 十一、后续可扩展方向

后续可以继续扩展：

- 增加更多协议，如 Spark、Venus、Euler；
- 为 MakerDAO 系统仓位接入更完整的价格白名单；
- 增加跨协议统一风险评分；
- 增加风险告警和推送；
- 增加用户自定义 watchlist；
- 增加链上交易实时监听；
- 增加更多历史压力测试场景；
- 将前端部署到静态站点，将后端部署为长期服务；
- 增加权限控制和多用户工作台。

## 十二、项目一句话总结

EtherVision 是我在实习期间独立完成的多协议 DeFi 风险监测与仓位分析系统，覆盖链上数据采集、缓存、统一 API、前端风险可视化和多协议工程化扩展，能够帮助用户快速理解 DeFi 借贷仓位的资产结构、债务压力、健康因子和清算风险。
