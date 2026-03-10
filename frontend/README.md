# aave-liquidation（前端）

Aave V2 / V3 ETH 市场清算风险监测看板（数据库版）。通过内部后端 API 查询链上爬取的仓位数据，提供个人账户分析与宏观市场评估两大功能模块。

## 依赖

- Node.js 18+
- [pnpm](https://pnpm.io/)

## 快速开始

### 1. 安装依赖

```bash
cd frontend
pnpm install
```

### 2. 配置后端 API 地址

前端通过环境变量 `VITE_API_BASE_URL` 连接后端 API。默认值（`.env`）：

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api
```

如需修改，在 `frontend/` 目录下创建 `.env.local` 并覆盖该变量：

```dotenv
VITE_API_BASE_URL=http://10.1.5.183:8000/api
```

> `.env.local` 已加入 `.gitignore`，不会提交到版本控制。

### 3. 启动开发服务器

```bash
# 本机访问
pnpm dev

# 局域网访问（其他设备可通过 IP 访问）
pnpm dev --host
```

启动后访问终端显示的本地地址（默认 `http://localhost:5173`）。

### 4. 构建生产版本

```bash
pnpm build
```

产物输出到 `dist/`。

### 5. 预览生产构建

```bash
pnpm preview
pnpm preview --host   # 局域网访问
```

## 部署（静态托管）

`dist/` 为纯静态文件，可直接部署到任意静态托管服务：

### Nginx 示例

```nginx
server {
    listen 80;
    root /path/to/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**注意**：`VITE_API_BASE_URL` 在构建时注入，如需更换后端地址，修改环境变量后须重新执行 `pnpm build`。

## 使用说明

### 全局筛选

页面顶部提供两组切换按钮，作用于所有功能模块：

- **抵押端 / 借贷端**：切换关注维度（抵押 ETH 下跌风险 vs 借贷 WETH 上涨风险）
- **V2 / V3 / ALL**：筛选 Aave 协议版本

### 个人账户分析

1. 在输入框中粘贴钱包地址（支持 EIP-55 校验和地址和小写地址）
2. 点击**查询仓位**
3. 页面展示：
   - **账户概览**：ETH 抵押数量与 USD 价值、总抵押、可借额度、总债务、清算价格、健康因子、当前 LTV、清算阈值
   - **资产负债**：已供给资产（Supplied）与已借出负债（Borrowed）明细表

### 宏观市场评估

- **ETH 实时价格**：每 10 分钟轮询后端 Oracle 数据
- **ETH 价格走势**：支持 24h / 7D / 3M 时间范围，历史价格折线图，带 5 分钟本地缓存
- **价格波动清算模拟**：通过滑块设置 -100% ~ +200% 价格变动幅度，预览模拟价格
- **清算分布柱状图**：展示各价格区间内待清算 USD 总量，点击柱子可查看该价格下触发清算的仓位列表

## 后端 API 说明

前端依赖以下 API 端点（均以 `VITE_API_BASE_URL` 为基础路径）：

| 端点                                                                         | 用途                   |
| ---------------------------------------------------------------------------- | ---------------------- |
| `GET /user/position?address=&version=`                                       | 查询单个用户仓位概览   |
| `GET /price?asset=eth&time=now`                                              | 获取 ETH 实时价格      |
| `GET /price/period?asset=eth&start=&end=&interval=`                          | 获取 ETH 历史价格序列  |
| `GET /liquidate/period?start=&end=&interval=1&eth_ratio=0.4&version=`        | 抵押端各价格区间清算量 |
| `GET /borrow/liquidate/period?start=&end=&interval=1&eth_ratio=0.4&version=` | 借贷端各价格区间清算量 |

## 项目结构

```text
frontend/
├── .env                     # 默认环境变量（VITE_API_BASE_URL）
├── config.yaml              # 本地配置（RPC 地址，由 vite.config.ts 注入为 VITE_RPC_URL）
├── vite.config.ts           # 读取 config.yaml，注入构建时变量
├── index.html
└── src/
    ├── App.tsx              # 根组件：标签页、版本/侧边切换、路由渲染
    └── components/
        ├── AddressInput.tsx     # 地址输入框，viem isAddress 校验
        ├── SummaryCard.tsx      # 账户概览卡片
        ├── PositionTable.tsx    # 供给 / 借贷明细表
        ├── MarketAssessment.tsx # 宏观市场评估容器
        ├── LiquidationChart.tsx # 清算分布柱状图 + 仓位明细弹窗
        └── EthPriceTrend.tsx    # ETH 价格走势折线图
```
