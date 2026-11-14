import topicCheckIcon from "./assets/notice-timeline/topic-check.svg?no-inline";

export function NoticeFilterButton({ children, pressed, onClick, className = "notice-chip", checkIcon = topicCheckIcon }: {
  children: string;
  pressed: boolean;
  onClick: () => void;
  className?: string;
  checkIcon?: string;
}) {
  return <button className={`notice-filter-button ${className}`} type="button" aria-pressed={pressed} onClick={onClick}>
    <span className="notice-filter-check"><img src={checkIcon} alt="" /></span>
    <span>{children}</span>
  </button>;
}
