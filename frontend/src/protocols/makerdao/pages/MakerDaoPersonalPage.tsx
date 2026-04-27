import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { isAddress } from 'viem';
import { AddressInput } from '../../../components/AddressInput';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';
import {
  MakerDaoPersonalDashboard,
  MakerDaoSystemPositionDashboard,
} from '../components/MakerDaoPersonalDashboard';

interface MakerDaoPersonalPageProps {
  address: string;
  error: string;
  onSearch: (address: string) => void;
}

type MakerDaoPositionMode = 'regular' | 'system';

const MAKERDAO_REGULAR_HISTORY_KEY = 'search_history_makerdao_regular';
const MAKERDAO_SYSTEM_HISTORY_KEY = 'search_history_makerdao_system';
const MAKERDAO_SYSTEM_HISTORY_LIMIT = 50;

function MakerDaoPositionModeSwitch({
  value,
  onChange,
}: {
  value: MakerDaoPositionMode;
  onChange: (value: MakerDaoPositionMode) => void;
}) {
  const options: Array<{ value: MakerDaoPositionMode; label: string }> = [
    { value: 'regular', label: '普通仓位' },
    { value: 'system', label: '系统仓位' },
  ];

  return (
    <div className="switch-group makerdao-position-mode-switch" aria-label="MakerDAO 仓位类型">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`switch-btn ${value === option.value ? 'active' : ''}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function normalizeEvmAddress(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  return trimmed.startsWith('0x') || trimmed.startsWith('0X') ? trimmed : `0x${trimmed}`;
}

function MakerDaoSystemUrnSearch({ onSearch }: { onSearch: (urn: string) => void }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(MAKERDAO_SYSTEM_HISTORY_KEY);
      setHistory(stored ? JSON.parse(stored) : []);
    } catch (storageError) {
      setHistory([]);
      console.error('Failed to load MakerDAO system urn history', storageError);
    }
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setShowHistory(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const saveHistory = (urn: string) => {
    const nextHistory = [urn, ...history.filter((item) => item !== urn)].slice(
      0,
      MAKERDAO_SYSTEM_HISTORY_LIMIT,
    );
    setHistory(nextHistory);
    localStorage.setItem(MAKERDAO_SYSTEM_HISTORY_KEY, JSON.stringify(nextHistory));
  };

  const clearHistory = () => {
    setHistory([]);
    localStorage.removeItem(MAKERDAO_SYSTEM_HISTORY_KEY);
  };

  const searchUrn = (urn: string) => {
    setError('');
    setValue(urn);
    setShowHistory(false);
    saveHistory(urn);
    onSearch(urn);
  };

  const submitSystemPosition = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const urn = normalizeEvmAddress(value);

    if (!urn || !isAddress(urn, { strict: false })) {
      setError('请输入有效的系统 urn 地址');
      return;
    }

    searchUrn(urn);
  };

  return (
    <form onSubmit={submitSystemPosition} className="input-form">
      <div className="input-row">
        <div className="input-wrapper" ref={wrapperRef}>
          <input
            type="text"
            value={value}
            onFocus={() => setShowHistory(true)}
            onChange={(event) => {
              setValue(event.target.value);
              setError('');
            }}
            placeholder="输入 MakerDAO 系统 urn 地址 (0x...)"
            className="address-input"
            spellCheck={false}
          />

          {showHistory && history.length > 0 ? (
            <div className="history-dropdown">
              <div className="history-header">
                <span>搜索记录</span>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    clearHistory();
                  }}
                  className="clear-history-btn"
                >
                  清除记录
                </button>
              </div>
              <ul className="history-list">
                {history.map((urn) => (
                  <li
                    key={urn}
                    className="history-item"
                    onClick={() => {
                      searchUrn(urn);
                    }}
                  >
                    {urn}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        <button type="submit" className="search-btn">
          查询仓位
        </button>
      </div>
      {error ? <p className="input-error">{error}</p> : null}
    </form>
  );
}

export function MakerDaoPersonalPage({ address, error, onSearch }: MakerDaoPersonalPageProps) {
  const [mode, setMode] = useState<MakerDaoPositionMode>('regular');
  const [systemQuery, setSystemQuery] = useState<{ urn: string } | null>(null);

  return (
    <>
      <PageHero
        title="MakerDAO 个人账户分析"
        subtitle="MakerDAO Vault 抵押债务、健康因子与清算价格概览"
      />

      <div className="makerdao-position-mode-row">
        <MakerDaoPositionModeSwitch value={mode} onChange={setMode} />
      </div>

      {mode === 'regular' ? (
        <>
          <AddressInput
            onSearch={onSearch}
            loading={false}
            historyKey={MAKERDAO_REGULAR_HISTORY_KEY}
            placeholder="输入 MakerDAO owner / proxy / urn 地址 (0x...)"
          />
          <ErrorNotice message={error} />

          {address ? (
            <div className="results-container">
              <ResultPanel>
                <MakerDaoPersonalDashboard address={address} />
              </ResultPanel>
            </div>
          ) : null}
        </>
      ) : (
        <>
          <MakerDaoSystemUrnSearch onSearch={(urn) => setSystemQuery({ urn })} />

          {systemQuery ? (
            <div className="results-container">
              <ResultPanel>
                <MakerDaoSystemPositionDashboard urn={systemQuery.urn} />
              </ResultPanel>
            </div>
          ) : null}
        </>
      )}
    </>
  );
}
