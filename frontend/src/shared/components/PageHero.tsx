import type { ReactNode } from 'react';

interface PageHeroProps {
  title: string;
  subtitle: string;
  controls?: ReactNode;
}

export function PageHero({ title, subtitle, controls }: PageHeroProps) {
  return (
    <div className="hero">
      <h1 className="hero-title">{title}</h1>
      <p className="hero-sub">{subtitle}</p>
      {controls ? <div className="hero-switch">{controls}</div> : null}
    </div>
  );
}
