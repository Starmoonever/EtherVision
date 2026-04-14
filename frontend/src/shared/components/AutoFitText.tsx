import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

interface AutoFitTextProps {
  text: string;
  className?: string;
  style?: React.CSSProperties;
  maxFontSizePx: number;
  minFontSizePx: number;
  fontWeight?: number;
  useScientificWhenOverflow?: boolean;
  scientificIntegerDigitsThreshold?: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function toScientificText(value: string): string | null {
  const n = Number.parseFloat(value.trim());
  if (!Number.isFinite(n)) return null;
  return n.toExponential(2).replace('e+', 'e');
}

function integerDigitsCount(value: string): number | null {
  const n = Number.parseFloat(value.trim());
  if (!Number.isFinite(n)) return null;
  const abs = Math.abs(n);
  if (abs < 1) return 1;
  return Math.floor(Math.log10(abs)) + 1;
}

export function AutoFitText({
  text,
  className,
  style,
  maxFontSizePx,
  minFontSizePx,
  fontWeight,
  useScientificWhenOverflow = false,
  scientificIntegerDigitsThreshold,
}: AutoFitTextProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const [fontSizePx, setFontSizePx] = useState<number>(maxFontSizePx);
  const [displayText, setDisplayText] = useState(text);

  const baseStyle = useMemo<React.CSSProperties>(
    () => ({
      ...style,
      fontSize: `${fontSizePx}px`,
      lineHeight: 1,
      fontWeight: fontWeight ?? undefined,
      whiteSpace: 'nowrap',
      maxWidth: '100%',
    }),
    [fontSizePx, fontWeight, style],
  );

  const recompute = () => {
    const container = containerRef.current;
    const measure = measureRef.current;
    if (!container || !measure) return;

    const available = container.clientWidth;
    if (available <= 0) return;

    const computeSize = (candidateText: string): { size: number; stillOverflowAtMin: boolean } => {
      measure.textContent = candidateText;
      measure.style.fontSize = `${maxFontSizePx}px`;
      if (fontWeight !== undefined) measure.style.fontWeight = String(fontWeight);

      const measured = measure.scrollWidth;
      if (measured <= 0) return { size: maxFontSizePx, stillOverflowAtMin: false };

      const ratio = available / measured;
      const next = clamp(maxFontSizePx * ratio, minFontSizePx, maxFontSizePx);
      const widthAtMin = measured * (minFontSizePx / maxFontSizePx);
      return { size: next, stillOverflowAtMin: widthAtMin > available + 0.5 };
    };

    const digits = integerDigitsCount(text);
    const shouldUseScientificByDigits =
      typeof scientificIntegerDigitsThreshold === 'number' &&
      scientificIntegerDigitsThreshold > 0 &&
      digits !== null &&
      digits > scientificIntegerDigitsThreshold;

    const preferredText =
      shouldUseScientificByDigits && toScientificText(text)
        ? (toScientificText(text) as string)
        : text;

    const primary = computeSize(preferredText);
    let finalText = preferredText;
    let finalSize = primary.size;

    if (!shouldUseScientificByDigits && useScientificWhenOverflow && primary.stillOverflowAtMin) {
      const scientific = toScientificText(text);
      if (scientific) {
        const fallback = computeSize(scientific);
        finalText = scientific;
        finalSize = fallback.size;
      }
    }

    setDisplayText(finalText);
    setFontSizePx(finalSize);
  };

  useLayoutEffect(() => {
    recompute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    text,
    maxFontSizePx,
    minFontSizePx,
    fontWeight,
    useScientificWhenOverflow,
    scientificIntegerDigitsThreshold,
  ]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver(() => recompute());
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div ref={containerRef} className={className} style={{ maxWidth: '100%' }}>
      <span style={baseStyle}>{displayText}</span>
      <span
        ref={measureRef}
        aria-hidden="true"
        style={{
          position: 'absolute',
          visibility: 'hidden',
          whiteSpace: 'nowrap',
          lineHeight: 1,
          fontWeight: fontWeight ?? undefined,
        }}
      >
        {displayText}
      </span>
    </div>
  );
}
