# aave-liquidation（前端）

交互式查询 Aave V3 Base Mainnet 上单个钱包的仓位数据，展示抵押物、借贷明细及 USD 估值。

## 依赖

- Node.js 18+
- [pnpm](https://pnpm.io/)

## 快速开始

### 1. 安装依赖

```bash
cd frontend
pnpm install
```

### 2. 配置

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml`：

```yaml
# Base 网络 RPC 端点
# 留空则自动轮换公共节点（可能触发限流，建议配置私有节点）
rpc_url: "http://your-rpc-node:port/"
```

> `config.yaml` 已加入 `.gitignore`，不会提交到版本控制。
> Vite 在启动/构建时读取此文件，修改后需重启开发服务器。

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

**Nginx 示例**

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

**注意**：RPC 端点在构建时注入，如需更换节点，修改 `config.yaml` 后须重新执行 `pnpm build`。

## 使用说明

1. 在输入框中粘贴钱包地址（支持 EIP-55 校验和地址和小写地址）
2. 点击**查询**，等待链上数据加载
3. 页面展示：
   - 账户汇总（总抵押物、总借贷、健康系数、LTV）
   - 供给明细（资产、单价、余额、USD 估值）
   - 借贷明细（稳定借贷、浮动借贷、合计 USD）

## 项目结构

```
frontend/
├── config.yaml.example
├── config.yaml              # 本地配置（gitignored）
├── vite.config.ts           # 读取 config.yaml，注入 RPC 地址
├── index.html
└── src/
    ├── App.tsx
    ├── lib/
    │   └── aave.ts          # 合约调用逻辑（viem）
    └── components/
        ├── AddressInput.tsx
        ├── SummaryCard.tsx
        └── PositionTable.tsx
```

## 公共 RPC 节点（内置后备）

未配置 `rpc_url` 或自定义节点不可用时，自动按序尝试：

1. `https://base.llamarpc.com`
2. `https://base-rpc.publicnode.com`
3. `https://1rpc.io/base`
4. `https://base.drpc.org`
5. `https://mainnet.base.org`
