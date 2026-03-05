//发送GraphQL 查询语句至 The Graph，返回账户数据//
const axios = require('axios');
//读取 query.graphql 文件内容，将抓取数据保存在电脑内存中//
const fs = require('fs');

//在studio获取的API//
const API_KEY = '652e441841a17e3465aca75fe092fa0c'; 
const SUBGRAPH_URL = `https://gateway.thegraph.com/api/${API_KEY}/subgraphs/id/GQFbb95cE6d8mV989mL5figjaGaKCQB3xqYrr1bRyXqF`;

async function run() {
    let allUsers = [];
    let lastId = "0x0000000000000000000000000000000000000000"; // 从零地址开始找
    let hasMore = true;

    console.log("开始获取全部抵押 ETH 的账户数据...");

    const gqlQuery = fs.readFileSync('./query.graphql', 'utf8');

    try {
        while (hasMore) {
            const response = await axios.post(SUBGRAPH_URL, {
                query: gqlQuery,
                variables: { lastId: lastId }
            });

            //如果报错，打印出完整的错误信息//
            if (response.data.errors) {
                console.error("❌ GraphQL 返回了错误:", JSON.stringify(response.data.errors, null, 2));
                return;
            }
            const data = response.data.data.userReserves;

            if (!data || data.length === 0) {
                hasMore = false; // 没有更多数据了，停止循环
            } else {
                // 将本次获取的 1000 条数据加入总列表
                allUsers = allUsers.concat(data);
                // 更新 lastId 为当前这批数据的最后一个 ID，用于下次查询的起点
                lastId = data[data.length - 1].id;
                console.log(`已下载 ${allUsers.length} 个账户...`);
            }
        }

        // 格式化数据方便阅读
        const result = allUsers.map(item => ({
            walletAddress: item.user.id,
            ethAmount: (Number(item.currentATokenBalance) / 1e18).toFixed(6)
        }));

        // 写入本地文件
        fs.writeFileSync('all_aave_eth_users.json', JSON.stringify(result, null, 2));
        console.log(`\n✅ 抓取成功！`);
        console.log(`共计：${result.length} 个账户`);
        console.log(`文件已保存至：all_aave_eth_users.json`);

    } catch (error) {
        if (error.response) {
            console.error("❌ 服务器响应错误:", error.response.data);
        } else {
            console.error("❌ 请求失败:", error.message);
        }
    }
}

run();