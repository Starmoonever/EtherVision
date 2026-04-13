interface ChartFallbackProps {
  minHeight?: string;
}

export function ChartFallback({ minHeight = '240px' }: ChartFallbackProps) {
  return (
    <div
      className="card"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight,
      }}
    >
      <div className="spinner"></div>
    </div>
  );
}
