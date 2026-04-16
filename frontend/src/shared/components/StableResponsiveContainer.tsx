import { useEffect, useRef, useState } from 'react';
import { ResponsiveContainer } from 'recharts';

interface StableResponsiveContainerProps {
  children: React.ReactNode;
  width?: number | string;
  height: number | string;
  minHeight?: number | string;
  className?: string;
  style?: React.CSSProperties;
}

function toCssLength(value: number | string | undefined): string | undefined {
  if (value === undefined) return undefined;
  return typeof value === 'number' ? `${value}px` : value;
}

function readContainerSize(element: HTMLDivElement): { width: number; height: number } {
  const rect = element.getBoundingClientRect();
  return {
    width: rect.width,
    height: rect.height,
  };
}

export function StableResponsiveContainer({
  children,
  width = '100%',
  height,
  minHeight,
  className,
  style,
}: StableResponsiveContainerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const updateSize = () => {
      setSize(readContainerSize(element));
    };

    updateSize();

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateSize);
      return () => window.removeEventListener('resize', updateSize);
    }

    const observer = new ResizeObserver(() => updateSize());
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const hasRenderableSize = size.width > 0 && size.height > 0;

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        width: toCssLength(width),
        height: toCssLength(height),
        minHeight: toCssLength(minHeight),
        minWidth: 0,
        ...style,
      }}
    >
      {hasRenderableSize ? (
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      ) : null}
    </div>
  );
}
