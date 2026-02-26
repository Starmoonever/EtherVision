import json
import csv
import requests
from web3 import Web3
import numpy as np
# 节点访问以太主网
RPC_URL = "http://10.8.6.153:2700/"
# Aave V3 Pool 代理合约地址
POOL_ADDRESS = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
# 文件名配置
INPUT_FILE = "all_aave_eth_users.csv"
# 计算得到的健康因子和liquidation price存储处
OUTPUT_FILE = "liquidation_results.csv"
# 初始化连接
w3 = Web3(Web3.HTTPProvider(RPC_URL))
# Aave V3 Pool 接口仅包含查询账户数据函数，getUserAccountData
# 输入 user（要查询的账户地址）
# 调用Aave 合约中函数 getUserAccountData
# "outputs": 定义了函数返回的结果。你可以看到它按顺序返回 6 个值 （totalCollateralBase，totalDebtBase，availableBorrowsBase，currentLiquidationThreshold，ltv，healthFactor
POOL_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"user","type":"address"}],"name":"getUserAccountData","outputs":[{"internalType":"uint256","name":"totalCollateralBase","type":"uint256"},{"internalType":"uint256","name":"totalDebtBase","type":"uint256"},{"internalType":"uint256","name":"availableBorrowsBase","type":"uint256"},{"internalType":"uint256","name":"currentLiquidationThreshold","type":"uint256"},{"internalType":"uint256","name":"ltv","type":"uint256"},{"internalType":"uint256","name":"healthFactor","type":"uint256"}],"stateMutability":"view","type":"function"}]')
# Python以此找到pool 合约地址，调用函数getUserAccountData
pool_contract = w3.eth.contract(address=POOL_ADDRESS, abi=POOL_ABI)

#实时获取ETH价格
def get_eth_price():
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
        response = requests.get(url, timeout=5)
        price = response.json()['ethereum']['usd']
        print(f"📈 当前 ETH 市场价: ${price}")
        return price
# 主程序，一次性获取所有账户在Aave V3 Pool的健康因子和清算价格
def run_analysis():
    if not w3.is_connected():
        print("❌ 错误：无法连接到节点，请检查 VPN 或内网连接。")
        return

    current_price = get_eth_price()
    results = []

    with open(INPUT_FILE, mode='r', encoding='utf-8') as f:
            # 自动解析 CSV，第一行必须包含 walletAddress
            reader = csv.DictReader(f)
            
            print(f"🚀 开始处理地址列表...")
            for i, row in enumerate(reader):
                addr = row['walletAddress'].strip()
       # 用 NumPy 进行精度转换和判断
                try:
                    eth_amount = np.float64(row.get('ethAmount', 0))
                    if eth_amount <= 0:
                        continue
                except ValueError:
                    continue

                if not addr.startswith('0x') or addr == "0x" + "0"*40:
                    continue

                try:
                    # 以太主链上数据获取
                    checksum_addr = w3.to_checksum_address(addr)
                    data = pool_contract.functions.getUserAccountData(checksum_addr).call()
                    
                    # 高精度计算 (使用 np.float64)
                    # Aave Base 精度通常为 10^8
                    collateral_usd = np.float64(data[0]) / np.float64(1e8)
                    debt_usd = np.float64(data[1]) / np.float64(1e8)
                    threshold = np.float64(data[3]) / np.float64(10000)
                    hf = np.float64(data[5]) / np.float64(1e18)

                    # 计算清算价格
                    if debt_usd > 0:
                        # 核心公式：Liq Price = Debt / (Collateral_Quantity * Threshold)
                        # 这里 Collateral_Quantity = Collateral_USD / Current_Price
                        eth_inventory = collateral_usd / current_price
                        liq_price = debt_usd / (eth_inventory * threshold)
                    else:
                        liq_price = np.float64(0.0)

                    # 存储原始高精度数据
                    results.append({
                        "walletAddress": addr,
                        "healthFactor": hf,
                        "liquidationPrice": liq_price,
                        "totalDebtUSD": debt_usd,
                        "totalCollateralUSD": collateral_usd
                    })

                    if i % 1000 == 0:
                        print(f"已扫描 {i} 条，当前发现有效借贷地址 {len(results)} 个...")

                except Exception as e:
                    print(f"❌ 地址 {addr} 调用失败: {e}")

        # 保存结果：仅在输出时控制精度 ---
            with open(OUTPUT_FILE, mode='w', newline='') as f:
                fieldnames = ["walletAddress", "healthFactor", "liquidationPrice", "totalDebtUSD", "totalCollateralUSD"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            
            for res in results:
                writer.writerow({
                    "walletAddress": res["walletAddress"],
                    "healthFactor": f"{res['healthFactor']:.8f}", # 保留 8 位小数观察微小变动
                    "liquidationPrice": f"{res['liquidationPrice']:.2f}",
                    "totalDebtUSD": f"{res['totalDebtUSD']:.2f}",
                    "totalCollateralUSD": f"{res['totalCollateralUSD']:.2f}"
                })

            print(f"✅ 任务完成！共处理 {len(results)} 个有效地址。")

if __name__ == "__main__":
    run_analysis()
