import { useState } from "react";
import {
  Activity,
  BarChart3,
  BookOpen,
  Gauge,
  Radar,
  Settings,
  TrendingUp,
  Waypoints,
} from "lucide-react";

import { Tabs } from "./components/Tabs";
import { Configuration } from "./pages/Configuration";
import {
  DeskOverview,
  EvidenceStreams,
  PaperJournal,
  PositionsBook,
  ResearchBoard,
} from "./pages/DeskViews";
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
    subtitle: "The desk as it actually runs: equity, jobs, news gate",
    tabs: { Desk: <DeskOverview /> },
  },
  {
    label: "Equity Paper",
    icon: TrendingUp,
    subtitle: "The $1,000 account: curve, positions, confidence calibration",
    tabs: {
      Account: <EquityPaperMonitor />,
      Positions: <PositionsBook />,
      Journal: <PaperJournal />,
    },
  },
  {
    label: "Evidence",
    icon: Radar,
    subtitle: "Forward shadow streams feeding the September 15 decision",
    tabs: { Streams: <EvidenceStreams /> },
  },
  {
    label: "Research",
    icon: BarChart3,
    subtitle: "Prop-challenge verdicts and validation results",
    tabs: { Challenge: <ResearchBoard /> },
  },
  {
    label: "IG Program",
    icon: Waypoints,
    subtitle: "Governed IG/FX program views (dormant until that journal runs)",
    tabs: {
      Overview: <Overview />,
      Opportunities: <OpportunityBoard />,
      Activity: <ActivityDashboard />,
      "Demo Campaign": <DemoCampaign />,
      Inactivity: <InactivityDiagnostics />,
      "Why No Trade": <WhyNoTrade />,
      Leaderboard: <StrategyLeaderboard />,
      Validation: <StrategyValidationMatrix />,
      Comparison: <StrategyPerformanceComparison />,
      "Regime Matrix": <StrategyRegimeMatrix />,
      Contribution: <StrategyPortfolioContribution />,
      Breakers: <StrategyCircuitBreakers />,
      Positions: <PositionsMonitor />,
      Trades: <TradesMonitor />,
      Execution: <ExecutionMonitor />,
      Lifecycle: <LifecycleMonitor />,
      Risk: <RiskMonitor />,
      Context: <MarketContext />,
      Router: <RouterMonitor />,
      Performance: <Performance />,
      Instruments: <InstrumentPerformance />,
      Regimes: <RegimePerformance />,
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
