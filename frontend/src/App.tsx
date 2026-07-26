import { useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  BriefcaseBusiness,
  Gauge,
  Radar,
  Settings,
  TrendingUp,
  Waypoints,
} from "lucide-react";

import { Tabs } from "./components/Tabs";
import { Configuration } from "./pages/Configuration";
import { EquityPaperMonitor } from "./pages/EquityPaper";
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
  StrategyCircuitBreakers,
  StrategyLeaderboard,
  StrategyPerformanceComparison,
  StrategyPortfolioContribution,
  StrategyRegimeMatrix,
  StrategyValidationMatrix,
} from "./pages/OpportunityViews";

interface Section {
  label: string;
  icon: typeof Activity;
  subtitle: string;
  tabs: Record<string, React.ReactNode>;
}

const SECTIONS: Section[] = [
  {
    label: "Overview",
    icon: Activity,
    subtitle: "System health and live status",
    tabs: { Overview: <Overview /> },
  },
  {
    label: "Equity Paper",
    icon: TrendingUp,
    subtitle: "The $1,000 account: curve, sessions, confidence calibration",
    tabs: { Account: <EquityPaperMonitor /> },
  },
  {
    label: "Opportunities",
    icon: Radar,
    subtitle: "Signal flow and campaign activity",
    tabs: {
      Board: <OpportunityBoard />,
      Activity: <ActivityDashboard />,
      "Demo Campaign": <DemoCampaign />,
      Inactivity: <InactivityDiagnostics />,
      "Why No Trade": <WhyNoTrade />,
    },
  },
  {
    label: "Strategies",
    icon: BarChart3,
    subtitle: "Validation, comparison and portfolio contribution",
    tabs: {
      Leaderboard: <StrategyLeaderboard />,
      Validation: <StrategyValidationMatrix />,
      Comparison: <StrategyPerformanceComparison />,
      "Regime Matrix": <StrategyRegimeMatrix />,
      Contribution: <StrategyPortfolioContribution />,
      Breakers: <StrategyCircuitBreakers />,
    },
  },
  {
    label: "Trading",
    icon: Waypoints,
    subtitle: "Positions, executions and order lifecycle",
    tabs: {
      Positions: <PositionsMonitor />,
      Trades: <TradesMonitor />,
      Execution: <ExecutionMonitor />,
      Lifecycle: <LifecycleMonitor />,
      Risk: <RiskMonitor />,
    },
  },
  {
    label: "Markets",
    icon: Gauge,
    subtitle: "Regime context and routing decisions",
    tabs: {
      Context: <MarketContext />,
      Router: <RouterMonitor />,
      Performance: <Performance />,
      Instruments: <InstrumentPerformance />,
      Regimes: <RegimePerformance />,
    },
  },
  {
    label: "Intelligence",
    icon: Bot,
    subtitle: "Reviews, alerts, journal evidence and replay",
    tabs: {
      "AI Reviews": <AIReviews />,
      Alerts: <AlertsMonitor />,
      Journal: <JournalMonitor />,
      Replay: <Replay />,
      Search: <Search />,
    },
  },
  {
    label: "Settings",
    icon: Settings,
    subtitle: "Operations Center configuration",
    tabs: { Configuration: <Configuration /> },
  },
];

function OperationsShell() {
  const [section, setSection] = useState(SECTIONS[0]);
  const [tabBySection, setTabBySection] = useState<Record<string, string>>({});
  const { connected, lastEvent } = useOperationsEvents();

  const tabNames = Object.keys(section.tabs);
  const activeTab = tabBySection[section.label] ?? tabNames[0];

  return (
    <div className="app-shell">
      <aside>
        <div className="brand">
          <Gauge size={22} />
          <div>
            <strong>Trading Desk</strong>
            <span>Operations</span>
          </div>
        </div>
        <nav aria-label="Operations views">
          {SECTIONS.map((entry) => (
            <button
              className={section.label === entry.label ? "active" : ""}
              key={entry.label}
              onClick={() => setSection(entry)}
            >
              <entry.icon size={16} />
              <span>{entry.label}</span>
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
            <h1>{section.label}</h1>
            <p>{section.subtitle}</p>
          </div>
          <div className="top-status">
            <span className={connected ? "dot online" : "dot"} />
            {connected
              ? `Live${lastEvent ? `: ${lastEvent.event_type}` : ""}`
              : "Polling every 10s"}
          </div>
        </header>
        <div className="safety-banner">
          <strong>Demo environment</strong>
          <span>Live trading disabled</span>
          <span>Read only</span>
        </div>
        <Tabs
          tabs={tabNames}
          active={activeTab}
          onSelect={(tab) =>
            setTabBySection((previous) => ({
              ...previous,
              [section.label]: tab,
            }))
          }
        />
        <div className="content" key={`${section.label}:${activeTab}`}>
          {section.tabs[activeTab]}
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
