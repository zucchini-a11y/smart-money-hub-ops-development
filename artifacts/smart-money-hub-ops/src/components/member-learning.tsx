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
import { MemberCoachPopout } from './member-coach-popout';

const diagramLessonIds = new Set([
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

function splitLessonActivities(markdown: string): { bodyMarkdown: string; activities: LessonActivity | null } {
  const body: string[] = [];
  const sections: Record<keyof LessonActivity, string[]> = { practise: [], analyse: [], review: [] };
  let activeSection: keyof LessonActivity | null = null;

  for (const line of markdown.split(/\r?\n/)) {
    const heading = line.trim().match(/^##\s+(PRACTISE|ANALYSE|REVIEW)\s*$/i);
    if (heading) {
      activeSection = heading[1].toLocaleLowerCase() as keyof LessonActivity;
      continue;
    }
    if (!activeSection) body.push(line);
    else sections[activeSection].push(line);
  }

  const bullets = (lines: string[]) => lines
    .map((line) => line.trim().match(/^[-*]\s+(.+)$/)?.[1])
    .filter((line): line is string => Boolean(line));
  const analyse = sections.analyse.map((line) => line.trim()).filter(Boolean).join(" ");
  const hasActivities = sections.practise.length > 0 || Boolean(analyse) || sections.review.length > 0;

  return {
    bodyMarkdown: body.join("\n").trim(),
    activities: hasActivities
      ? { practise: bullets(sections.practise), analyse, review: bullets(sections.review) }
      : null,
  };
}

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
  const selectedContent = selected && !selected.locked
    ? splitLessonActivities(selected.bodyMarkdown)
    : null;
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
            <p>Complete lessons in order. Finish the current lesson to unlock the next one, then practise, analyse, and review.</p>
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
                        aria-label={`${lesson.title}${lesson.locked ? ', locked until earlier lessons are completed.' : ''}`}
                        aria-current={isActive ? 'step' : undefined}
                        data-testid={`learning-lesson-${lesson.lessonId}`}
                      >
                        <span className="ml-lesson-number">{String(lesson.sequence || index + 1).padStart(2, '0')}</span>
                        <span className="ml-lesson-label"><strong>{lesson.title}</strong><small>{lesson.locked ? 'Locked · finish the previous lesson' : lessonStatus(lesson.progress)}</small></span>
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
                    {selected.locked ? 'Locked' : lessonStatus(selected.progress)}
                  </span>
                </div>
                <h2>{selected.title}</h2>
                {selected.locked ? (
                  <section className="ml-locked-content" role="note" data-testid="learning-locked-note">
                    <span className="ml-locked-icon"><LockKeyhole size={18} /></span>
                    <span className="ml-eyebrow">LESSON LOCKED</span>
                    <strong className="ml-locked-title">Complete the previous lesson to unlock this one.</strong>
                    <p>Finish and mark the lesson before this one as complete. Its notes, real candlestick diagrams, and exercises will then become available.</p>
                  </section>
                ) : (
                  <>
                    <p className="ml-summary">{selected.summary}</p>
                    <div className="ml-reading-rule"><span>STUDY NOTES</span><i /></div>
                    <div className="ml-body" data-testid="learning-lesson-body">{renderLessonMarkdown(selectedContent?.bodyMarkdown ?? '')}</div>
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
                    {selectedContent?.activities && (
                      <section className="ml-lesson-activities" aria-label="Lesson practice, analysis, and review">
                        <article className="ml-activity-card">
                          <span className="ml-eyebrow">PRACTISE</span>
                          <ul>{selectedContent.activities.practise.map((item) => <li key={item}>{item}</li>)}</ul>
                        </article>
                        <article className="ml-activity-card">
                          <span className="ml-eyebrow">ANALYSE</span>
                          <p>{selectedContent.activities.analyse}</p>
                        </article>
                        <article className="ml-activity-card">
                          <span className="ml-eyebrow">REVIEW · SELF-CHECK</span>
                          <ul>{selectedContent.activities.review.map((item) => <li key={item}>{item}</li>)}</ul>
                        </article>
                      </section>
                    )}
                    {selected.progress === 'completed' && selected.completedAt && <p className="ml-completed-date"><CheckCircle2 size={14} /> Completed {formatDate(selected.completedAt)}</p>}
                    {savedMessage && <p className="ml-save-message" role="status" data-testid="learning-saved-message"><CheckCircle2 size={15} /> {savedMessage}</p>}
                    {actionError && <p className="ml-action-error" role="alert" data-testid="learning-save-error">{actionError}</p>}
                  </>
                )}
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

        <footer className="ml-footer">
          <span>VAYDA SMART MONEY HUB <i /> LEARN WITH CLARITY</span>
          <span>Education only. Trading involves risk and is not financial advice.</span>
        </footer>
      </div>
      {lessons.length > 0 && <MemberCoachPopout lessonTitle={selected?.title} />}
    </main>
  );
}
