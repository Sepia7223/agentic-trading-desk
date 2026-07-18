import { useState } from "react";
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
  HeartPulse,
  Landmark,
  Radar,
  Search as SearchIcon,
  Settings,
  ShieldCheck,
  Waypoints,
  ListFilter,
} from "lucide-react";

import { Configuration } from "./pages/Configuration";
import {
  OperationsEventProvider,
  useOperationsEvents,
} from "./events/OperationsEvents";
import { Overview } from "./pages/Overview";
import {
  AIReviews,
  AlertsMonitor,
  ExecutionMonitor,
  JournalMonitor,
  LifecycleMonitor,
  MarketContext,
  PositionsMonitor,
  RiskMonitor,
  RouterMonitor,
  TradesMonitor,
} from "./pages/OperationalViews";
import { Performance } from "./pages/Performance";
import { Replay } from "./pages/Replay";
import { Search } from "./pages/Search";
import { WhyNoTrade } from "./pages/WhyNoTrade";
import {
  ActivityDashboard,
  DemoCampaign,
  InactivityDiagnostics,
  InstrumentPerformance,
  OpportunityBoard,
  RegimePerformance,
  StrategyLeaderboard,
} from "./pages/OpportunityViews";

const navigation = [
  ["Overview", Activity],
  ["Opportunities", ListFilter],
  ["Activity Dashboard", Activity],
  ["Strategy Leaderboard", BarChart3],
  ["Instrument Performance", Landmark],
  ["Regime Performance", Radar],
  ["Inactivity Diagnostics", CircleHelp],
  ["Demo Campaign", Gauge],
  ["Market", Radar],
  ["Router", GitBranch],
  ["Why No Trade", CircleHelp],
  ["Risk", ShieldCheck],
  ["Execution", Waypoints],
  ["Lifecycle", HeartPulse],
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
    Opportunities: <OpportunityBoard />,
    "Activity Dashboard": <ActivityDashboard />,
    "Strategy Leaderboard": <StrategyLeaderboard />,
    "Instrument Performance": <InstrumentPerformance />,
    "Regime Performance": <RegimePerformance />,
    "Inactivity Diagnostics": <InactivityDiagnostics />,
    "Demo Campaign": <DemoCampaign />,
    Market: <MarketContext />,
    Router: <RouterMonitor />,
    "Why No Trade": <WhyNoTrade />,
    Risk: <RiskMonitor />,
    Execution: <ExecutionMonitor />,
    Lifecycle: <LifecycleMonitor />,
    Positions: <PositionsMonitor />,
    Trades: <TradesMonitor />,
    Performance: <Performance />,
    "AI Reviews": <AIReviews />,
    Alerts: <AlertsMonitor />,
    Journal: <JournalMonitor />,
    Replay: <Replay />,
    Search: <Search />,
    Configuration: <Configuration />,
  };
  return pages[page];
}

function OperationsShell() {
  const [page, setPage] = useState("Overview");
  const { connected, lastEvent } = useOperationsEvents();
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
            {connected
              ? `Live events${lastEvent ? `: ${lastEvent.event_type}` : ""}`
              : "Event stream offline"}
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

export default function App() {
  return (
    <OperationsEventProvider>
      <OperationsShell />
    </OperationsEventProvider>
  );
}
