# AGENTS.md

本文件用于说明本仓库的共享开发规则与 agent 协作约束。

前半部分面向所有维护者，包括人类开发者与代码 agent。后半部分保留 agent 在本仓库内工作的额外注意事项。

## 仓库概览

这是一个多协议清算风险监测与仓位分析仓库，当前包含：

- 后端：Python，统一承载 Aave、Compound、Morpho、JustLend 等协议的数据采集、持久化与 API
- 前端：React + TypeScript + Vite，消费统一后端 API，提供个人仓位分析与市场看板
- 数据库：PostgreSQL 为主，ClickHouse 用于部分链上原始日志查询

当前仓库不是单一 Aave 项目。Aave 仍然是历史最重、文档最丰富的模块，但 Morpho、Compound、JustLend 已经是正式的一部分。

## 共享开发规则

### 文档分工

- 根 `README.md`：仓库入口、安装运行路径、模块地图、文档导航
- `backend/README.md`：后端运行方式、模块职责、数据库说明、测试与常见坑
- `frontend/README.md`：前端运行、构建、联调与目录结构
- `AGENTS.md`：仓库规则、约定、agent 注意事项

### 文档同步要求

出现以下变更时，必须同步更新对应文档：

- 仓库结构、启动方式、依赖前提发生变化：更新根 `README.md`
- 后端命令、配置、API、数据库结构、模块职责发生变化：更新 `backend/README.md`
- 前端环境变量、构建方式、页面结构、API 依赖发生变化：更新 `frontend/README.md`
- 仓库级约定、地址存储规则、agent 工作边界发生变化：更新 `AGENTS.md`

### 地址存储标准

当前仓库中存在历史遗留的多种地址存储格式。下面是**后续新增表、新增列、以及地址相关重构的目标标准**，不代表所有现有表都已完成迁移。

- 所有存储链上地址的数据库列，统一使用 PostgreSQL 列级 `STORAGE PLAIN`
- 所有 TRON 地址必须以规范化 Base58 文本形式存储，并以 `T` 开头，例如 `Txxxxx`

适用范围包括但不限于：

- `user_address`
- `walletAddress`
- `token_address`
- `contract_address`
- `market`
- `oracle_address`
- `receiver`
- `sender`
- `borrower_address`
- `payer_address`
- `payee_address`
- `liquidator_address`

补充约束：

- TRON 地址禁止以 `41...` 裸十六进制、raw bytes、或其他非 `T...` 形式落库
- 兼容旧表时可以保留读路径兼容逻辑，但新写入应优先遵循上述标准
- 对旧表做兼容性修补时，需要明确这是“兼容旧格式”还是“推进迁移到新标准”

## 项目结构

### 后端

- `backend/aave_crawler/`：Aave 数据采集、仓位快照、历史回放、清算分析
- `backend/compound_crawler/`：Compound V2/V3 市场、治理参数、仓位回放
- `backend/morpho_crawler/`：Morpho Blue 当前仓位与市场信息
- `backend/justlend_crawler/`：JustLend 当前仓位、趋势回放与说明文案
- `backend/crawler_shared/`：共享配置、数据库与统一 API 入口
- `backend/alembic/`：迁移脚本
- `backend/tests/`：后端测试

### 前端

- `frontend/src/api/`：按协议拆分的 API 客户端
- `frontend/src/components/`：各协议仪表盘与图表组件
- `frontend/src/protocols/`：协议注册表
- `frontend/src/shared/`：共享 UI 与类型
- `frontend/src/hooks/`：共享 hooks
- `frontend/src/theme/`：主题与设计 token

### 前端样式分层约定

前端样式必须保持“应用壳、共享基础、协议私有”三层分离：

