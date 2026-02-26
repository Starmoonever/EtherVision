import { useState } from 'react';
import { isAddress } from 'viem';

interface Props {
  onSearch: (address: string) => void;
  loading: boolean;
}

export function AddressInput({ onSearch, loading }: Props) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      setError('请输入以太坊地址');
      return;
    }
    if (!isAddress(trimmed)) {
      setError('无效的以太坊地址格式');
      return;
    }
    setError('');
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
          placeholder="输入以太坊账户地址 (0x...)"
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
