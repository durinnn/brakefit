interface PageHeaderProps {
  eyebrow: string;
  title: string;
  caption?: string;
}

export default function PageHeader({ eyebrow, title, caption }: PageHeaderProps) {
  return (
    <header className="border-b border-ink-800 px-5 pb-5 pt-8">
      <p className="label">{eyebrow}</p>
      <h1 className="mt-2 text-2xl font-bold leading-snug text-ink-100">
        {title}
      </h1>
      {caption ? (
        <p className="mt-2 text-sm text-ink-400 tabular">{caption}</p>
      ) : null}
    </header>
  );
}
