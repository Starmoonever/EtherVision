//React 结合 TypeScript 开发前端界面，创建一个钱包地址搜索框，负责管理用户输入的状态，校验以太坊地址是否合法。//

// useState: 记住在搜索框里输入的文字。
// isAddress: 判断一段字符串是否符合以太坊地址格式
import { useState } from 'react';
import { isAddress } from 'viem';

// 定义接口，该组件接收的参数
interface Props {
  // 函数 onSearch: 用户点击查询按钮时调用，传入用户输入的地址
  onSearch: (address: string) => void;
  // 布尔值，是否正在查询链上数据
  loading: boolean;
}

// 组件函数 AddressInput，接收 Props 参数
export function AddressInput({ onSearch, loading }: Props) {
  // 状态变量 value: 存储用户在搜索框里的输入
  const [value, setValue] = useState('');
  // 状态变量 error: 存储校验过程中的错误提示信息
  const [error, setError] = useState('');

  // 处理表单提交事件
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault(); // 阻止浏览器刷新
    // 移除首尾空格
    const trimmed = value.trim();
    // 如果钱包地址为空
    if (!trimmed) {
      // 设置报错信息
      setError('请输入抵押ETH的钱包地址');
      //终止执行并返回，不进行后续搜索。
      return;
    }
    // 检验地址是否符合格式
    if (!isAddress(trimmed)) {
      setError('抵押ETH的钱包地址格式无效');
      return;
    }
    // 地址正确，则清空之前的错误提示
    setError('');
    // 将合规地址传给 onSearch 函数，触发Aave 里 的API 调用
    onSearch(trimmed);
  };

  
  return (
    <form onSubmit={handleSubmit} className="input-form">
      <div className="input-row">
        <input
          type="text"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError('');
          }}
          placeholder="输入抵押ETH的钱包地址 (0x...)"
          className="address-input"
          spellCheck={false}
          disabled={loading}
        />
        <button type="submit" className="search-btn" disabled={loading}>
          {loading ? '查询中…' : '查询仓位'}
        </button>
      </div>
      {error && <p className="input-error">{error}</p>}
    </form>
  );
}
