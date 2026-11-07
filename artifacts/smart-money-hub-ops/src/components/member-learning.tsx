import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetMemberLearningQueryKey,
  useGetMemberLearning,
  useUpdateMemberLearningProgress,
} from '@workspace/api-client-react';
import type { MemberLearningLesson, MemberLearningResponse } from '@workspace/api-client-react';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Eye,
  EyeOff,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import './member-learning.css';
import { MemberLessonDiagram } from './member-learning-diagrams';

const diagramLessonIds = new Set([
  'orientation',
  'candle-anatomy',
  'swing-high-low',
  'market-structure',
  'multi-timeframe-context',
  'bos-and-choch',
  'change-of-character',
  'mss-displacement',
  'liquidity-and-equal-highs-lows',
  'liquidity-sweep',
  'inducement',
  'order-blocks-in-context',
  'fair-value-gaps',
  'inverse-fvg',
  'volume-imbalance-liquidity-void',
  'breaker-block',
  'mitigation-block',
  'rejection-block',
  'premium-discount-ote',
  'power-of-three-judas-swing',
  'complete-smc-trade-model',
  'confirmation-and-risk-planning',
]);
type LessonFilter = 'all' | MemberLearningLesson['progress'];

const lessonFilters: Array<{ value: LessonFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'not_started', label: 'To do' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'completed', label: 'Complete' },
];

const roadmapSteps = [
  { number: '01', title: 'Learn', description: 'Understand the concept and its limits.' },
  { number: '02', title: 'Practise', description: 'Use chart exercises and practical assignments.' },
  { number: '03', title: 'Analyse', description: 'Apply concepts to Gold and other relevant markets.' },
  { number: '04', title: 'Review', description: 'Check your understanding before moving forward.' },
];

type LessonActivity = { practise: string[]; analyse: string; review: string[] };

