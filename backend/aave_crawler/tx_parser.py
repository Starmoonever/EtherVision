"""tx_parser.py — 通过 AI-ContractParser 子模块解析 Aave 交易，返回人类可读的 brief。

模板占位符 label 处理规则：
  - ${N:amount}   → 原始整数 / 10**decimals（decimals 来自相邻 token 参数）
  - ${N:token}    → ERC-20 symbol()（先查静态表，再 RPC fallback）
  - ${N:contract} → 直接使用 params[N]（已是合约名，如 "Aave"）
  - 其他 label   → 原值透传

用法::

    from aave_crawler.tx_parser import parse_tx_briefs

    briefs = await parse_tx_briefs(
        tx_hashes=["0xabc...", "0xdef..."],
        protocol="v3",
    )
    # -> ["在 Aave 取出 700 weETH", "在 Aave 借出 500 USDC"]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 路径 ────────────────────────────────────────────────────────────────────
_PARSER_DIR = Path(__file__).parent.parent / "AI-ContractParser"
_DECODE_SCRIPT = _PARSER_DIR / "scripts" / "decode" / "decode-tx-input.js"
_ENV_FILE = _PARSER_DIR / ".env"

# ── Aave Pool 地址 ───────────────────────────────────────────────────────────
_POOL_BY_PROTOCOL: dict[str, str] = {
    "v3": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
    "v3_borrow": "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
    "v2": "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9",
    "v2_borrow": "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9",
}

# protocol 字符串（'v2'/'v3'）→ brief 中的版本标签
_VERSION_LABEL: dict[str, str] = {
    "v2": "V2",
    "v3": "V3",
}

# ── 并发上限（避免同时 fork 过多 node 进程）────────────────────────────────
_BRIEF_SEM = asyncio.Semaphore(8)

# ── 进程内 brief 缓存（tx_hash → brief）────────────────────────────────────
_brief_mem_cache: dict[str, str] = {}

# ── 模板占位符正则：${N:label} ───────────────────────────────────────────────
_PLACEHOLDER_PAT = re.compile(r"\$\{(\d+):([^}]+)\}")

# ── 最小 ERC-20 ABI（symbol + decimals）──────────────────────────────────────
_ERC20_ABI = [
    {
        "name": "symbol", "type": "function",
        "inputs": [], "outputs": [{"type": "string"}],
        "stateMutability": "view",
    },
    {
        "name": "decimals", "type": "function",
        "inputs": [], "outputs": [{"type": "uint8"}],
        "stateMutability": "view",
    },
]

# ── Mainnet 常见 Aave 代币静态表（地址全部小写）→ (symbol, decimals) ─────────
_KNOWN_TOKENS: dict[str, tuple[str, int]] = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": ("WETH",   18),
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": ("wstETH", 18),
    "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee": ("weETH",  18),
    "0xae78736cd615f374d3085123a210448e74fc6393": ("rETH",   18),
    "0xbe9895146f7af43049ca1c1ae358b0541ea49704": ("cbETH",  18),
    "0xbf5495efe5db9ce00f80364c8b423567e58d2110": ("ezETH",  18),
    "0xa1290d69c65a6fe4df752f95823fae25cb99e5a7": ("rsETH",  18),
    "0xf1c9acdc66974dfb6decb12aa385b9cd01190e38": ("osETH",  18),
    "0xa35b1b31ce002fbf2058d22f30f95d405200a15b": ("ETHx",   18),
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC",    6),
    "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT",    6),
    "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI",    18),
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": ("WBTC",    8),
    "0x514910771af9ca656af840dff83e8264ecf986ca": ("LINK",   18),
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": ("AAVE",   18),
    "0xd533a949740bb3306d119cc777fa900ba034cd52": ("CRV",    18),
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": ("UNI",    18),
    "0xba100000625a3754423978a60c9317c58a424e3d": ("BAL",    18),
}

# ── Token info 缓存 ───────────────────────────────────────────────────────────
_token_info_cache: dict[str, tuple[str, int]] = {}

# ── Web3 实例（懒加载）───────────────────────────────────────────────────────
_w3 = None
_w3_lock = asyncio.Lock()


def _read_rpc_url() -> str:
    """从 AI-ContractParser/.env 读取 ETH_RPC_URL。"""
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ETH_RPC_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


async def _get_w3():
    """懒加载 AsyncWeb3 实例，失败时返回 None。"""
    global _w3
    if _w3 is not None:
        return _w3
    async with _w3_lock:
        if _w3 is not None:
            return _w3
        rpc = _read_rpc_url()
        if not rpc:
            logger.warning("tx_parser: ETH_RPC_URL 未配置，token 信息将仅用静态表")
            return None
        try:
            from web3 import AsyncWeb3
            _w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
        except Exception as exc:
            logger.warning("tx_parser: 初始化 web3 失败: %s", exc)
        return _w3


async def _get_token_info(addr: str) -> tuple[str, int]:
    """返回 (symbol, decimals)；先查静态表，再 RPC，失败返回 ('', 18)。"""
    addr = addr.lower()
    if addr in _token_info_cache:
        return _token_info_cache[addr]
    if addr in _KNOWN_TOKENS:
        info = _KNOWN_TOKENS[addr]
        _token_info_cache[addr] = info
        return info

    w3 = await _get_w3()
    if w3 is None:
        return ("", 18)
    try:
        from web3 import AsyncWeb3 as _AW3
        contract = w3.eth.contract(
            address=_AW3.to_checksum_address(addr), abi=_ERC20_ABI
        )
        symbol, decimals = await asyncio.gather(
            contract.functions.symbol().call(),
            contract.functions.decimals().call(),
        )
        info = (str(symbol), int(decimals))
        _token_info_cache[addr] = info
        logger.debug("tx_parser: token %s → %s / %d decimals", addr, symbol, decimals)
        return info
    except Exception as exc:
        logger.debug("tx_parser: _get_token_info 失败 %s: %s", addr, exc)
        _token_info_cache[addr] = ("", 18)
        return ("", 18)


# uint256.max = 2^256-1，Aave 用作"全额偿还/全额取出"的哨兵值
_SENTINEL_THRESHOLD = Decimal(10) ** 75  # 大于此值视为 uint256.max


def _fmt_amount(raw: str, decimals: int) -> str:
    """原始整数字符串 → 可读小数（最多 6 位，去尾零）。

    特殊值：若 raw >= 1e75（Aave uint256.max 哨兵），返回 '全部'。
    """
    try:
        raw_dec = Decimal(raw)
        if raw_dec >= _SENTINEL_THRESHOLD:
            return "全部"
        value = raw_dec / Decimal(10 ** decimals)
        return f"{value:.6f}".rstrip("0").rstrip(".")
    except Exception:
        return raw


def _normalize_param(v: object) -> list[str]:
    """将 param 值统一为字符串列表（处理 JSON 数组和标量两种情况）。"""
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


async def _resolve_token_addr(raw: str) -> tuple[str, int]:
    """单个 token 地址 → (symbol, decimals)。"""
    _ADDR_LEN = 42
    if raw.startswith("0x") and len(raw) >= _ADDR_LEN:
        sym, dec = await _get_token_info(raw)
        if sym:
            return (sym, dec)
        short = raw[:6] + "…" + raw[-4:]
        return (short, dec)
    elif raw.startswith("0x"):
        return ("ETH", 18)
    else:
        return (raw, 18)


async def _fill_template_rich(
    template: str,
    params: dict[str, object],
    protocol: str = "",
    prices: "dict[str, Decimal] | None" = None,
) -> str:
    """根据占位符 label 对 params 进行富化后填充模板。

    处理顺序：
      1. 解析所有 ``token`` 参数 → (addr, symbol, decimals)，支持地址数组
      2. 用相邻 token 的 decimals 格式化 ``amount``/``amounts`` 参数，支持金额数组
         数组情形下，amounts[i] 与 token[i] 一一对应，输出 "N1 T1 + N2 T2"
      3. ``token`` 占位符：若提供了 prices，在 symbol 后附加「（价值 X.XX USD）」
      4. ``contract`` 参数：名称 + 版本号后缀（来自 protocol 参数）
      5. 其他 label → 原值透传

    :param protocol: 'v2' | 'v3'，用于在 contract 占位符后附加版本标签
    :param prices:   token_address_lower → Decimal(price_usd)，用于计算 USD 价值
    """
    placeholders: dict[str, str] = {
        m.group(1): m.group(2)
        for m in _PLACEHOLDER_PAT.finditer(template)
    }

    # ── Step 1: 解析 token 参数（支持数组）──────────────────────────────────
    # token_by_idx[idx] = list of (addr, symbol, decimals)，每个 token 地址对应一项
    token_by_idx: dict[str, list[tuple[str, str, int]]] = {}
    for idx, label in placeholders.items():
        if label == "token":
            addrs = _normalize_param(params.get(idx, ""))
            infos: list[tuple[str, str, int]] = []
            for a in addrs:
                if a:
                    sym, dec = await _resolve_token_addr(a)
                    infos.append((a, sym, dec))
            if infos:
                token_by_idx[idx] = infos

    # 默认 decimals：取序号最小的 token 的第一个
    default_decimals = 18
    if token_by_idx:
        nearest_idx = min(token_by_idx.keys(), key=lambda x: int(x))
        default_decimals = token_by_idx[nearest_idx][0][2]

    # ── Step 2: 构建替换值 ───────────────────────────────────────────────────
    resolved: dict[str, str] = {}
    for idx, label in placeholders.items():
        raw_obj = params.get(idx, f"${{{idx}:{label}}}")

        if label == "token":
            if idx not in token_by_idx:
                resolved[idx] = str(raw_obj)
            else:
                # 找相邻 amount 索引，用于计算 USD 价值
                adj_prev = str(int(idx) - 1)
                adj_next = str(int(idx) + 1)
                amt_idx = None
                if adj_prev in placeholders and placeholders[adj_prev] in ("amount", "amounts"):
                    amt_idx = adj_prev
                elif adj_next in placeholders and placeholders[adj_next] in ("amount", "amounts"):
                    amt_idx = adj_next
                amt_list = _normalize_param(params.get(amt_idx, "")) if amt_idx else []

                parts: list[str] = []
                for i, (addr_i, sym_i, dec_i) in enumerate(token_by_idx[idx]):
                    token_str = sym_i
                    if prices and amt_list and i < len(amt_list):
                        amt_raw = amt_list[i]
                        fmt_check = _fmt_amount(amt_raw, dec_i)
                        if fmt_check != "全部" and addr_i:
                            price_usd = prices.get(addr_i.lower())
                            if price_usd:
                                try:
                                    usd_val = Decimal(amt_raw) / Decimal(10 ** dec_i) * price_usd
                                    token_str += f"（价值 {usd_val:.2f} USD）"
                                except Exception:
                                    pass
                    parts.append(token_str)
                resolved[idx] = " + ".join(parts)

        elif label in ("amount", "amounts"):
            # 找相邻 token 索引（先 idx+1，再 idx-1）
            adj_next = str(int(idx) + 1)
            adj_prev = str(int(idx) - 1)
            if adj_next in token_by_idx:
                token_infos = token_by_idx[adj_next]
            elif adj_prev in token_by_idx:
                token_infos = token_by_idx[adj_prev]
            else:
                token_infos = [("", "", default_decimals)]

            amounts = _normalize_param(raw_obj)
            parts2: list[str] = []
            for i, amt_str in enumerate(amounts):
                dec = token_infos[i][2] if i < len(token_infos) else default_decimals
                parts2.append(_fmt_amount(amt_str, dec))
            resolved[idx] = " + ".join(parts2) if parts2 else str(raw_obj)

        elif label == "contract":
            version_suffix = _VERSION_LABEL.get(protocol.lower(), "")
            raw_str = str(raw_obj)
            resolved[idx] = f"{raw_str} {version_suffix}".strip() if version_suffix else raw_str

        else:
            resolved[idx] = str(raw_obj)

    result = _PLACEHOLDER_PAT.sub(lambda m: resolved.get(m.group(1), m.group(0)), template)
    import re as _re
    result = _re.sub(r"  +", " ", result).strip()
    return result


async def _parse_single(
    tx_hash: str,
    pool_address: str,
    protocol: str = "",
    prices: "dict[str, Decimal] | None" = None,
) -> str:
    """子进程调用 decode-tx-input.js，解析单笔 tx 的 brief（含富化处理）。"""
    async with _BRIEF_SEM:
        try:
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(_DECODE_SCRIPT),
                "--tx", tx_hash,
                "--address", pool_address,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_PARSER_DIR),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=30
            )
        except asyncio.TimeoutError:
            logger.warning("parse_tx_brief timeout: %s", tx_hash)
            return ""
        except Exception as exc:
            logger.warning("parse_tx_brief error (%s): %s", tx_hash, exc)
            return ""

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")

    # 跳过 dotenv 头部行（某些 tip 消息含 { 会干扰）：找行首的 '{' 作为 JSON 起始
    _json_match = re.search(r"(?m)^\{", stdout_text)
    if not _json_match:
        logger.debug("parse_tx_brief: no JSON in stdout for %s", tx_hash)
        return ""
    json_start = _json_match.start()

    try:
        data = json.loads(stdout_text[json_start:])
    except json.JSONDecodeError as exc:
        logger.debug("parse_tx_brief: JSON decode error for %s: %s", tx_hash, exc)
        return ""

    try:
        brief_block = data["data"]["template"]["brief"]
        tmpl: str = brief_block["template"]
        # 保留原始类型（list 或 str），让 _fill_template_rich 处理数组 param
        params: dict[str, object] = dict(brief_block.get("params", {}))
        return await _fill_template_rich(tmpl, params, protocol=protocol, prices=prices)
    except (KeyError, TypeError):
        logger.debug("parse_tx_brief: no brief in parsed result for %s", tx_hash)
        return ""


async def parse_tx_brief(
    tx_hash: str,
    protocol: str = "v3",
    prices: "dict[str, Decimal] | None" = None,
) -> str:
    """解析单笔 tx 的人类可读摘要。

    - prices 为 None 时：查/写内存缓存（适合生产环境重复调用）
    - prices 不为 None 时：每次重新解析并附加 USD 价值描述，绕过内存缓存
      （同一 tx 在不同 block 时刻的价格不同，不能复用缓存结果）
    """
    tx_hash = tx_hash.lower()
    if prices is None and tx_hash in _brief_mem_cache:
        return _brief_mem_cache[tx_hash]

    pool_address = _POOL_BY_PROTOCOL.get(protocol, _POOL_BY_PROTOCOL["v3"])
    brief = await _parse_single(tx_hash, pool_address, protocol=protocol, prices=prices)
    if prices is None:
        _brief_mem_cache[tx_hash] = brief
    return brief


async def parse_tx_briefs(
    tx_hashes: list[str],
    protocol: str = "v3",
) -> list[str]:
    """并发解析多笔 tx 的 brief，保持与 tx_hashes 相同顺序。

    :param tx_hashes: tx hash 列表
    :param protocol:  'v2' | 'v3'
    :returns:         与 tx_hashes 等长的 brief 列表，失败项返回空字符串
    """
    if not tx_hashes:
        return []
    pool_address = _POOL_BY_PROTOCOL.get(protocol, _POOL_BY_PROTOCOL["v3"])

    async def _get(tx_hash: str) -> str:
        h = tx_hash.lower()
        if h in _brief_mem_cache:
            return _brief_mem_cache[h]
        brief = await _parse_single(h, pool_address, protocol=protocol)
        _brief_mem_cache[h] = brief
        return brief

    return list(await asyncio.gather(*(_get(h) for h in tx_hashes)))


async def parse_briefs_from_metas(metas: list[dict]) -> list[str]:
    """从 meta 列表中批量解析 brief，自动读取每条 meta 的 tx_hash 和 protocol。

    meta dict 需包含:
      - ``tx_hash``:  str
      - ``protocol``: str ('v2' | 'v3')

    :returns: 与 metas 等长的 brief 列表，失败项返回空字符串

    相比手动拆分 tx_hash 列表再单独传 protocol，此函数可避免调用方到处重复
    相同的 ``[m["tx_hash"] for m in metas]`` + ``protocol=protocol`` 写法。
    """
    if not metas:
        return []
    return list(await asyncio.gather(
        *(
            parse_tx_brief(
                m["tx_hash"],
                protocol=m.get("protocol", "v3"),
                prices=m.get("prices"),
            )
            for m in metas
        )
    ))
