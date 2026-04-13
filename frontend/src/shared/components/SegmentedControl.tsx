import type { ReactNode } from 'react';

interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  title?: string;
  wide?: boolean;
  activeClassName?: string;
}

interface SegmentedControlProps<T extends string> {
  options: Array<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel?: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: SegmentedControlProps<T>) {
  return (
    <div className="switch-group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.title}
          onClick={() => onChange(option.value)}
          className={[
            'switch-btn',
            option.wide ? 'switch-btn-wide' : '',
            value === option.value ? `active ${option.activeClassName ?? ''}`.trim() : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
