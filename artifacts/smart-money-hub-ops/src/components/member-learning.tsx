import { useEffect, useMemo, useState } from 'react';
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
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import './member-learning.css';

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
  const [savedMessage, setSavedMessage] = useState('');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    if (!lessons.length) {
      setSelectedId(null);
      return;
    }
    if (selectedId && lessons.some((lesson) => lesson.lessonId === selectedId && !lesson.locked)) return;
    const next = learning.data?.nextLessonId;
    const nextLesson = next ? lessons.find((lesson) => lesson.lessonId === next && !lesson.locked) : undefined;
    setSelectedId(nextLesson?.lessonId ?? lessons.find((lesson) => !lesson.locked)?.lessonId ?? lessons[0].lessonId);
  }, [lessons, learning.data?.nextLessonId, selectedId]);

  const response = learning.data as MemberLearningResponse | undefined;
  const selected = lessons.find((lesson) => lesson.lessonId === selectedId) ?? null;
  const activeIndex = selected ? lessons.findIndex((lesson) => lesson.lessonId === selected.lessonId) : -1;
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
    const target = lessons[activeIndex + offset];
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
            <div className="ml-eyebrow"><span className="ml-live-dot" /> INDEPENDENT MARKET STUDY</div>
            <h1 id="ml-title">Build a sharper<br /><em>way of seeing.</em></h1>
            <p>A private study space for developing your own market-analysis habits. Move at your pace; progress stays with your account.</p>
          </div>
          <aside className="ml-progress-card" aria-label="Learning progress" data-testid="learning-progress">
            <div className="ml-progress-top"><span>YOUR LEARNING PATH</span><BookOpen size={17} aria-hidden="true" /></div>
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
              <div className="ml-rail-heading"><div><span className="ml-eyebrow">THE CURRICULUM</span><h2>Your path</h2></div><span className="ml-count">{String(lessons.length).padStart(2, '0')}</span></div>
              <ol className="ml-lesson-list" data-testid="learning-lesson-list">
                {lessons.map((lesson, index) => {
                  const isActive = lesson.lessonId === selected?.lessonId;
                  const isComplete = lesson.progress === 'completed';
                  return (
                    <li key={lesson.lessonId}>
                      <button
                        className={`ml-lesson-item${isActive ? ' is-active' : ''}${isComplete ? ' is-complete' : ''}${lesson.locked ? ' is-locked' : ''}`}
                        type="button"
                        onClick={() => { if (lesson.locked) return; setSelectedId(lesson.lessonId); setSavedMessage(''); setActionError(''); }}
                        disabled={lesson.locked}
                        aria-disabled={lesson.locked}
                        aria-label={`${lesson.title}${lesson.locked ? ', locked. Complete the prior lesson first.' : ''}`}
                        aria-current={isActive ? 'step' : undefined}
                        data-testid={`learning-lesson-${lesson.lessonId}`}
                      >
                        <span className="ml-lesson-number">{String(lesson.sequence || index + 1).padStart(2, '0')}</span>
                        <span className="ml-lesson-label"><strong>{lesson.title}</strong><small>{lesson.locked ? 'Locked' : lessonStatus(lesson.progress)}</small></span>
                        <span className="ml-lesson-state" aria-hidden="true">{lesson.locked ? <LockKeyhole size={13} /> : isComplete ? <Check size={14} /> : isActive ? <ChevronRight size={15} /> : <Circle size={11} />}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <div className="ml-rail-foot"><span className="ml-rail-line" /><span>PROCESS OVER PREDICTION</span></div>
            </aside>

            {selected && (
              <article className="ml-reading-panel" data-testid="learning-lesson-detail">
                <div className="ml-reading-topline">
                  <span><span className="ml-live-dot" /> LESSON {String(selected.sequence || activeIndex + 1).padStart(2, '0')}</span>
                  <span className={`ml-status-chip ${selected.progress === 'completed' ? 'is-done' : ''}`}>
                    {selected.locked ? <LockKeyhole size={13} /> : selected.progress === 'completed' ? <CheckCircle2 size={13} /> : <Clock3 size={13} />}
                    {selected.locked ? 'Locked' : lessonStatus(selected.progress)}
                  </span>
                </div>
                {selected.locked ? (
                  <section className="ml-locked-content" aria-live="polite" data-testid="learning-lesson-locked">
                    <span className="ml-locked-icon"><LockKeyhole size={19} /></span>
                    <span className="ml-eyebrow">NEXT STEP LOCKED</span>
                    <h2>{selected.title}</h2>
                    <p>Complete the prior lesson first to unlock this part of your learning path.</p>
                  </section>
                ) : (
                  <>
                    <h2>{selected.title}</h2>
                    <p className="ml-summary">{selected.summary}</p>
                    <div className="ml-reading-rule"><span>STUDY NOTES</span><i /></div>
                    <div className="ml-body" data-testid="learning-lesson-body">{selected.bodyMarkdown}</div>
                    {selected.progress === 'completed' && selected.completedAt && <p className="ml-completed-date"><CheckCircle2 size={14} /> Completed {formatDate(selected.completedAt)}</p>}
                  </>
                )}
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
                    <button className="ml-button ml-button-next" type="button" onClick={() => moveLesson(1)} disabled={activeIndex >= lessons.length - 1} data-testid="button-next-lesson">
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