const lessonActivities: Record<string, LessonActivity> = {
  orientation: {
    practise: ['Write the Learn → Practise → Analyse → Review steps in your journal.', 'Record your H1 bias, M5 entry timeframe, risk limits, and conditions for standing aside.'],
    analyse: 'Choose a saved or demo chart for Gold and one other relevant market. Describe only what the charts show; this is not a live signal.',
    review: ['Which rules are part of your established plan?', 'When is standing aside the correct decision?'],
  },
  'candle-anatomy': {
    practise: ['Mark open, high, low, and close on five candles.', 'Compare each candle body with its wicks.'],
    analyse: 'Compare up-closing and down-closing candles on a saved Gold chart and another relevant market. Check the chart colour legend.',
    review: ['What do the body and wicks represent?', 'Can candle colour alone establish direction?'],
  },
  'swing-high-low': {
    practise: ['Mark 10 swing highs and lows on an M5 Gold chart using the three-candle example.', 'Repeat on H1 and note which swings price visibly respects.'],
    analyse: 'Compare how H1 swing areas appear in M5 detail on XAUUSD and one other market.',
    review: ['What is the minimum candle pattern shown in the guide?', 'Why can an H1 swing matter more than an M5 fluctuation?'],
  },
  'market-structure': {
    practise: ['Label HH, HL, LH, and LL across one H1 Gold chart. Mark the swing that would challenge the current sequence.'],
    analyse: 'State the H1 bias on a saved XAUUSD chart, then check whether M5 agrees. Repeat on another relevant market.',
    review: ['What makes a chart sequence a range rather than a trend?', 'Which swing is protected in the guide’s uptrend example?'],
  },
  'multi-timeframe-context': {
    practise: ['Write the H1 bias before viewing M5.', 'On M5, record what entry confirmation you would need and what would invalidate the idea.'],
    analyse: 'Apply the H1-to-M5 process to Gold and another market you follow. If the views conflict, record the conflict instead of forcing a setup.',
    review: ['Which timeframe sets your higher-timeframe bias?', 'Does M5 detail override an unclear H1 context?'],
  },
  'bos-and-choch': {
    practise: ['Find five BOS examples on H1 Gold. Mark the prior swing and closing candle; separately note wick-only breaks.'],
    analyse: 'On a saved XAUUSD chart, map the pullback area after a BOS and note what M5 confirmation your plan would still require.',
    review: ['Why does a wick through a level not meet the guide’s BOS close rule?', 'What do you study after a BOS without chasing it?'],
  },
  'change-of-character': {
    practise: ['Find three CHoCH examples on H1 Gold. Note whether a sweep came first and whether the observed shift held.'],
    analyse: 'Compare an M5 CHoCH against H1 context on a saved chart. Record whether it describes a shift or only a pullback.',
    review: ['Which swing level breaks in the guide’s bullish CHoCH example?', 'Why is a CHoCH not an entry by itself?'],
  },
  'mss-displacement': {
    practise: ['Mark displacement candles and gaps on five M5 structure breaks. Grade each example strong or weak and explain why.'],
    analyse: 'Compare saved XAUUSD examples around London and New York sessions with another market; do not assume the pattern repeats.',
    review: ['How does the guide distinguish MSS from CHoCH?', 'What can make a structure break look weak?'],
  },
  'liquidity-and-equal-highs-lows': {
    practise: ['Mark equal highs, equal lows, previous-day highs/lows, and a session range on a saved Gold chart.'],
    analyse: 'List visible levels above and below the selected XAUUSD price. Compare which is nearer and more obvious, then repeat on another market.',
    review: ['Why is a liquidity level a chart interpretation rather than proof of hidden orders?', 'Name four visible reference types from the lesson.'],
  },
  'liquidity-sweep': {
    practise: ['Find five sweep examples on M5 Gold. Mark the wick beyond the reference and the close back inside.'],
    analyse: 'Review saved Asia high/low examples around the London session and note whether a later structure description followed.',
    review: ['How does a sweep differ from a close-based BOS?', 'Is a sweep alone sufficient under your plan?'],
  },
  inducement: {
    practise: ['Mark a smaller swing before three candidate order-block areas on M5 Gold. Note whether price passed the swing first.'],
    analyse: 'On a saved H1 chart, identify smaller visible swings leading toward a zone without assuming intent or hidden orders.',
    review: ['Why does the guide describe inducement as a filter, not a universal rule?', 'What did price visibly do after passing the smaller swing?'],
  },
  'fair-value-gaps': {
    practise: ['Draw 10 three-candle FVG examples on M5 Gold. Mark the 50% level and record whether each area was revisited.'],
    analyse: 'Compare saved FVG examples that align with H1 context with those that do not on XAUUSD.',
    review: ['What price relationship defines bullish and bearish FVG examples?', 'What does consequent encroachment refer to?'],
  },
  'inverse-fvg': {
    practise: ['Find three FVG examples with a candle close through the zone. Record what happened on a later revisit.'],
    analyse: 'Look for saved M5 IFVG examples after a sweep and structure shift; compare them with wick-only passes.',
    review: ['Why is a wick-only pass not enough for the guide’s inversion example?', 'What opposite-side role is assigned to a failed bullish FVG?'],
  },
  'volume-imbalance-liquidity-void': {
    practise: ['Mark one body imbalance with overlapping wicks and one run of directional candles on Gold.'],
    analyse: 'Use a saved chart around a sharp move and observe whether price later revisited any marked area.',
    review: ['How does a body imbalance differ from the FVG definition?', 'What candle sequence is called a liquidity void in the guide?'],
  },
  'order-blocks-in-context': {
    practise: ['Mark five candidate order-block areas that precede a visible structure break on M5 Gold.', 'Record the zone bounds and whether price later revisited them.'],
    analyse: 'Find saved H1 candidate zones that align with the observed structure; inspect M5 detail without assuming a reaction.',
    review: ['What visible move does the guide require before applying the label?', 'Does the label prove who placed orders?'],
  },
  'breaker-block': {
    practise: ['Find three candidate breaker examples on M5 Gold. Mark the prior zone, the close through, and any earlier sweep.'],
    analyse: 'Mark one H1 candidate and inspect a saved M5 revisit without predicting the outcome.',
    review: ['How does the guide distinguish a breaker from a mitigation block?', 'What happens to the old zone in a bullish breaker example?'],
  },
  'mitigation-block': {
    practise: ['Find three failure-swing examples on M5 Gold. Mark the failed swing area and any later revisit.'],
    analyse: 'Journal candidate breaker and mitigation examples separately on saved XAUUSD charts.',
    review: ['Why does the guide treat this as a supporting zone?', 'What happened to the prior high or low before the example formed?'],
  },
  'rejection-block': {
    practise: ['Mark five prominent wick examples at H1 swing areas. Record how price behaved if it later returned.'],
    analyse: 'Compare candidate wick zones with previous-day or session reference levels on a saved Gold chart.',
    review: ['How is the example zone drawn?', 'Why should ordinary small wicks not all receive the same label?'],
  },
  'premium-discount-ote': {
    practise: ['Draw a selected H1 Gold dealing range. Mark 50% and the guide’s 62%–79% OTE band, then note M5 observations.'],
    analyse: 'On a saved XAUUSD chart, describe the range location and what context it provides; do not infer a trade direction from the band alone.',
    review: ['Which retracement range does the guide show for OTE?', 'What does the midpoint represent?'],
  },
  'power-of-three-judas-swing': {
    practise: ['Mark the Asia range on Gold across five saved or demo sessions. Note whether either side was passed later.'],
    analyse: 'Compare the AMD description on XAUUSD with another market over the same selected dates.',
    review: ['What do accumulation, manipulation, and distribution mean in this framework?', 'What should you do when the sequence does not appear?'],
  },
  'complete-smc-trade-model': {
    practise: ['Paper-trade five historical or demo chart examples. Log H1 context, sweep, M5 shift, zone, stop, target, and whether 1:3 was available.'],
    analyse: 'Apply the same checklist to one other relevant market and compare observations without assuming equal results.',
    review: ['Which elements does the guide combine in its schematic?', 'What is the planned decision if there is no sweep or 1:3 is unavailable?'],
  },
  'sessions-and-kill-zones': {
    practise: ['On a saved chart, label the timezone and daylight-saving setting before marking any session window.'],
    analyse: 'Compare one selected Gold session with another relevant market using the broker chart timezone.',
    review: ['Which timezone does the guide use for its example windows?', 'What must you verify before comparing a chart with those times?'],
  },
  'confirmation-and-risk-planning': {
    practise: ['Use a hypothetical or demo example to review all 10 checklist steps and calculate whether the plan meets 2% risk and 1:3 minimum R:R.', 'Explain the planned response at 1:1 and at the 3% daily loss limit.'],
    analyse: 'Apply the checklist to saved Gold and another relevant market chart. Record missing evidence or invalidation; do not imply live data.',
    review: ['What is the planned decision if 1:3 is unavailable?', 'When must you stop for the day?'],
  },
};

