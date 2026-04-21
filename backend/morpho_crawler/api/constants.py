"""Morpho FastAPI 层常量。

当前仅承载 GET /api/morpho/markets 分页接口使用的硬编码市场列表。
"""

from __future__ import annotations

# api/morpho/markets相关：硬编码 market_id + pair（来源 tmp/top_200_markets_by_total_market_size.json：
# TVL 降序，跳过 collateral 为空、跳过 loan+collateral 与已选重复；pair 使用「借出 : 抵押」避免 symbol 内含 - 时歧义）
MORPHO_MARKETS_HARDCODED: list[tuple[str, str]] = [
    (
        "0x64d65c9a2d91c36d56fbc42d69e979335320169b3df63bf92789e2c8883fcc64",
        "USDC : cbBTC",
    ),
    (
        "0x3274643db77a064abd3bc851de77556a4ad2e2f502f4f0c80845fa8f909ecf0b",
        "USDT : sUSDS",
    ),
    (
        "0xe7e9694b754c4d4f7e21faf7223f6fa71abaeb10296a4c43a54a7977149687d2",
        "USDT : wstETH",
    ),
    (
        "0x3a85e619751152991742810df6ec69ce473daef99e28a64ab2340d7b7ccfee49",
        "USDC : WBTC",
    ),
    (
        "0x90ef0c5a0dc7c4de4ad4585002d44e9d411d212d2f6258e94948beecf8b4c0d5",
        "PYUSD : sUSDe",
    ),
    (
        "0xb323495f7e4148be5643a4ea4a8221eef163e4bccfdedc2a6f4696baacbc86cc",
        "USDC : wstETH",
    ),
    (
        "0x1590cb22d797e226df92ebc6e0153427e207299916e7e4e53461389ad68272fb",
        "USDC : wsrUSD",
    ),
    (
        "0xa921ef34e2fc7a27ccc50ae7e4b154e16c9799d3387076c421423ef52ac4df99",
        "USDT : WBTC",
    ),
    (
        "0xb8fc70e82bc5bb53e773626fcc6a23f7eefa036918d7ef216ecfb1950a94a85e",
        "WETH : wstETH",
    ),
    (
        "0xe83d72fa5b00dcd46d9e0e860d95aa540d5ec106da5833108a9f826f21f36f52",
        "USDC : AA_FalconXUSDC",
    ),
    (
        "0xc0ae375fd761ff19b3f04de5534c0f1ec110f80e1c2ede27c42c1c43c3040394",
        "RLUSD : syrupUSDC",
    ),
    (
        "0x37e7484d642d90f14451f1910ba4b7b8e4c3ccdd0ec28f8b2bdb35479e472ba7",
        "WETH : weETH",
    ),
    (
        "0xf6a056627a51e511ec7f48332421432ea6971fc148d8f3c451e14ea108026549",
        "WBTC : LBTC",
    ),
    (
        "0x88a18b2f4d94e7ad27a381b15531c06abf05a7c99dd5d3c3679875fed6f7e742",
        "USDtb : sUSDe",
    ),
    (
        "0x85d59152eeeab7ca024804895b358868d8dd1e134171be400d7792d5604a212c",
        "PYUSD : weETH",
    ),
    (
        "0xa9f70093360419b4544f17a4553ac5847d896be23f020295bd95c24af4df700e",
        "USDT : wsrUSD",
    ),
    (
        "0x45671fb8d5dea1c4fbca0b8548ad742f6643300eeb8dbd34ad64a658b2b05bca",
        "USDT : cbBTC",
    ),
    (
        "0x5cebfae10f5e88d33df2421923f3d9f32359429fda2f78edacc9b4fdb09b0553",
        "USDC : PT-USDG-28MAY2026",
    ),
    (
        "0xeb17955ea422baeddbfb0b8d8c9086c5be7a9cfdefb292119a102e981a30062e",
        "USDC : stcUSD",
    ),
    (
        "0xa75bb490ecfee90c86a9d22ebc2dde42fb83478b3f18722b9fc6f5f668cab124",
        "USDC : PT-apyUSD-18JUN2026",
    ),
    (
        "0xef2c308b5abecf5c8750a1aa82b47c558005feb7a03f4f8e1ad682d71ac8d0ba",
        "USDC : mF-ONE",
    ),
    (
        "0x9bc98c2f20ac58287ef2c860eea53a2fdc27c17a7817ff1206c0b7840cc7cd79",
        "USDC : PT-reUSD-25JUN2026",
    ),
    (
        "0x09cf702bb8b6fe8c6effb6021744e365f598b89bc28f3ea7cd6c55115af825df",
        "AUSD : sUSDS",
    ),
    (
        "0xd570c19c0dc0fbe4ab7faf4a37c4150e1c141c8aada8ca3e1b4b6c1b712af93d",
        "USDC : stUSDS",
    ),
    (
        "0xc9629945524f3fde56c7e8854a6c3d48e76b9d97236abbe73c750fcc7aeb8501",
        "PYUSD : syrupUSDC",
    ),
    (
        "0xb7a75cabc2e8eadd0bc661340a9e359d9828bed6d5cbbcd64188bca8c01e399e",
        "EURCV : WBTC",
    ),
    (
        "0x5f8a138ba332398a9116910f4d5e5dcd9b207024c5290ce5bc87bc2dbd8e4a86",
        "WETH : ETH+",
    ),
    (
        "0x61765602144e91e5ac9f9e98b8584eae308f9951596fd7f5e0f59f21cd2bf664",
        "USDC : weETH",
    ),
    (
        "0x0b352b7550acdb1f39fea4b8f9ef8ac2d7953613b92599610b8fbec8a98a51d1",
        "EURCV : wstETH",
    ),
    (
        "0x94b823e6bd8ea533b4e33fbc307faea0b307301bc48763acc4d4aa4def7636cd",
        "USDC : WETH",
    ),
    (
        "0x29ae8cad946d861464d5e829877245a863a18157c0cde2c3524434dafa34e476",
        "USDT : sUSDD",
    ),
    (
        "0xf135feb27b5f2bd2d54f344fd38dbb5161ff7f0ef4494901fb23f2fe8e58145a",
        "EURCV : steakUSDC",
    ),
    (
        "0xaa7231d6bee28b578efe38b52e801d5d3067023853342fc06ded437d2a80ef98",
        "EURCV : EUTBL",
    ),
    (
        "0x82053fe2fc3a3d6cb856458948e9c3589e76f20f3a2079606739b517587267ce",
        "EURCV : cbBTC",
    ),
    (
        "0xbbf7ce1b40d32d3e3048f5cf27eeaa6de8cb27b80194690aab191a63381d8c99",
        "USDC : siUSD",
    ),
    (
        "0x2fb3713487c7812e7309935b034f40228841666f6b048faf31fd2110ae674f20",
        "USDC : PT-stcUSD-23JUL2026",
    ),
    (
        "0x702b7ec7628de2622e51e1bb34a7e6ad9e95f3a25a2ed361e4ce621f23f5e642",
        "USDC : PT-cUSD-23JUL2026",
    ),
    (
        "0x582fdc4176da0ab5c65e086603ab9ecd9188e889e16efef6e35854cf14e15065",
        "AUSD : sUSDat",
    ),
    (
        "0x64d2f82e674b764d618b630297813cd34bdc42a0fa66f92efa2ac8b1efe4bbd5",
        "msUSD : siUSD",
    ),
    (
        "0xdbf4bc065d4e76f4505a523f2bba5e5ccdca94c16d67c3a6ff1dadbcbb26d4aa",
        "USDT : stcUSD",
    ),
    (
        "0x8924445a76b678c536df977ed9222fb0b23ee5311497dd0223fe6270bb20b4e6",
        "USDC : sUSN",
    ),
    (
        "0xb8fef900b383db2dbbf4458c7f46acf5b140f26d603a6d1829963f241b82510e",
        "USDC : OETH",
    ),
    (
        "0xea4bfb18df0ee6bffb7b3f0270899a8adb92ab6b684709634c8276128813cfd4",
        "RLUSD : weETH",
    ),
    (
        "0xcb12dcbc7c6c4f20ca1537a3cc1a41ec27501f85a3e322a710d9a16a88a28c0e",
        "PYUSD : PT-sUSDE-7MAY2026",
    ),
    (
        "0xe9d96a2f8042486bfd8cfd22692e49cd355e8a51da2f427bdb2d3671fbe978ea",
        "AUSD : upGAMMAusdc",
    ),
    (
        "0xf5c5df23559b0fb56560a7578ea17d81e245153ba64b8132df026c9358864d27",
        "PYUSD : wstETH",
    ),
    (
        "0xe07d416323a1afbfe0bf2fe27ffb549ff565cf5c86d21b79fc60664038e597c9",
        "USDC : savUSD",
    ),
    (
        "0xff527fe9c6516f9d82a3d51422ccb031d123266e6e26d4c22c942a948c180a75",
        "EURC : WBTC",
    ),
    (
        "0xd98cd88ae5b336086b39fb1d62ba6171282e946105b010143f0e89f8fe7cff36",
        "WETH : savETH",
    ),
    (
        "0xab3196447663a41382ba4b4d55eab3fa702ee2cf071db224fd72492953040056",
        "AUSD : syrupUSDC",
    ),
    (
        "0x3c16c2d107caade490b1d513ccc54cbd06a30f20ad6a9aaad8c744413872514a",
        "wstETH : ynETHx",
    ),
    (
        "0x3fea56ab83b05840dc83dc6b3d2f2fbd938147cbaa8126bac529e6c820058253",
        "USDT : PT-reUSD-25JUN2026",
    ),
    (
        "0xb7843fe78e7e7fd3106a1b939645367967d1f986c2e45edb8932ad1896450877",
        "USDT : XAUt",
    ),
    (
        "0xf4e9fb49e95a34320aea8b5e0ef515391a72368c39bdcf8ad8910645fd6eab97",
        "USDC : syzUSD",
    ),
    (
        "0xbf02d6c6852fa0b8247d5514d0c91e6c1fbde9a168ac3fd2033028b5ee5ce6d0",
        "USDC : LBTC",
    ),
    (
        "0xd8a8e6667f58aa9229e8979bd619742b1660ee856c200a93e407dbccb7222323",
        "PYUSD : cbBTC",
    ),
    (
        "0xc2c53d2b868e163da71de14a5113cc2743fc9b5ad7488334720ed2846566a8f6",
        "USDT : weETH",
    ),
    (
        "0xfd039edc69eac5eaab4a10463fdbcaca75d6eddb1f0e00248d73fc977fb2554b",
        "USDT : PT-cUSD-23JUL2026",
    ),
    (
        "0x5eaaebc81e9e27972ab458811d1b60828e8ab51ef6620f9b3918fd7e68eecec1",
        "USDT : PT-stcUSD-23JUL2026",
    ),
    (
        "0x3e29fdb9fefb8930c040f661368c505edc5081e86112c6da4238d683f6f282ac",
        "rUSD : wsrUSD",
    ),
    (
        "0xe23380494e365453f72f736f2d941959ae945773eb67a06cf4f538c7c4201264",
        "apxUSD : apyUSD",
    ),
    (
        "0xa4774e3e693fff2ebd1dcbbd69b1b0a5b9bb0ccc753bfda5dd07bdac97c4818a",
        "USDT : syrupUSDT",
    ),
    (
        "0x4565ac05d38b19374ccbb04c17cca60ca9353cd41824f0803d0fc7704f60eaed",
        "USDC : reUSD",
    ),
    (
        "0x23a7d0ff682b323363fb8ba58327ed87001f6306e09b7fd7413bbe4698e749c8",
        "USDC : msY",
    ),
    (
        "0xc9098061d437a9dd53b0070cb33df6fca1a0a5ead288588c88699b0420c1c078",
        "msUSD : sUSDe",
    ),
    (
        "0xd2630c0ebf33ba83c82e8cd400a8e6345370238ca695ce58773b2d3e43de1b0a",
        "msETH : ynETHx",
    ),
    (
        "0xf80a664057fe3cadcd9e83f27bb1effe5c15d1d2648acc7634daff1581951b5e",
        "USDC : PT-avUSD-14MAY2026",
    ),
    (
        "0xed05fcc2893b78b3fa468d21b6e4d2925e7f2c64eb1f16279757c43f87502a99",
        "USDC : PT-apxUSD-18JUN2026",
    ),
    (
        "0xe1b65304edd8ceaea9b629df4c3c926a37d1216e27900505c04f14b2ed279f33",
        "USDC : RLP",
    ),
    (
        "0x6a7e36eb088bd501d73f7ab4c5b8671358559341a78ce521c9e499dc0bc642b9",
        "PYUSD : LBTC",
    ),
    (
        "0xae60b71b407e0517ead445b7113a7ffa07ea4a9379d526ade541a3e9ec777cb4",
        "USDC : sNUSD",
    ),
    (
        "0x5d41b8d23ccf6d9e9f7e2b1b357d92bba6ef0367d6ef8ceda965f73e52108461",
        "USDC : USP",
    ),
    (
        "0xc978f01522ff64adafd91856065d602c56e326a0368b895bd9244d5998e60076",
        "USDC : PT-savUSD-14MAY2026",
    ),
    (
        "0xa84573d73bcd78cd295b3a35b4419877584a4cc3208161128addf15d9a90e5fb",
        "AUSD : WBTC",
    ),
    (
        "0xc2bc5e1e304fb1ea103dcbee37ece3c7e9219fb4b2b19d8ffdf81c39f4fbf180",
        "USDC : PT-srNUSD-28MAY2026",
    ),
    (
        "0xa0c6499787a7d046f91f2687558c021e2baae5a378885280a448183a926ef5f7",
        "USDC : upUSDC",
    ),
    (
        "0x01e26c10a6589d17495ff9c4385502065766e7535a2f459b2c2a1b3f9015d97b",
        "USDC : muBOND",
    ),
    (
        "0x24a1ac1fb21a206906af5acf2d65a6e6d9627823c195efef112d3a9b6cd5eab6",
        "frxUSD : stakedao-FrxMsUSD",
    ),
    (
        "0x693ba455f49e69daba49904640dab1277538c5f4e524da79b2ec2070d12f694e",
        "AUSD : WETH",
    ),
    (
        "0x5de846e07c99a4a11060462006d033ff7bbccef63c414d6d3c6a6876fa6af18f",
        "AUSD : cbBTC",
    ),
    (
        "0xce68c7aa336675e42bbc8eaa8b5ecc7ebd816bf8625b5316330c6ac2dabc4cf2",
        "WBTC : SolvBTC",
    ),
    (
        "0x77e624dd9dd980810c2b804249e88f3598d9c7ec91f16aa5fbf6e3fdf6087f82",
        "USDS : stUSDS",
    ),
    (
        "0xfcd3b104b9a592d4377edd68f48ecf60082d787b64ca97a3385f3cc4cb9bd20f",
        "AUSD : wstETH",
    ),
    (
        "0x987134eb4716fc3dee2cb9ca8d8fba692389f7e43c717db4fe0cedaf287816e9",
        "LINK : wstLINK",
    ),
    (
        "0x0a15460ad263c2186fe0b5df20a8cf71d55f3cfa06de15edcf6138f6b8edd8bf",
        "USDC : rETH",
    ),
    (
        "0x138eec0e4a1937eb92ebc70043ed539661dd7ed5a89fb92a720b341650288a40",
        "WETH : WBTC",
    ),
    (
        "0x2f4ea313fb7df23a82c19d95e8b90acc8179bd053e0d9ef745cdf28d6a49499c",
        "USDS : cbBTC",
    ),
    (
        "0x6d95bf5fad1b0427205ee2b595f80b52e22394173de0832efa79fde88abb8525",
        "USDC : MORPHO",
    ),
    (
        "0xba5bb3ccec8df00a56ac1f4d97ae0fd1461f262b6d4f29631bdec717fa6017fd",
        "USDtb : USDe",
    ),
    (
        "0xb62aac664f81d19f21a158aa0373967ef60fd1ac8de4a9091bd225c007973ca6",
        "USDC : PT-sNUSD-4JUN2026",
    ),
    (
        "0x7421c2741e064e8c53fcb5de9faf7f0025dce75bc1caf26774dd878291c81dac",
        "EURC : wstETH",
    ),
    (
        "0x2cbfb38723a8d9a2ad1607015591a78cfe3a5949561b39bde42c242b22874ec0",
        "WETH : cbBTC",
    ),
    (
        "0xbf0432567b44ef5ce013ffcd7dd756c522252503f7986a406e780715b32c74fc",
        "AUSD : wSPYx",
    ),
    (
        "0x7629b62c42febfccd87a8eb76bd91587b33bbcd474cb79bc4964aeb0479e4e53",
        "frxUSD : stakedao-crvfrxUSD",
    ),
    (
        "0xb374528d44b6ab6e0cecc87e0481f45d892f38baec90c1d318851969ec14ea5f",
        "USDS : wstETH",
    ),
    (
        "0x12cacbbd1c88513cce13d54927f5f1301335779353817bc5e791e71d200f2199",
        "USDS : WETH",
    ),
    (
        "0xf3814af4869a6ce59ffef016e555dd4c1e92bf383b5ab89abe496044c6364746",
        "apxUSD : PT-apxUSD-18JUN2026",
    ),
    (
        "0xf2e2a93732723b3b6718425bdbb9438730d733b12803c55d98200de4e82179e1",
        "cbBTC : mHyperBTC",
    ),
    (
        "0x0d55c325847ed87d53506c2aca7de046cb59d8c22928fd55fb2790c4811d20db",
        "msETH : rswETH",
    ),
    (
        "0x3d353ef0436b85c3b12d53536c19b21c533c046b07c9d92d791a1510e7ef0b74",
        "USDC : PT-mAPOLLO-30APR2026",
    ),
]

# api/morpho/markets相关：Morpho Blue GraphQL 使用的链 ID（Ethereum mainnet）
MORPHO_MARKETS_BLUE_API_CHAIN_ID = 1

# api/morpho/markets相关：Morpho 官方 Blue API（与 app 市场数据同源）
MORPHO_BLUE_GRAPHQL_URL = "https://blue-api.morpho.org/graphql"
