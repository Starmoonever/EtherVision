import web3
print("Web3 库连接成功！版本号：", web3.__version__)

#验证python与私有节点连接是否成功，查看最新块高
from web3 import Web3

RPC_URL = "http://10.8.6.153:2700/" 
w3 = Web3(Web3.HTTPProvider(RPC_URL))

is_connected = w3.is_connected()
block_number = w3.eth.block_number
if is_connected:    
    print(f"✅ 成功连接到公司私有节点！")
    print(f"当前节点最新区块高度: {block_number}")
else:
    print(f"❌ 无法连接到节点，请检查是否在公司内网或 VPN 是否开启。")