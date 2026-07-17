import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BookOpen,
  Bot,
  BriefcaseBusiness,
  CircleHelp,
  Database,
  FileClock,
  Gauge,
  GitBranch,
  Landmark,
  Radar,
  Search as SearchIcon,
  Settings,
  ShieldCheck,
  Waypoints,
} from "lucide-react";

import { Configuration } from "./pages/Configuration";
import { Overview } from "./pages/Overview";
import { Performance } from "./pages/Performance";
import { RecordsPage } from "./pages/RecordsPage";
import { Replay } from "./pages/Replay";
import { Search } from "./pages/Search";
import { WhyNoTrade } from "./pages/WhyNoTrade";

const navigation = [
  ["Overview", Activity],
  ["Market", Radar],
  ["Router", GitBranch],
  ["Why No Trade", CircleHelp],
  ["Risk", ShieldCheck],
  ["Execution", Waypoints],
  ["Positions", BriefcaseBusiness],
  ["Trades", Landmark],
  ["Performance", BarChart3],
  ["AI Reviews", Bot],
  ["Alerts", AlertTriangle],
  ["Journal", Database],
  ["Replay", FileClock],
  ["Search", SearchIcon],
  ["Configuration", Settings],
] as const;

function CurrentPage({ page }: { page: string }) {
  const pages: Record<string, React.ReactNode> = {
    Overview: <Overview />,
    Market: (
      <RecordsPage
        title="Live Market Context"
        endpoint="/api/v1/context/latest"
      />
    ),
    Router: (
      <RecordsPage
        title="Strategy Router"
        endpoint="/api/v1/router/latest"
        notice="Research strategies: RESEARCH ONLY - EXECUTION PROHIBITED"
      />
    ),
    "Why No Trade": <WhyNoTrade />,
    Risk: <RecordsPage title="Risk Monitor" endpoint="/api/v1/risk/latest" />,
    Execution: (
      <RecordsPage title="Execution Monitor" endpoint="/api/v1/execution" />
    ),
    Positions: (
      <RecordsPage
        title="Open Positions: Paper and IG Demo"
        endpoint="/api/v1/positions/open"
      />
    ),
    Trades: <RecordsPage title="Closed Trades" endpoint="/api/v1/trades" />,
    Performance: <Performance />,
    "AI Reviews": (
      <RecordsPage
        title="AI Review Center"
        endpoint="/api/v1/ai-reviews"
        notice="AI authority: ADVISORY ONLY"
      />
    ),
    Alerts: <RecordsPage title="Alerts Center" endpoint="/api/v1/alerts" />,
    Journal: (
      <RecordsPage
        title="Journal Integrity"
        endpoint="/api/v1/journal/status"
      />
    ),
    Replay: <Replay />,
    Search: <Search />,
    Configuration: <Configuration />,
  };
  return pages[page];
}

export default function App() {
  const [page, setPage] = useState("Overview");
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws/events`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    return () => socket.close();
  }, []);
  return (
    <div className="app-shell">
      <aside>
        <div className="brand">
          <Gauge size={22} />
          <div>
            <strong>Trading Desk</strong>
            <span>Operations Center</span>
          </div>
        </div>
        <nav aria-label="Operations views">
          {navigation.map(([label, Icon]) => (
            <button
              className={page === label ? "active" : ""}
              key={label}
              onClick={() => setPage(label)}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <BookOpen size={15} /> Journal-first evidence
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <h1>{page}</h1>
            <p>Supervision and historical evidence</p>
          </div>
          <div className="top-status">
            <span className={connected ? "dot online" : "dot"} />
            {connected ? "Live events" : "Event stream offline"}
          </div>
        </header>
        <div className="safety-banner">
          <strong>Environment: IG DEMO</strong>
          <span>Live trading: DISABLED</span>
          <span>Dashboard authority: READ ONLY</span>
        </div>
        <div className="content">
          <CurrentPage page={page} />
        </div>
      </main>
    </div>
  );
}
