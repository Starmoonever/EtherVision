export interface RequestMeta {
  fetchedAt: number;
  fromCache: boolean;
}

export interface DataWithMeta<T> {
  data: T;
  meta: RequestMeta;
}

export interface AggregatedRequestMeta {
  lastUpdatedAt: number | null;
  cacheStatus: 'hit' | 'miss' | 'mixed' | 'none';
}

export function mergeRequestMetas(
  metas: Array<RequestMeta | null | undefined>,
): AggregatedRequestMeta {
  const valid = metas.filter((item): item is RequestMeta => Boolean(item));

  if (valid.length === 0) {
    return {
      lastUpdatedAt: null,
      cacheStatus: 'none',
    };
  }

  const fromCacheCount = valid.filter((item) => item.fromCache).length;
  const cacheStatus =
    fromCacheCount === valid.length ? 'hit' : fromCacheCount === 0 ? 'miss' : 'mixed';

  return {
    lastUpdatedAt: Math.max(...valid.map((item) => item.fetchedAt)),
    cacheStatus,
  };
}