- `frontend/src/App.css` 只保留应用壳样式，例如 `.app`、`.app-main`、`.app-footer`，不要放页面组件、协议看板、图表或表格样式
- `frontend/src/shared/styles/components.css` 只放真正跨协议复用的基础 UI 样式，例如卡片、表格、输入框、按钮、徽标、加载态、通用排版工具类
- 共享样式禁止出现协议语义前缀或协议私有命名，例如 `aave-*`、`compound-*`、`justlend-*`、`makerdao-*`、`morpho-*`
- 各协议私有样式必须放在对应目录的 `frontend/src/protocols/<protocol>/styles.css` 中，并由该协议 `root.tsx` 导入
- 协议组件 class 命名应优先使用协议前缀，例如 `makerdao-*`、`morpho-*`；不要跨协议复用别的协议 class
- 如果多个协议需要同一种视觉模式，应先抽象为中性的共享 class，再放入 `shared/styles/components.css`，不要用 `protocol-*` 这类含义模糊的临时命名长期共享
- 新增页面或重构样式时，应避免在一个 CSS 文件中混合多个协议的规则；发现历史混合样式时，优先迁回对应协议目录
- 大型协议样式文件应按业务域继续拆分为协议私有模块，例如 `market.css`、`vault.css`、`history.css`、`dashboard.css`
- 协议 `styles.css` 可以作为样式索引，只保留显式 `@import`；模块必须放在该协议目录下，不要从共享样式或其他协议入口导入
- 拆分协议样式时必须保持原有 cascade 顺序，先做视觉等价的结构整理，再考虑命名或视觉调整

## 后端关键约定

### 数据库访问模式

后端采用双访问模式：

- SQLAlchemy AsyncSession：更适合 API 读操作与 ORM 模型管理
- asyncpg Pool：更适合批量写入、显式事务、性能关键路径

除非性能上已经证明 ORM 不够，否则 API 查询优先使用 SQLAlchemy。批量落库、回放缓存、批处理脚本优先使用 asyncpg。

### Aave 现有核心约定

- `-p/--protocol` 常见取值：`v2`、`v3`、`v2_borrow`、`v3_borrow`
- Aave V3 预言机价格通常为 USD 8 位小数；Aave V2 需要注意 ETH 计价分支
- `ETH_SYMBOLS` 用于定义 ETH 系资产范围
- 清算价格分为两类：
  - `liq_price`：ETH 下跌导致清算
  - `liq_price_rise`：ETH 上涨导致 WETH 借款仓位清算

### 外部数据依赖

- PostgreSQL 中部分 schema 由外部系统维护，不属于本仓库迁移管理范围
- ClickHouse 只用于特定日志分析，不是核心运行前提
- 对外部表做假设时，必须先区分“本仓库管理”与“外部维护”

## 常见开发命令

### 后端

```bash
cd backend
uv sync
uv run api
uv run pytest tests/ -q
```

### 前端

```bash
cd frontend
pnpm install
pnpm dev
pnpm build
```

## Agent 专用说明

本节仅面向代码 agent。

### 工作原则

- 先理解现状，再改文档或代码，不要凭印象补全
- 涉及仓库结构、模块职责、命令、配置时，优先核对实际文件
- 如果当前状态与文档不一致，应以代码和配置为准，再修正文档

### 前端样式工作边界

- 修改前端页面时，先确认样式应归属应用壳、共享基础还是具体协议，不要为了方便把局部样式写进 `App.css`
- 新增协议页面时，同步新增或维护该协议的 `styles.css`，并在协议 `root.tsx` 中导入
- 不要让 MakerDAO 复用 JustLend、Morpho 复用通用 `protocol-*` 等跨协议 class；命名可以相似，但样式所有权必须独立
- 迁移样式时应尽量先保持视觉等价，再做命名和结构调整；如果存在视觉回归风险，应明确记录待回归检查点
- 拆分大型协议 CSS 时，用协议 `styles.css` 统一汇总模块 import，并按页面或能力命名模块，避免生成长期存在的“临时迁移”分区
- 完成前端样式结构调整后，至少运行 `pnpm build` 验证打包通过

### 文档修改原则

- 文档一律使用简体中文，除非必须保留英文专有名词
- 根 README 负责导航，不应复制过多 backend 细节
- `backend/README.md` 可以详细，但不要再写成“只有 Aave 的项目”
- `frontend/README.md` 只讲前端关心的运行、联调、结构，不重复后端实现细节

### 对历史信息的处理

- 不要把“目标标准”写成“当前事实”
- 不要删除仍对运维或排障有价值的历史说明，除非已确认过时
- 如果仓库存在混合状态，文档必须显式写明“现状”和“后续标准”的区别

### 安全边界

- 不要默认外部 schema、外部链数据表、外部服务的结构已经被本仓库控制
- 修改涉及地址格式、数据库列类型、API 响应字段时，必须检查上下游兼容性
- 发现旧逻辑依赖历史格式时，先记录并解释，不要盲目统一