function lessonStatus(progress: MemberLearningLesson['progress']) {
  if (progress === 'completed') return 'Completed';
  if (progress === 'in_progress') return 'In progress';
  return 'Not started';
}

function formatDate(value: string | null) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function renderInlineMarkdown(value: string): ReactNode[] {
  const tokens = value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return tokens.map((token, index) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={index}>{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={index}>{token.slice(1, -1)}</code>;
    }
    return token;
  });
}

function renderLessonMarkdown(markdown: string): ReactNode[] {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { kind: 'ordered' | 'unordered'; items: string[] } | null = null;
  let key = 0;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(<p key={`paragraph-${key++}`}>{renderInlineMarkdown(paragraph.join(' '))}</p>);
    paragraph = [];
  };

  const flushList = () => {
    if (!list) return;
    const List = list.kind === 'ordered' ? 'ol' : 'ul';
    blocks.push(
      <List key={`list-${key++}`}>
        {list.items.map((item, index) => <li key={index}>{renderInlineMarkdown(item)}</li>)}
      </List>,
    );
    list = null;
  };

  markdown.split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      return;
    }

    const heading = trimmed.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push(<h3 key={`heading-${key++}`}>{renderInlineMarkdown(heading[1])}</h3>);
      return;
    }

    const orderedItem = trimmed.match(/^\d+\.\s+(.+)$/);
    const unorderedItem = trimmed.match(/^[-*]\s+(.+)$/);
    const item = orderedItem?.[1] ?? unorderedItem?.[1];
    if (item) {
      flushParagraph();
      const kind = orderedItem ? 'ordered' : 'unordered';
      if (list && list.kind !== kind) flushList();
      if (!list) list = { kind, items: [] };
      list.items.push(item);
      return;
    }

    flushList();
    paragraph.push(trimmed);
  });

  flushParagraph();
  flushList();
  return blocks;
}

