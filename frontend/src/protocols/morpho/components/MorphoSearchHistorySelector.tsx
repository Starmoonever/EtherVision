/**
 * MorphoSearchHistorySelector - 搜索历史选择器组件
 * 支持按 address 或 marketId 过滤，展示相关的搜索记录
 */

import { useState } from 'react';
import type { MorphoSearchRecord } from '../../../api/morpho-search-history';

interface MorphoSearchHistorySelectorProps {
  // 当前选中的 address（可选，用于按 address 过滤市场）
  currentAddress?: string;

  // 当前选中的 marketId（可选，用于按 market 过滤地址）
  currentMarketId?: string;

  // 搜索历史记录
  records: MorphoSearchRecord[];

  // 选择回调
  onSelect: (address: string, marketId: string) => void;

  // 删除回调
  onDelete?: (address: string, marketId: string) => void;
}

export function MorphoSearchHistorySelector({
  currentAddress,
  currentMarketId,
  records,
  onSelect,
  onDelete,
}: MorphoSearchHistorySelectorProps) {
  const [filterMode, setFilterMode] = useState<'address' | 'market' | 'all'>('all');

  // 过滤逻辑
  let filtered = records;

  if (filterMode === 'address' && currentAddress) {
    filtered = records.filter((r) => r.address.toLowerCase() === currentAddress.toLowerCase());
  } else if (filterMode === 'market' && currentMarketId) {
    filtered = records.filter((r) => r.marketId.toLowerCase() === currentMarketId.toLowerCase());
  }

  // 按时间倒序排列
  filtered = filtered.sort((a, b) => b.timestamp - a.timestamp);

  if (records.length === 0) {
    return (
      <div style={{ padding: '1rem', textAlign: 'center', color: '#94a3b8' }}>暂无搜索历史</div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {/* 过滤切换 */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <button
          onClick={() => setFilterMode('all')}
          style={{
            padding: '0.4rem 0.8rem',
            background: filterMode === 'all' ? '#0f172a' : '#1e293b',
            color: '#cbd5e1',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '0.85rem',
          }}
        >
          全部 ({records.length})
        </button>

        {currentAddress && (
          <button
            onClick={() => setFilterMode('address')}
            style={{
              padding: '0.4rem 0.8rem',
              background: filterMode === 'address' ? '#0f172a' : '#1e293b',
              color: '#cbd5e1',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            此地址的市场 (
            {records.filter((r) => r.address.toLowerCase() === currentAddress.toLowerCase()).length}
            )
          </button>
        )}

        {currentMarketId && (
          <button
            onClick={() => setFilterMode('market')}
            style={{
              padding: '0.4rem 0.8rem',
              background: filterMode === 'market' ? '#0f172a' : '#1e293b',
              color: '#cbd5e1',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            此市场的地址 (
            {
              records.filter((r) => r.marketId.toLowerCase() === currentMarketId.toLowerCase())
                .length
            }
            )
          </button>
        )}
      </div>

      {/* 记录列表 */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          maxHeight: '400px',
          overflowY: 'auto',
        }}
      >
        {filtered.length === 0 ? (
          <div
            style={{
              padding: '0.75rem',
              textAlign: 'center',
              color: '#94a3b8',
              fontSize: '0.875rem',
            }}
          >
            无匹配记录
          </div>
        ) : (
          filtered.map((record) => (
            <div
              key={`${record.protocol}:${record.marketId}:${record.address}`}
              onClick={() => onSelect(record.address, record.marketId)}
              style={{
                padding: '0.75rem',
                background: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '4px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#0f172a';
                e.currentTarget.style.borderColor = '#475569';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#1e293b';
                e.currentTarget.style.borderColor = '#334155';
              }}
            >
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.25rem',
                  flex: 1,
                  minWidth: 0,
                }}
              >
                <div
                  style={{
                    fontSize: '0.875rem',
                    fontFamily: 'monospace',
                    color: '#cbd5e1',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {record.address.slice(0, 8)}…{record.address.slice(-6)}
                </div>
                <div
                  style={{
                    fontSize: '0.75rem',
                    color: '#94a3b8',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  Market: {record.marketId.slice(0, 12)}…{record.label && ` · ${record.label}`}
                </div>
              </div>

              {onDelete && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(record.address, record.marketId);
                  }}
                  style={{
                    padding: '0.4rem 0.6rem',
                    background: '#ef4444',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '3px',
                    cursor: 'pointer',
                    fontSize: '0.75rem',
                    marginLeft: '0.5rem',
                  }}
                >
                  删除
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
