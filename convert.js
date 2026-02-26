const fs = require('fs');
try {
    const data = JSON.parse(fs.readFileSync('all_aave_eth_users.json', 'utf8'));
    const csvRows = ['walletAddress,ethAmount']; // 表头
    data.forEach(item => csvRows.push(`${item.walletAddress},${item.ethAmount}`));
    fs.writeFileSync('all_aave_eth_users.csv', csvRows.join('\n'));
    console.log("CSV 已生成！");
} catch (error) {
    console.error("❌ 转换失败:", error.message);
}
