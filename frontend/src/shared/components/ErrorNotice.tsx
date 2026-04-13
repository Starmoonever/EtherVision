interface ErrorNoticeProps {
  message: string;
}

export function ErrorNotice({ message }: ErrorNoticeProps) {
  if (!message) return null;

  return (
    <div className="error-block">
      <span className="error-icon">⚠️</span>
      <p>{message}</p>
    </div>
  );
}
