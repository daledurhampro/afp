import { useEffect, useMemo, useState } from 'react';
import {
  PieChart, Pie, Cell, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';

// A scripted, self-contained walkthrough of an AFP analysis run.
// Nothing here calls the API, Lambda or Bedrock: all data is sample data,
// so the demo works signed out and even when the AWS infrastructure is destroyed.

interface DemoModalProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------- Sample data ----------

const HOLDINGS = [
  { account: '401(k)', symbol: 'SPY', name: 'SPDR S&P 500 ETF', shares: 120, price: 590 },
  { account: '401(k)', symbol: 'QQQ', name: 'Invesco QQQ Trust', shares: 45, price: 510 },
  { account: '401(k)', symbol: 'BND', name: 'Vanguard Total Bond Market', shares: 200, price: 73 },
  { account: '401(k)', symbol: 'VEA', name: 'Vanguard FTSE Developed Markets', shares: 150, price: 52 },
  { account: 'Roth IRA', symbol: 'VTI', name: 'Vanguard Total Stock Market', shares: 80, price: 290 },
  { account: 'Roth IRA', symbol: 'VNQ', name: 'Vanguard Real Estate ETF', shares: 60, price: 90 },
  { account: 'Roth IRA', symbol: 'GLD', name: 'SPDR Gold Shares', shares: 25, price: 245 },
];

const TOTAL = HOLDINGS.reduce((sum, h) => sum + h.shares * h.price, 0);

const ASSET_CLASS = [
  { name: 'Equity', value: 124750, color: '#209DD7' },
  { name: 'Fixed Income', value: 14600, color: '#753991' },
  { name: 'Commodities', value: 6125, color: '#FFB707' },
  { name: 'Real Estate', value: 5400, color: '#062147' },
];

const REGIONS = [
  { name: 'North America', value: 136950 },
  { name: 'Intl Developed', value: 7800 },
  { name: 'Global', value: 6125 },
];

const CURRENT_AGE = 40;
const RETIREMENT_AGE = 65;

function buildProjection() {
  const points: { age: number; value: number }[] = [];
  let balance = TOTAL;
  for (let age = CURRENT_AGE; age <= 90; age++) {
    points.push({ age, value: Math.max(0, Math.round(balance)) });
    if (age < RETIREMENT_AGE) {
      balance = balance * 1.07 + 20000; // growth + annual contribution
    } else {
      balance = balance * 1.045 - 85000; // more conservative growth, annual withdrawal
    }
  }
  return points;
}

// ---------- Agents & script ----------

type AgentId = 'planner' | 'tagger' | 'reporter' | 'charter' | 'retirement';

const AGENTS: { id: AgentId; icon: string; name: string; role: string }[] = [
  { id: 'planner', icon: '🎯', name: 'Financial Planner', role: 'Orchestrator' },
  { id: 'tagger', icon: '🏷️', name: 'Instrument Tagger', role: 'Classification' },
  { id: 'reporter', icon: '📊', name: 'Portfolio Analyst', role: 'Report writer' },
  { id: 'charter', icon: '📈', name: 'Chart Specialist', role: 'Visualization' },
  { id: 'retirement', icon: '🏖️', name: 'Retirement Planner', role: 'Projections' },
];

// Stages: 0 portfolio, 1 planner, 2 tagger, 3 parallel agents, 4 results
const STAGE_DURATIONS = [10000, 10000, 10000, 15000];
const STAGE_LABELS = ['Portfolio', 'Planning', 'Tagging', 'Analysis', 'Results'];
const TICK_MS = 100;

// Plain-language captions so first-time viewers know what each stage shows.
const CAPTIONS: { title: string; body: string }[] = [
  {
    title: 'Step 1 of 4: Start with a portfolio',
    body: 'This sample investor holds seven funds across a 401(k) and a Roth IRA. When they ask for an analysis, AFP puts the request on a queue. A team of AI agents picks it up and works on it in the background, so the user doesn\'t have to wait on the page.',
  },
  {
    title: 'Step 2 of 4: The Planner takes charge',
    body: 'The Financial Planner is the orchestrator agent. It reads the portfolio, works out what needs doing, and hands each task to a specialist agent. Like a team lead, it delegates the work instead of doing all of it.',
  },
  {
    title: 'Step 3 of 4: Tagging the investments',
    body: 'Before anything can be analyzed, AFP needs to know what each fund actually holds. The Instrument Tagger classifies each fund by asset class (stocks, bonds, and so on), region and sector, then saves that breakdown for the other agents to use.',
  },
  {
    title: 'Step 4 of 4: Specialists work in parallel',
    body: 'Three specialist agents now run at the same time. The Analyst writes a report using a knowledge base of market research, the Chart Specialist builds visualizations, and the Retirement Planner simulates hundreds of possible market futures to estimate whether the savings will last.',
  },
  {
    title: 'Done: the results are ready',
    body: 'Each agent\'s output is combined into one analysis. Use the tabs below to see the written report, the charts, and the retirement projection. A real analysis takes a minute or two; this demo shortens it to under a minute.',
  },
];

// `at` = ms into the stage when the line appears, so lines arrive one at a time.
const LOG: { stage: number; at: number; agent: AgentId; text: string }[] = [
  { stage: 1, at: 1500, agent: 'planner', text: 'Job received from SQS queue — loading portfolio for user' },
  { stage: 1, at: 5500, agent: 'planner', text: 'Found 7 instruments; 0 missing allocation data → delegating to Tagger' },
  { stage: 2, at: 1500, agent: 'tagger', text: 'Classifying SPY, QQQ, BND, VEA, VTI, VNQ, GLD' },
  { stage: 2, at: 6000, agent: 'tagger', text: 'Saved asset class, region and sector breakdowns to database' },
  { stage: 3, at: 1000, agent: 'planner', text: 'Invoking Reporter, Charter and Retirement in parallel' },
  { stage: 3, at: 3500, agent: 'reporter', text: 'Pulling market insights from S3 Vectors knowledge base' },
  { stage: 3, at: 6000, agent: 'charter', text: 'Building allocation and geography charts' },
  { stage: 3, at: 8500, agent: 'retirement', text: 'Running 500 Monte Carlo simulations to age 90' },
  { stage: 3, at: 12000, agent: 'reporter', text: 'Portfolio report written' },
  { stage: 4, at: 0, agent: 'planner', text: 'All agents complete — results saved, job marked completed ✅' },
];

function agentStatus(id: AgentId, stage: number): 'idle' | 'running' | 'done' {
  if (id === 'planner') return stage >= 4 ? 'done' : stage >= 1 ? 'running' : 'idle';
  if (id === 'tagger') return stage > 2 ? 'done' : stage === 2 ? 'running' : 'idle';
  return stage > 3 ? 'done' : stage === 3 ? 'running' : 'idle';
}

const usd = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const pct = (n: number) => `${((n / TOTAL) * 100).toFixed(1)}%`;

type ResultTab = 'overview' | 'charts' | 'retirement';

// ---------- Component ----------

export default function DemoModal({ isOpen, onClose }: DemoModalProps) {
  const [stage, setStageRaw] = useState(0);
  const [elapsed, setElapsed] = useState(0); // ms spent in the current stage
  const [paused, setPaused] = useState(false);
  const [tab, setTab] = useState<ResultTab>('overview');
  const projection = useMemo(buildProjection, []);

  const goToStage = (s: number) => {
    setStageRaw(s);
    setElapsed(0);
  };

  // Reset whenever the modal is opened
  useEffect(() => {
    if (isOpen) {
      goToStage(0);
      setPaused(false);
      setTab('overview');
    }
  }, [isOpen]);

  // Tick the clock; pausing just stops the ticks so progress is kept
  useEffect(() => {
    if (!isOpen || paused || stage >= STAGE_DURATIONS.length) return;
    const timer = setInterval(() => setElapsed(e => e + TICK_MS), TICK_MS);
    return () => clearInterval(timer);
  }, [isOpen, paused, stage]);

  // Advance to the next stage once the current one has run its course
  useEffect(() => {
    if (stage < STAGE_DURATIONS.length && elapsed >= STAGE_DURATIONS[stage]) {
      goToStage(stage + 1);
    }
  }, [elapsed, stage]);

  // Escape to close + lock background scroll
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const finished = stage >= 4;
  const visibleLog = LOG.filter(l => l.stage < stage || (l.stage === stage && l.at <= elapsed));
  const stageProgress = finished ? 1 : Math.min(1, elapsed / STAGE_DURATIONS[stage]);
  const caption = CAPTIONS[stage];
  const retirementValue = projection.find(p => p.age === RETIREMENT_AGE)?.value ?? 0;

  return (
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="demo-title"
        className="bg-white rounded-xl max-w-5xl w-full max-h-[92vh] overflow-y-auto shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between z-10">
          <div>
            <h2 id="demo-title" className="text-xl font-bold text-dark">
              AFP Demo <span className="text-ai-accent">— watch the agents work</span>
            </h2>
            <p className="text-xs text-gray-500">Sample portfolio and illustrative prices. No real account data is used.</p>
          </div>
          <div className="flex items-center gap-2">
            {finished ? (
              <button
                onClick={() => { goToStage(0); setPaused(false); setTab('overview'); }}
                className="px-4 py-2 text-sm border border-primary text-primary rounded-lg hover:bg-primary hover:text-white transition-colors"
              >
                ↻ Replay
              </button>
            ) : (
              <>
                <button
                  onClick={() => setPaused(p => !p)}
                  className="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                >
                  {paused ? '▶ Resume' : '❚❚ Pause'}
                </button>
                <button
                  onClick={() => goToStage(stage + 1)}
                  className="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                >
                  Next step →
                </button>
                <button
                  onClick={() => goToStage(4)}
                  className="hidden sm:inline-block px-4 py-2 text-sm text-gray-500 rounded-lg hover:bg-gray-100 transition-colors"
                >
                  Skip to results
                </button>
              </>
            )}
            <button
              onClick={onClose}
              aria-label="Close demo"
              className="w-9 h-9 rounded-lg text-gray-500 hover:bg-gray-100 text-xl leading-none"
            >
              ×
            </button>
          </div>
        </div>

        {/* Stage progress */}
        <div className="px-6 pt-4">
          <div className="flex gap-2">
            {STAGE_LABELS.map((label, i) => (
              <div key={label} className="flex-1">
                <div className="h-1.5 rounded-full bg-gray-200 overflow-hidden">
                  <div
                    className="h-full bg-ai-accent transition-[width] duration-100 ease-linear"
                    style={{ width: i < stage ? '100%' : i === stage ? `${stageProgress * 100}%` : '0%' }}
                  />
                </div>
                <div className={`mt-1 text-xs ${i === stage ? 'text-ai-accent font-semibold' : 'text-gray-400'}`}>{label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Explainer caption */}
        <div className="px-6 pt-4">
          <div key={stage} className="rounded-lg border-l-4 border-ai-accent bg-purple-50 px-4 py-3 animate-fade-in">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-ai-accent">What&apos;s happening</div>
              {paused && !finished && <div className="text-xs font-medium text-gray-500">Paused</div>}
            </div>
            <div className="mt-1 font-semibold text-dark">{caption.title}</div>
            <p className="mt-1 text-sm text-gray-700 leading-relaxed">{caption.body}</p>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Stage 0: portfolio */}
          {stage === 0 && (
            <section>
              <h3 className="text-lg font-semibold text-dark mb-1">1. Your portfolio</h3>
              <p className="text-sm text-gray-600 mb-4">
                A user has two accounts. They click <span className="font-semibold text-ai-accent">Start New Analysis</span> and
                the job is sent to an SQS queue.
              </p>
              <HoldingsTable />
            </section>
          )}

          {/* Stages 1-3: agents at work */}
          {stage >= 1 && !finished && (
            <section>
              <h3 className="text-lg font-semibold text-dark mb-4">2. The AI planning team gets to work</h3>
              <AgentGrid stage={stage} />
              <ActivityLog entries={visibleLog} />
            </section>
          )}

          {/* Stage 4: results */}
          {finished && (
            <section>
              <AgentGrid stage={stage} compact />
              <h3 className="text-lg font-semibold text-dark mt-6 mb-3">3. Your analysis is ready</h3>

              <div className="flex gap-1 border-b mb-4">
                {([
                  ['overview', '📄 Report'],
                  ['charts', '📈 Charts'],
                  ['retirement', '🏖️ Retirement'],
                ] as [ResultTab, string][]).map(([id, label]) => (
                  <button
                    key={id}
                    onClick={() => setTab(id)}
                    className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                      tab === id ? 'border-primary text-primary' : 'border-transparent text-gray-500 hover:text-dark'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {tab === 'overview' && <Report />}

              {tab === 'charts' && (
                <div className="grid md:grid-cols-2 gap-6">
                  <div className="border rounded-lg p-4">
                    <h4 className="font-semibold text-dark mb-2">Asset class allocation</h4>
                    <ResponsiveContainer width="100%" height={240}>
                      <PieChart>
                        <Pie data={ASSET_CLASS} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}>
                          {ASSET_CLASS.map(entry => <Cell key={entry.name} fill={entry.color} />)}
                        </Pie>
                        <Tooltip formatter={(v) => usd(Number(v))} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                      {ASSET_CLASS.map(entry => (
                        <div key={entry.name} className="flex items-center gap-2 text-sm">
                          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: entry.color }} />
                          <span className="text-gray-700">{entry.name}</span>
                          <span className="text-gray-500 ml-auto">{pct(entry.value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="border rounded-lg p-4">
                    <h4 className="font-semibold text-dark mb-2">Geographic exposure</h4>
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={REGIONS} margin={{ left: 10 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                        <YAxis tickFormatter={v => `$${Math.round(Number(v) / 1000)}k`} tick={{ fontSize: 12 }} />
                        <Tooltip formatter={(v) => usd(Number(v))} />
                        <Bar dataKey="value" fill="#209DD7" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {tab === 'retirement' && (
                <div className="space-y-4">
                  <div className="grid sm:grid-cols-3 gap-4">
                    <Stat label="Projected at 65" value={usd(retirementValue)} />
                    <Stat label="Success probability" value="84%" accent />
                    <Stat label="Annual income target" value={usd(85000)} />
                  </div>
                  <div className="border rounded-lg p-4">
                    <h4 className="font-semibold text-dark mb-2">Projected portfolio value (median path)</h4>
                    <ResponsiveContainer width="100%" height={280}>
                      <LineChart data={projection} margin={{ left: 10, right: 10 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="age" tick={{ fontSize: 12 }} />
                        <YAxis tickFormatter={v => `$${(Number(v) / 1_000_000).toFixed(1)}M`} tick={{ fontSize: 12 }} />
                        <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={l => `Age ${l}`} />
                        <ReferenceLine x={RETIREMENT_AGE} stroke="#FFB707" strokeDasharray="4 4" label={{ value: 'Retire', fontSize: 12, fill: '#062147' }} />
                        <Line type="monotone" dataKey="value" stroke="#753991" strokeWidth={2.5} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </section>
          )}
        </div>

        <div className="border-t px-6 py-3 text-xs text-gray-500">
          This demo uses sample data. Real analyses run on AWS Lambda agents powered by Amazon Bedrock and are for informational purposes only.
        </div>
      </div>
    </div>
  );
}

// ---------- Sub-components ----------

function HoldingsTable() {
  return (
    <div className="overflow-x-auto border rounded-lg">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            <th className="text-left px-4 py-2 font-medium">Account</th>
            <th className="text-left px-4 py-2 font-medium">Symbol</th>
            <th className="text-left px-4 py-2 font-medium">Name</th>
            <th className="text-right px-4 py-2 font-medium">Shares</th>
            <th className="text-right px-4 py-2 font-medium">Value</th>
          </tr>
        </thead>
        <tbody>
          {HOLDINGS.map(h => (
            <tr key={h.symbol} className="border-t">
              <td className="px-4 py-2 text-gray-600">{h.account}</td>
              <td className="px-4 py-2 font-semibold text-dark">{h.symbol}</td>
              <td className="px-4 py-2 text-gray-600 whitespace-nowrap">{h.name}</td>
              <td className="px-4 py-2 text-right">{h.shares}</td>
              <td className="px-4 py-2 text-right">{usd(h.shares * h.price)}</td>
            </tr>
          ))}
          <tr className="border-t bg-gray-50 font-semibold">
            <td className="px-4 py-2" colSpan={4}>Total</td>
            <td className="px-4 py-2 text-right">{usd(TOTAL)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function AgentGrid({ stage, compact = false }: { stage: number; compact?: boolean }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {AGENTS.map(agent => {
        const status = agentStatus(agent.id, stage);
        const styles = {
          idle: 'border-gray-200 bg-gray-50 opacity-60',
          running: 'border-ai-accent bg-purple-50 animate-glow-pulse',
          done: 'border-success bg-green-50',
        }[status];
        return (
          <div key={agent.id} className={`rounded-lg border-2 text-center transition-all duration-500 ${styles} ${compact ? 'p-2' : 'p-4'}`}>
            <div className={compact ? 'text-xl' : 'text-3xl mb-1'}>{agent.icon}</div>
            <div className="text-sm font-semibold text-dark">{agent.name}</div>
            {!compact && <div className="text-xs text-gray-500">{agent.role}</div>}
            <div className={`text-xs mt-1 font-medium ${
              status === 'running' ? 'text-ai-accent' : status === 'done' ? 'text-success' : 'text-gray-400'
            }`}>
              {status === 'running' ? 'Working…' : status === 'done' ? '✓ Done' : 'Waiting'}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ActivityLog({ entries }: { entries: typeof LOG }) {
  return (
    <div className="mt-5 bg-dark rounded-lg p-4 font-mono text-xs text-gray-200 space-y-1.5 min-h-[180px]">
      {entries.map((entry, i) => {
        const agent = AGENTS.find(a => a.id === entry.agent)!;
        return (
          <div key={i} className="flex gap-2">
            <span className="text-accent shrink-0">[{agent.name}]</span>
            <span>{entry.text}</span>
          </div>
        );
      })}
      <div className="text-gray-500 animate-pulse">▍</div>
    </div>
  );
}

function Stat({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="border rounded-lg p-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-2xl font-bold ${accent ? 'text-success' : 'text-dark'}`}>{value}</div>
    </div>
  );
}

function Report() {
  return (
    <div className="border rounded-lg p-5 text-sm text-gray-700 space-y-4 leading-relaxed">
      <div>
        <h4 className="text-base font-bold text-dark mb-1">Executive summary</h4>
        <p>
          Your {usd(TOTAL)} portfolio across two accounts is growth-oriented, with {pct(124750)} in equities.
          Costs are low (weighted expense ratio ≈ 0.09%) and diversification across US large caps is strong.
        </p>
      </div>
      <div>
        <h4 className="text-base font-bold text-dark mb-1">Key observations</h4>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>US concentration:</strong> about 91% of holdings are North American; international developed markets are only {pct(7800)}.</li>
          <li><strong>Overlap:</strong> SPY, VTI and QQQ share many top holdings, so your technology exposure is higher than it first appears.</li>
          <li><strong>Defensive assets:</strong> bonds ({pct(14600)}) and gold ({pct(6125)}) provide a modest buffer against equity drawdowns.</li>
        </ul>
      </div>
      <div>
        <h4 className="text-base font-bold text-dark mb-1">Recommendations</h4>
        <ol className="list-decimal pl-5 space-y-1">
          <li>Consider raising international exposure toward 20–30% for broader diversification.</li>
          <li>Direct new 401(k) contributions to BND to move gradually toward a target bond allocation as retirement nears.</li>
          <li>Review the SPY / VTI overlap; consolidating could simplify the portfolio without changing risk.</li>
        </ol>
      </div>
    </div>
  );
}
