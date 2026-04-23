const SAFE_POINT_TARGET = 480;
const MINUTES_PER_DAY = 24 * 60;
const HOURS_PER_DAY = 24;

function getRangeDays(startTs: number, endTs: number): number {
  const durationMs = Math.max(0, endTs - startTs);
  return Math.max(1, Math.ceil(durationMs / (1000 * 60 * 60 * 24)));
}

function getDailyScale(startTs: number, endTs: number): number {
  return Math.max(1, Math.ceil(getRangeDays(startTs, endTs) / SAFE_POINT_TARGET));
}

export function getDailySafeIntervalMinutes(startTs: number, endTs: number): number {
  return MINUTES_PER_DAY * getDailyScale(startTs, endTs);
}

export function getDailySafeIntervalHours(startTs: number, endTs: number): number {
  return HOURS_PER_DAY * getDailyScale(startTs, endTs);
}

export function formatCompoundHistoryErrorMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : String(error ?? '');
  if (message.includes('exceeds the maximum of 500')) {
    return '时间范围过长，请缩短区间或使用更粗粒度';
  }
  return fallback;
}
