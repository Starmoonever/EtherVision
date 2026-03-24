//React 结合 TypeScript 开发前端界面，创建一个钱包地址搜索框，负责管理用户输入的状态，校验以太坊地址是否合法。//

// useState: 记住在搜索框里输入的文字。
// isAddress: 判断一段字符串是否符合以太坊地址格式
import { useState, useEffect, useRef } from 'react';
import { isAddress } from 'viem';

// 定义接口，该组件接收的参数
interface Props {
  // 函数 onSearch: 用户点击查询按钮时调用，传入用户输入的地址
  onSearch: (address: string) => void;
  // 布尔值，是否正在查询链上数据
  loading: boolean;
  historyKey?: string;
  placeholder?: string;
}

const DEFAULT_STORAGE_KEY = 'search_history';
const MAX_HISTORY = 50;

// 组件函数 AddressInput，接收 Props 参数
export function AddressInput({
  onSearch,
  loading,
  historyKey = DEFAULT_STORAGE_KEY,
  placeholder = '输入钱包地址 (0x...)',
}: Props) {
  // 状态变量 value: 存储用户在搜索框里的输入
  const [value, setValue] = useState('');
  // 状态变量 error: 存储校验过程中的错误提示信息
  const [error, setError] = useState('');
  // 历史记录
  const [history, setHistory] = useState<string[]>([]);
  // 是否显示历史记录
  const [showHistory, setShowHistory] = useState(false);
  // 引用 wrapper 元素，用于点击外部关闭下拉框
  const wrapperRef = useRef<HTMLDivElement>(null);

  // 加载历史记录
  useEffect(() => {
    try {
      const stored = localStorage.getItem(historyKey);
      if (stored) {
        setHistory(JSON.parse(stored));
      }
    } catch (e) {
      console.error('Failed to load history', e);
    }
  }, [historyKey]);

  // 点击外部关闭下拉框
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setShowHistory(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const saveHistory = (address: string) => {
    const newHistory = [address, ...history.filter((h) => h !== address)].slice(0, MAX_HISTORY);
    setHistory(newHistory);
    localStorage.setItem(historyKey, JSON.stringify(newHistory));
  };

  const clearHistory = () => {
    setHistory([]);
    localStorage.removeItem(historyKey);
  };

  const handleHistoryClick = (address: string) => {
    setValue(address);
    setError('');
    setShowHistory(false);
    onSearch(address);
    // Move to top of history
    saveHistory(address);
  };

  // 处理表单提交事件
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault(); // 阻止浏览器刷新
    // 移除首尾空格
    let trimmed = value.trim();
    // 如果钱包地址为空
    if (!trimmed) {
      // 设置报错信息
      setError('请输入抵押ETH的钱包地址');
      //终止执行并返回，不进行后续搜索。
      return;
    }

    // 容错处理：如果用户没有输入 0x 前缀，自动补全
    if (!trimmed.startsWith('0x') && !trimmed.startsWith('0X')) {
      trimmed = '0x' + trimmed;
    }

    // 检验地址是否符合格式
    // 即使是没有 checksum 的纯大写或纯小写地址，只要长度是 42，isAddress 也能判断其为 true。
    // 但是如果地址混合了大小写且 checksum 错误，isAddress 可能会返回 false，因此这里使用 isAddress 进行宽松验证。
    if (!isAddress(trimmed, { strict: false })) {
      setError('抵押ETH的钱包地址格式无效');
      return;
    }
    // 地址正确，则清空之前的错误提示
    setError('');

    // 保存历史记录
    saveHistory(trimmed);

    // 将合规地址传给 onSearch 函数，触发Aave 里 的API 调用
    onSearch(trimmed);
    setShowHistory(false);
  };

  /* 定义用户在页面上看到的输入框什么样，用户输入时，程序如何实时响应。*/
  return (
    /* 表单提交时触发 handleSubmit 函数 */
    <form onSubmit={handleSubmit} className="input-form">
      <div className="input-row">
        <div className="input-wrapper" ref={wrapperRef}>
          {/* 输入框 ,用户输入时，实时更新 value 状态 */}
          <input
            type="text"
            value={value}
            onFocus={() => setShowHistory(true)}
            onChange={(e) => {
              setValue(e.target.value); /* 实时更新 value 内容 */
              setError(''); /* 清空之前的错误提示 */
            }}
            placeholder={placeholder}
            className="address-input"
            spellCheck={false}
            disabled={loading}
          />

          {showHistory && history.length > 0 && (
            <div className="history-dropdown">
              <div className="history-header">
                <span>搜索记录</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    clearHistory();
                  }}
                  className="clear-history-btn"
                >
                  清除记录
                </button>
              </div>
              <ul className="history-list">
                {history.map((addr) => (
                  <li key={addr} className="history-item" onClick={() => handleHistoryClick(addr)}>
                    {addr}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <button type="submit" className="search-btn" disabled={loading}>
          {loading ? '查询中…' : '查询仓位'}
        </button>
      </div>
      {error && <p className="input-error">{error}</p>}
    </form>
  );
}
