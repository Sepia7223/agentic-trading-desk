export function Tabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: readonly string[];
  active: string;
  onSelect: (tab: string) => void;
}) {
  if (tabs.length < 2) return null;
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab}
          role="tab"
          aria-selected={tab === active}
          className={tab === active ? "active" : ""}
          onClick={() => onSelect(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