export function MemberLearningExperience() {
  const queryClient = useQueryClient();
  const learning = useGetMemberLearning({
    query: {
      queryKey: getGetMemberLearningQueryKey(),
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
  });
  const updateProgress = useUpdateMemberLearningProgress();
  const lessons = useMemo(() => learning.data?.lessons ?? [], [learning.data?.lessons]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lessonQuery, setLessonQuery] = useState('');
  const [lessonFilter, setLessonFilter] = useState<LessonFilter>('all');
  const [savedMessage, setSavedMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const [diagramOpen, setDiagramOpen] = useState(false);
  const visibleLessons = useMemo(() => {
    const normalizedQuery = lessonQuery.trim().toLocaleLowerCase();
    return lessons.filter((lesson) => {
      const matchesFilter = lessonFilter === 'all' || lesson.progress === lessonFilter;
      const matchesSearch = !normalizedQuery ||
        `${lesson.title} ${lesson.summary}`.toLocaleLowerCase().includes(normalizedQuery);
      return matchesFilter && matchesSearch;
    });
  }, [lessons, lessonFilter, lessonQuery]);

  useEffect(() => {
    if (!visibleLessons.length) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (selectedId && visibleLessons.some((lesson) => lesson.lessonId === selectedId)) return;
    const next = learning.data?.nextLessonId;
    const nextLesson = next ? visibleLessons.find((lesson) => lesson.lessonId === next && !lesson.locked) : undefined;
    setSelectedId(nextLesson?.lessonId ?? visibleLessons.find((lesson) => !lesson.locked)?.lessonId ?? visibleLessons[0].lessonId);
  }, [visibleLessons, learning.data?.nextLessonId, selectedId]);

  useEffect(() => {
    setDiagramOpen(false);
  }, [selectedId]);

  const response = learning.data as MemberLearningResponse | undefined;
  const selected = visibleLessons.find((lesson) => lesson.lessonId === selectedId) ?? null;
  const activeIndex = selected ? visibleLessons.findIndex((lesson) => lesson.lessonId === selected.lessonId) : -1;
  const saving = updateProgress.isPending;

  async function saveProgress(lesson: MemberLearningLesson, progress: 'in_progress' | 'completed') {
    if (lesson.locked) return;
    setActionError('');
    setSavedMessage('');
    try {
      await updateProgress.mutateAsync({ lessonId: lesson.lessonId, data: { progress } });
      await queryClient.invalidateQueries({ queryKey: getGetMemberLearningQueryKey() });
      setSavedMessage(progress === 'completed' ? 'Lesson complete. Your progress is saved.' : 'Progress saved. Pick up here whenever you return.');
    } catch {
      setActionError('Your progress could not be saved. Check your connection and try again.');
    }
  }

  function moveLesson(offset: number) {
    const target = visibleLessons[activeIndex + offset];
    if (target) {
      setSelectedId(target.lessonId);
      setSavedMessage('');
      setActionError('');
    }
  }

  return (
    <main className="ml-page" data-testid="member-learning">
      <div className="ml-shell">
        <header className="ml-header">
          <Link className="ml-brand" href="/member/dashboard" aria-label="Return to Smart Money Hub dashboard">
            <span className="ml-brand-mark" aria-hidden="true"><span /><span /><span /></span>
            <span className="ml-brand-copy"><strong>VAYDA</strong><small>SMART MONEY HUB</small></span>
          </Link>
          <div className="ml-private"><ShieldCheck size={15} aria-hidden="true" /> PRIVATE MEMBER SPACE</div>
          <Link className="ml-back-link" href="/member/dashboard" data-testid="link-learning-dashboard">
            <ArrowLeft size={15} /> Workspace
          </Link>
        </header>

        <section className="ml-intro" aria-labelledby="ml-title">
          <div className="ml-intro-copy">
            <div className="ml-eyebrow"><span className="ml-live-dot" /> TRADING ACADEMY · MEMBER STUDY SPACE</div>
            <h1 id="ml-title">Learn the market.<br /><em>Think for yourself.</em></h1>
            <p>Read any published lesson, practise the concept, and record progress in sequence. Build a process you can explain.</p>
          </div>
          <aside className="ml-progress-card" aria-label="Learning progress" data-testid="learning-progress">
            <div className="ml-progress-top"><span>TRADING ACADEMY PROGRESS</span><BookOpen size={17} aria-hidden="true" /></div>
            {learning.isLoading ? (
              <div className="ml-progress-skeleton" role="status" aria-label="Loading learning progress"><i /><i /></div>
            ) : response ? (
              <>
                <div className="ml-progress-number">{response.completionPercent}<small>%</small></div>
                <div className="ml-progress-track" aria-label={`${response.completionPercent}% complete`}>
                  <span style={{ transform: `scaleX(${Math.max(0, Math.min(100, response.completionPercent)) / 100})` }} />
                </div>
                <div className="ml-progress-meta">
                  <span><strong>{response.completedCount}</strong> of {response.totalCount} lessons</span>
                  <span>{response.totalCount > 0 && response.completedCount === response.totalCount ? 'Path complete' : 'Steady progress'}</span>
                </div>
              </>
            ) : <div className="ml-progress-unavailable">Progress will appear when your lessons load.</div>}
            <div className="ml-privacy-note"><LockKeyhole size={13} /> Your progress is private to your account.</div>
          </aside>
          <div className="ml-intro-index" aria-hidden="true"><span>01</span><i /> LEARN BY OBSERVING</div>
        </section>

        <section className="ml-roadmap" aria-label="Trading Academy roadmap">
          <div className="ml-roadmap-method">
            <div className="ml-roadmap-heading">
              <div><span className="ml-eyebrow">THE LEARNING ROUTE</span><h2>Learn. Practise. Apply. Review.</h2></div>
              <span className="ml-roadmap-motto">LEARN • CONFIRM • EXECUTE • GROW</span>
            </div>
            <div className="ml-roadmap-steps">
              {roadmapSteps.map((step) => (
                <article className="ml-roadmap-step" key={step.number}>
                  <span>{step.number}</span>
                  <div><h3>{step.title}</h3><p>{step.description}</p></div>
                </article>
              ))}
            </div>
          </div>
          <aside className="ml-philosophy" aria-labelledby="ml-philosophy-title">
            <span className="ml-eyebrow">YOUR ESTABLISHED PLAN</span>
            <h2 id="ml-philosophy-title">Our trading philosophy</h2>
            <ul className="ml-philosophy-rules">
              <li><strong>H1</strong><span>Higher-timeframe bias</span></li>
              <li><strong>M5</strong><span>Entry timeframe</span></li>
              <li><strong>2%</strong><span>Risk per trade</span></li>
              <li><strong>1:3</strong><span>Minimum planned risk-to-reward</span></li>
              <li><strong>3%</strong><span>Maximum daily loss</span></li>
              <li><strong>1:1</strong><span>Move to breakeven according to your plan</span></li>
            </ul>
            <p className="ml-philosophy-discipline">No forced entries, FOMO, or revenge trading. No setup means no trade.</p>
            <p className="ml-philosophy-rule">NO CONFIRMATION, NO ENTRY.</p>
            <small>These are your stated rules—not a guarantee or proof that a setup is valid.</small>
          </aside>
        </section>

        {learning.isLoading ? (
          <section className="ml-content-loading" aria-label="Loading your lessons" data-testid="learning-loading">
            <div className="ml-list-skeleton"><i /><i /><i /><i /></div>
            <div className="ml-reading-skeleton"><i /><i /><i /><i /><i /></div>
          </section>
        ) : learning.isError ? (
          <section className="ml-state-panel ml-error-state" role="alert" data-testid="learning-error">
            <span className="ml-state-icon"><RefreshCw size={20} /></span>
            <div><span className="ml-eyebrow">CONNECTION INTERRUPTED</span><h2>Your lessons are taking a moment.</h2><p>Your saved progress is safe. Try loading the learning path again.</p></div>
            <button className="ml-button ml-button-primary" type="button" onClick={() => void learning.refetch()} disabled={learning.isFetching} data-testid="button-retry-learning">
              <RefreshCw size={15} className={learning.isFetching ? 'ml-spin' : ''} /> {learning.isFetching ? 'Retrying' : 'Try again'}
            </button>
          </section>
        ) : lessons.length === 0 ? (
          <section className="ml-state-panel ml-empty-state" data-testid="learning-empty">
            <span className="ml-state-icon"><BookOpen size={21} /></span>
            <div><span className="ml-eyebrow">YOUR STUDY SPACE</span><h2>Your path is being prepared.</h2><p>Verified lesson content will appear here when it is available to your membership.</p></div>
            <span className="ml-empty-foot">No lesson materials are available yet.</span>
          </section>
        ) : (
          <section className="ml-workspace" aria-label="Learning path and lesson">
            <aside className="ml-lesson-rail">
              <div className="ml-rail-heading"><div><span className="ml-eyebrow">PUBLISHED LESSONS</span><h2>Study path</h2></div><span className="ml-count">{String(lessons.length).padStart(2, '0')}</span></div>
              <label className="ml-lesson-search">
                <Search size={15} aria-hidden="true" />
                <input
                  type="search"
                  value={lessonQuery}
                  onChange={(event) => setLessonQuery(event.target.value)}
                  placeholder="Find a lesson"
                  aria-label="Search lessons"
                  data-testid="input-search-lessons"
                />
              </label>
              <div className="ml-lesson-filters" role="group" aria-label="Filter lessons by progress">
                {lessonFilters.map((filter) => (
                  <button
                    key={filter.value}
                    type="button"
                    className={lessonFilter === filter.value ? 'is-active' : ''}
                    aria-pressed={lessonFilter === filter.value}
                    onClick={() => setLessonFilter(filter.value)}
                    data-testid={`filter-lessons-${filter.value}`}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
              <ol className="ml-lesson-list" data-testid="learning-lesson-list">
                {visibleLessons.map((lesson, index) => {
                  const isActive = lesson.lessonId === selected?.lessonId;
                  const isComplete = lesson.progress === 'completed';
                  return (
                    <li key={lesson.lessonId}>
                      <button
                        className={`ml-lesson-item${isActive ? ' is-active' : ''}${isComplete ? ' is-complete' : ''}${lesson.locked ? ' is-locked' : ''}`}
                        type="button"
                        onClick={() => { setSelectedId(lesson.lessonId); setSavedMessage(''); setActionError(''); setDiagramOpen(false); }}
                        aria-label={`${lesson.title}${lesson.locked ? ', available to read; progress requires earlier lessons to be completed.' : ''}`}
                        aria-current={isActive ? 'step' : undefined}
                        data-testid={`learning-lesson-${lesson.lessonId}`}
                      >
                        <span className="ml-lesson-number">{String(lesson.sequence || index + 1).padStart(2, '0')}</span>
                        <span className="ml-lesson-label"><strong>{lesson.title}</strong><small>{lesson.locked ? 'Read ahead' : lessonStatus(lesson.progress)}</small></span>
                        <span className="ml-lesson-state" aria-hidden="true">{lesson.locked ? <LockKeyhole size={13} /> : isComplete ? <Check size={14} /> : isActive ? <ChevronRight size={15} /> : <Circle size={11} />}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <div className="ml-rail-foot"><span className="ml-rail-line" /><span>PROCESS OVER PREDICTION</span></div>
            </aside>

            {visibleLessons.length === 0 ? (
              <section className="ml-no-results" role="status" data-testid="learning-no-results">
                <Search size={18} />
                <strong>No lessons match these filters.</strong>
                <span>Clear the search or choose All to see the full study path.</span>
              </section>
            ) : selected && (
              <article className="ml-reading-panel" data-testid="learning-lesson-detail">
                <div className="ml-reading-topline">
                  <span><span className="ml-live-dot" /> LESSON {String(selected.sequence || activeIndex + 1).padStart(2, '0')}</span>
                  <span className={`ml-status-chip ${selected.progress === 'completed' ? 'is-done' : ''}`}>
                    {selected.locked ? <LockKeyhole size={13} /> : selected.progress === 'completed' ? <CheckCircle2 size={13} /> : <Clock3 size={13} />}
                    {selected.locked ? 'Reading ahead' : lessonStatus(selected.progress)}
                  </span>
                </div>
                {selected.locked && (
                  <aside className="ml-read-ahead-note" role="note" data-testid="learning-read-ahead-note">
                    <LockKeyhole size={16} />
                    <span><strong>Reading ahead is available.</strong> Complete earlier lessons before recording progress on this one.</span>
                  </aside>
                )}
                <h2>{selected.title}</h2>
                <p className="ml-summary">{selected.summary}</p>
                <div className="ml-reading-rule"><span>STUDY NOTES</span><i /></div>
                <div className="ml-body" data-testid="learning-lesson-body">{renderLessonMarkdown(selected.bodyMarkdown)}</div>
                {diagramLessonIds.has(selected.lessonId) && (
                  <div className="ml-lesson-visual">
                    <button
                      className="ml-diagram-toggle"
                      type="button"
                      aria-expanded={diagramOpen}
                      aria-controls={`lesson-diagram-${selected.lessonId}`}
                      onClick={() => setDiagramOpen((open) => !open)}
                    >
                      {diagramOpen ? <EyeOff size={15} /> : <Eye size={15} />}
                          {diagramOpen ? 'Hide guide diagrams' : 'Show guide diagrams'}
                      <ChevronRight size={14} className={diagramOpen ? 'is-expanded' : ''} />
                    </button>
                    {diagramOpen && (
                      <div id={`lesson-diagram-${selected.lessonId}`} className="ml-diagram-content">
                        <MemberLessonDiagram lessonId={selected.lessonId} />
                      </div>
                    )}
                  </div>
                )}
                {lessonActivities[selected.lessonId] && (
                  <section className="ml-lesson-activities" aria-label="Lesson practice, analysis, and review">
                    <article className="ml-activity-card">
                      <span className="ml-eyebrow">PRACTISE</span>
                      <ul>{lessonActivities[selected.lessonId].practise.map((item) => <li key={item}>{item}</li>)}</ul>
                    </article>
                    <article className="ml-activity-card">
                      <span className="ml-eyebrow">ANALYSE</span>
                      <p>{lessonActivities[selected.lessonId].analyse}</p>
                    </article>
                    <article className="ml-activity-card">
                      <span className="ml-eyebrow">REVIEW · SELF-CHECK</span>
                      <ul>{lessonActivities[selected.lessonId].review.map((item) => <li key={item}>{item}</li>)}</ul>
                    </article>
                  </section>
                )}
                {selected.progress === 'completed' && selected.completedAt && <p className="ml-completed-date"><CheckCircle2 size={14} /> Completed {formatDate(selected.completedAt)}</p>}
                {savedMessage && <p className="ml-save-message" role="status" data-testid="learning-saved-message"><CheckCircle2 size={15} /> {savedMessage}</p>}
                {actionError && <p className="ml-action-error" role="alert" data-testid="learning-save-error">{actionError}</p>}
                <div className="ml-reading-actions">
                  <button className="ml-button ml-button-quiet" type="button" onClick={() => moveLesson(-1)} disabled={activeIndex <= 0} data-testid="button-previous-lesson">
                    <ArrowLeft size={15} /> Previous
                  </button>
                  <div className="ml-primary-actions">
                    {!selected.locked && selected.progress === 'not_started' && (
                      <button className="ml-button ml-button-quiet" type="button" onClick={() => void saveProgress(selected, 'in_progress')} disabled={saving} data-testid="button-start-lesson">
                        {saving ? 'Saving…' : 'Start lesson'}
                      </button>
                    )}
                    {!selected.locked && selected.progress !== 'completed' && (
                      <button className="ml-button ml-button-primary" type="button" onClick={() => void saveProgress(selected, 'completed')} disabled={saving} data-testid="button-complete-lesson">
                        {saving ? 'Saving progress…' : 'Mark complete'} <Check size={15} />
                      </button>
                    )}
                    {!selected.locked && selected.progress === 'completed' && (
                      <span className="ml-complete-lock"><CheckCircle2 size={16} /> Progress saved</span>
                    )}
                    <button className="ml-button ml-button-next" type="button" onClick={() => moveLesson(1)} disabled={activeIndex >= visibleLessons.length - 1} data-testid="button-next-lesson">
                      Next lesson <ArrowRight size={15} />
                    </button>
                  </div>
                </div>
              </article>
            )}
          </section>
        )}

        <footer className="ml-footer">
          <span>VAYDA SMART MONEY HUB <i /> LEARN WITH CLARITY</span>
          <span>Education only. Trading involves risk and is not financial advice.</span>
        </footer>
      </div>
    </main>
  );
}
