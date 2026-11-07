import { useMemo, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getListPortalMemberAnnouncementsQueryKey,
  useCreatePortalMemberAnnouncement,
  useListPortalMemberAnnouncements,
  usePublishPortalMemberAnnouncement,
  useUpdatePortalMemberAnnouncement,
} from '@workspace/api-client-react';
import type { PortalMemberAnnouncement, PortalSession } from '@workspace/api-client-react';
import {
  ArrowUpRight,
  BellRing,
  BookOpen,
  Check,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FilePenLine,
  LockKeyhole,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';
import './staff-announcements.css';

type TargetPath = '/member/learning' | '/member/dashboard';
type Editor = { id: string | null; title: string; message: string; targetPath: TargetPath };
type PublishReceipt = { recipientCount: number; audienceLabel: string; title: string };

const audienceCopy = 'Verified Development Clerk members, excluding staff';

function makeRequestId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `announcement-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function dateLabel(value: string | null | undefined) {
  if (!value) return 'Date unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function targetName(path: TargetPath) {
  return path === '/member/learning' ? 'Learning' : 'Member dashboard';
}

function AnnouncementCard({
  item,
  canEdit,
  canPublish,
  onEdit,
  onPublish,
}: {
  item: PortalMemberAnnouncement;
  canEdit: boolean;
  canPublish: boolean;
  onEdit: (item: PortalMemberAnnouncement) => void;
  onPublish: (item: PortalMemberAnnouncement) => void;
}) {
  const published = item.status === 'published';
  return (
    <article className={`sa-card${published ? ' is-published' : ''}`} data-testid={`announcement-${item.announcementId}`}>
      <div className="sa-card-rail" aria-hidden="true" />
      <div className="sa-card-content">
        <div className="sa-card-topline">
          <span className={`sa-status ${published ? 'sa-status-published' : 'sa-status-draft'}`} data-testid={`status-announcement-${item.announcementId}`}>
            <span className="sa-status-dot" />{published ? 'Published' : 'Draft'}
          </span>
          <span className="sa-card-date"><Clock3 size={12} />{dateLabel(published ? item.publishedAt : item.createdAt)}</span>
        </div>
        <h3 data-testid={`title-announcement-${item.announcementId}`}>{item.title}</h3>
        <p className="sa-message" data-testid={`message-announcement-${item.announcementId}`}>{item.message}</p>
        <div className="sa-card-meta">
          <span className="sa-destination"><ArrowUpRight size={12} /> Opens {targetName(item.targetPath)}</span>
          <span className="sa-author">{published ? `Published by ${item.publishedByName || 'staff'}` : `Created by ${item.createdByName}`}</span>
        </div>
        {published && item.recipientCount !== null && (
          <div className="sa-published-audience" data-testid={`recipients-${item.announcementId}`}>
            <CheckCircle2 size={13} /> {item.recipientCount.toLocaleString()} in-app {item.recipientCount === 1 ? 'notification' : 'notifications'} · Development members
          </div>
        )}
      </div>
      {!published && <div className="sa-card-actions">
        {canEdit && <button type="button" className="sa-button sa-button-quiet" onClick={() => onEdit(item)} data-testid={`button-edit-${item.announcementId}`}><FilePenLine size={14} /> Edit draft</button>}
        {canPublish && <button type="button" className="sa-button sa-button-publish" onClick={() => onPublish(item)} data-testid={`button-publish-${item.announcementId}`}><Send size={14} /> Review & publish</button>}
        {!canPublish && <span className="sa-restricted"><LockKeyhole size={12} /> Owner publishes</span>}
      </div>}
      {published && <div className="sa-readonly" aria-label="Published announcements are read only"><LockKeyhole size={13} /> Read only</div>}
    </article>
  );
}

export default function StaffAnnouncements({ session }: { session: PortalSession }) {
  const client = useQueryClient();
  const listKey = getListPortalMemberAnnouncementsQueryKey();
  const query = useListPortalMemberAnnouncements({ query: { queryKey: listKey, retry: false } });
  const createAnnouncement = useCreatePortalMemberAnnouncement();
  const updateAnnouncement = useUpdatePortalMemberAnnouncement();
  const publishAnnouncement = usePublishPortalMemberAnnouncement();
  const [editor, setEditor] = useState<Editor | null>(null);
  const [publishTarget, setPublishTarget] = useState<PortalMemberAnnouncement | null>(null);
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);
  const [receipt, setReceipt] = useState<PublishReceipt | null>(null);
  const isOwner = session.role === 'owner';
  const isManager = session.role === 'manager';
  const canCreate = isOwner || isManager;
  const announcements = query.data?.announcements ?? [];
  const drafts = useMemo(() => announcements.filter((item) => item.status === 'draft'), [announcements]);
  const published = useMemo(() => announcements.filter((item) => item.status === 'published'), [announcements]);
  const busy = createAnnouncement.isPending || updateAnnouncement.isPending || publishAnnouncement.isPending;
  const loading = query.isLoading;
  const audienceLabel = query.data?.audienceLabel === 'verified_development_members_excluding_staff'
    ? audienceCopy
    : audienceCopy;

  const refresh = async () => {
    setFeedback(null);
    await query.refetch();
  };

  const startNew = () => {
    setFeedback(null);
    setReceipt(null);
    setEditor({ id: null, title: '', message: '', targetPath: '/member/learning' });
  };

  const startEdit = (item: PortalMemberAnnouncement) => {
    setFeedback(null);
    setReceipt(null);
    setEditor({ id: item.announcementId, title: item.title, message: item.message, targetPath: item.targetPath });
  };

  const saveDraft = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editor || busy) return;
    setFeedback(null);
    const data = {
      title: editor.title.trim(),
      message: editor.message.trim(),
      targetPath: editor.targetPath,
    };
    try {
      if (editor.id) {
        await updateAnnouncement.mutateAsync({ announcementId: editor.id, data });
      } else {
        await createAnnouncement.mutateAsync({ data: { ...data, requestId: makeRequestId() } });
      }
      await client.invalidateQueries({ queryKey: getListPortalMemberAnnouncementsQueryKey() });
      setEditor(null);
      setFeedback({ kind: 'success', message: editor.id ? 'Draft changes saved.' : 'Announcement saved as a draft.' });
    } catch (failure) {
      setFeedback({ kind: 'error', message: errorText(failure, 'The draft could not be saved. Your text is still here; try again.') });
    }
  };

  const confirmPublish = async () => {
    if (!publishTarget || publishAnnouncement.isPending) return;
    setFeedback(null);
    try {
      const result = await publishAnnouncement.mutateAsync({ announcementId: publishTarget.announcementId, data: { confirm: true } });
      await client.invalidateQueries({ queryKey: getListPortalMemberAnnouncementsQueryKey() });
      setReceipt({
        recipientCount: result.recipientCount,
        audienceLabel: result.audienceLabel === 'verified_development_members_excluding_staff' ? audienceCopy : audienceCopy,
        title: result.announcement.title,
      });
      setPublishTarget(null);
      setFeedback({ kind: 'success', message: 'Announcement published to the Development in-app audience.' });
    } catch (failure) {
      setFeedback({ kind: 'error', message: errorText(failure, 'Publishing did not complete. Check the draft and try again.') });
      setPublishTarget(null);
    }
  };

  const canEditDraft = (item: PortalMemberAnnouncement) => isOwner || (isManager && item.createdByName === session.displayName);

  return (
    <main className="staff-announcements" data-testid="staff-announcements-page">
      <div className="sa-shell">
        <header className="sa-heading">
          <div className="sa-eyebrow"><span className="sa-eyebrow-mark" /> MEMBER COMMUNICATIONS <span className="sa-eyebrow-divider">/</span> DEVELOPMENT</div>
          <div className="sa-heading-row">
            <div>
              <h1>Announcements<span className="sa-heading-period">.</span></h1>
              <p>Prepare clear updates for the member workspace. Publishing is deliberate and in-app only.</p>
            </div>
            {canCreate && <button type="button" className="sa-button sa-button-primary" onClick={startNew} disabled={Boolean(editor) || busy} data-testid="button-new-announcement"><Plus size={16} /> New announcement</button>}
          </div>
          <div className="sa-heading-rule"><span>01</span><i /><span>COMPOSE → REVIEW → PUBLISH</span></div>
        </header>

        {feedback && <div className={`sa-feedback is-${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'} data-testid={`status-announcement-${feedback.kind}`}>
          {feedback.kind === 'success' ? <Check size={15} /> : <CircleAlert size={15} />}<span>{feedback.message}</span>
          <button type="button" onClick={() => setFeedback(null)} aria-label="Dismiss message" data-testid="button-dismiss-feedback"><X size={14} /></button>
        </div>}

        {receipt && <section className="sa-receipt" role="status" aria-live="polite" data-testid="publish-result">
          <div className="sa-receipt-icon"><CheckCircle2 size={19} /></div>
          <div className="sa-receipt-copy"><span className="sa-kicker">PUBLICATION CONFIRMED</span><h2>{receipt.title}</h2><p><strong>{receipt.recipientCount.toLocaleString()}</strong> in-app {receipt.recipientCount === 1 ? 'notification' : 'notifications'} created for {receipt.audienceLabel}.</p></div>
          <button type="button" onClick={() => setReceipt(null)} aria-label="Dismiss publish result" data-testid="button-dismiss-publish-result"><X size={15} /></button>
        </section>}

        <div className="sa-layout">
          <section className="sa-list-column" aria-label="Announcement records">
            <div className="sa-section-header">
              <div><span className="sa-kicker">WORKFLOW QUEUE</span><h2>Member updates</h2></div>
              <button type="button" className="sa-refresh" onClick={() => void refresh()} disabled={query.isFetching} aria-label="Refresh announcements" data-testid="button-refresh-announcements"><RefreshCw size={14} className={query.isFetching ? 'is-refreshing' : ''} /><span>{query.isFetching ? 'Refreshing' : 'Refresh'}</span></button>
            </div>

            {loading ? <div className="sa-skeleton-list" aria-label="Loading announcements" data-testid="state-announcements-loading">
              {[0, 1, 2].map((row) => <div className="sa-skeleton-card" key={row}><i /><div><b /><b /><b /></div></div>)}
            </div> : query.isError ? <div className="sa-state sa-error-state" role="alert" data-testid="state-announcements-error">
              <span className="sa-state-icon"><CircleAlert size={19} /></span><span className="sa-kicker">LIST UNAVAILABLE</span><h3>Could not load announcements</h3><p>We could not reach the announcement service. Existing records have not been changed.</p>
              <button type="button" className="sa-button sa-button-secondary" onClick={() => void refresh()} disabled={query.isFetching} data-testid="button-retry-announcements"><RefreshCw size={13} /> Try again</button>
            </div> : <>
              {!canCreate && <div className="sa-role-note" role="status" data-testid="status-role-unavailable"><LockKeyhole size={14} /> This workflow is available to Owners and Managers. Your current staff role is {session.role}.</div>}
              <div className="sa-list-summary"><span>{drafts.length} {drafts.length === 1 ? 'draft' : 'drafts'}</span><span>{published.length} published</span></div>
              <div className="sa-list-block">
                <div className="sa-subheading"><span className="sa-subheading-index">A</span><h3>Drafts</h3><span className="sa-subheading-line" /><span className="sa-count" data-testid="count-announcement-drafts">{drafts.length.toString().padStart(2, '0')}</span></div>
                {drafts.length === 0 ? <div className="sa-empty" data-testid="state-no-drafts">
                  <div className="sa-empty-mark"><FilePenLine size={19} /></div><div><span className="sa-kicker">NOTHING IN THE QUEUE</span><h4>No drafts yet</h4><p>{canCreate ? 'A thoughtful update starts here. Create a draft to review its wording and destination before publication.' : 'There are no member announcements waiting for review.'}</p></div>
                  {canCreate && <button type="button" className="sa-text-action" onClick={startNew} disabled={Boolean(editor) || busy} data-testid="button-create-first-announcement"><Plus size={14} /> Create a draft</button>}
                </div> : <div className="sa-cards">{drafts.map((item) => <AnnouncementCard key={item.announcementId} item={item} canEdit={canEditDraft(item)} canPublish={isOwner} onEdit={startEdit} onPublish={setPublishTarget} />)}</div>}
              </div>

              <div className="sa-list-block sa-published-block">
                <div className="sa-subheading"><span className="sa-subheading-index">B</span><h3>Published</h3><span className="sa-subheading-line" /><span className="sa-count" data-testid="count-announcement-published">{published.length.toString().padStart(2, '0')}</span></div>
                {published.length === 0 ? <div className="sa-empty sa-empty-compact" data-testid="state-no-published"><div className="sa-empty-mark"><BellRing size={17} /></div><div><span className="sa-kicker">PUBLICATION HISTORY</span><h4>No published updates</h4><p>Once an Owner publishes a draft, the record and recipient count will appear here.</p></div></div> : <div className="sa-cards">{published.map((item) => <AnnouncementCard key={item.announcementId} item={item} canEdit={false} canPublish={false} onEdit={startEdit} onPublish={setPublishTarget} />)}</div>}
              </div>
            </>}
          </section>

          <aside className="sa-guidance" aria-label="Publishing guidance">
            <div className="sa-guidance-top"><span className="sa-guidance-icon"><ShieldCheck size={17} /></span><span className="sa-kicker">CONTROLLED DELIVERY</span></div>
            <h2>Clear words.<br /><em>Careful reach.</em></h2>
            <p className="sa-guidance-intro">A publication creates notifications inside the member workspace. It does not send a message across other channels.</p>
            <div className="sa-audience-box" data-testid="announcement-audience">
              <span className="sa-audience-label">AUDIENCE</span><strong>Development members</strong><span>{audienceLabel}</span>
            </div>
            <div className="sa-channel-list" aria-label="Delivery channel scope">
              <div><CheckCircle2 size={14} /><span>In-app notifications</span><span className="sa-channel-included">INCLUDED</span></div>
              <div><X size={13} /><span>Email, Telegram, push</span><span className="sa-channel-excluded">NOT SENT</span></div>
              <div><X size={13} /><span>Live bot delivery</span><span className="sa-channel-excluded">NOT SENT</span></div>
            </div>
            <div className="sa-permissions">
              <span className="sa-kicker">ROLE CONTROLS</span>
              <p><strong>Managers</strong> can create drafts and edit their own drafts. They cannot publish.</p>
              <p><strong>Owners</strong> can edit any draft and publish after explicit confirmation.</p>
              <small>Published announcements are read-only. The server remains authoritative for all permissions.</small>
            </div>
            <div className="sa-target-note"><BookOpen size={14} /><span>Targets are limited to the member Learning page or dashboard.</span></div>
          </aside>
        </div>

        {editor && <div className="sa-editor-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setEditor(null); }}>
          <section className="sa-editor" role="dialog" aria-modal="true" aria-labelledby="sa-editor-title" data-testid="announcement-editor">
            <div className="sa-dialog-heading"><div><span className="sa-kicker">{editor.id ? 'DRAFT / EDIT' : 'DRAFT / NEW'}</span><h2 id="sa-editor-title">{editor.id ? 'Refine the update' : 'Compose an announcement'}</h2></div><button type="button" className="sa-dialog-close" onClick={() => setEditor(null)} disabled={busy} aria-label="Close editor" data-testid="button-close-announcement-editor"><X size={17} /></button></div>
            <p className="sa-dialog-intro">Write a concise member update. Saving keeps it as a draft; publication is a separate Owner action.</p>
            <form onSubmit={(event) => void saveDraft(event)}>
              <label className="sa-field"><span>Headline <small>{editor.title.length}/120</small></span><input autoFocus required maxLength={120} value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} placeholder="A clear, specific headline" data-testid="input-announcement-title" /></label>
              <label className="sa-field"><span>Message <small>{editor.message.length}/500</small></span><textarea required maxLength={500} rows={5} value={editor.message} onChange={(event) => setEditor({ ...editor, message: event.target.value })} placeholder="Share the update and what members should know next." data-testid="input-announcement-message" /></label>
              <label className="sa-field"><span>Member destination</span><select value={editor.targetPath} onChange={(event) => setEditor({ ...editor, targetPath: event.target.value as TargetPath })} data-testid="select-announcement-target"><option value="/member/learning">Learning</option><option value="/member/dashboard">Member dashboard</option></select><small className="sa-field-help">Opening the notification takes members to this page.</small></label>
              {editor.id && isManager && <div className="sa-inline-permission"><LockKeyhole size={13} /> This draft is editable by its creator. Only an Owner can publish it.</div>}
              <div className="sa-form-footer"><span className="sa-form-draft-label"><FilePenLine size={13} /> SAVES AS DRAFT</span><div><button type="button" className="sa-button sa-button-quiet" onClick={() => setEditor(null)} disabled={busy} data-testid="button-cancel-announcement">Cancel</button><button type="submit" className="sa-button sa-button-primary" disabled={busy || !editor.title.trim() || !editor.message.trim()} data-testid="button-save-announcement">{busy ? 'Saving…' : editor.id ? 'Save changes' : 'Save draft'} <Check size={14} /></button></div></div>
            </form>
          </section>
        </div>}

        {publishTarget && <div className="sa-editor-backdrop sa-confirm-backdrop" role="presentation">
          <section className="sa-confirm" role="dialog" aria-modal="true" aria-labelledby="sa-confirm-title" data-testid="publish-confirmation">
            <span className="sa-confirm-symbol"><Send size={18} /></span><span className="sa-kicker">OWNER REVIEW / FINAL STEP</span><h2 id="sa-confirm-title">Publish this update?</h2>
            <p className="sa-confirm-title-preview">“{publishTarget.title}”</p>
            <div className="sa-confirm-detail"><ShieldCheck size={15} /><span>This creates in-app notifications for <strong>{audienceCopy}</strong>. No email, Telegram, push, or live bot delivery will occur.</span></div>
            <div className="sa-confirm-actions"><button type="button" className="sa-button sa-button-quiet" onClick={() => setPublishTarget(null)} disabled={publishAnnouncement.isPending} data-testid="button-cancel-publish">Keep as draft</button><button type="button" className="sa-button sa-button-publish" onClick={() => void confirmPublish()} disabled={publishAnnouncement.isPending} data-testid="button-confirm-publish"><Send size={14} />{publishAnnouncement.isPending ? 'Publishing…' : 'Confirm publish'}</button></div>
          </section>
        </div>}

        <footer className="sa-footer"><span>SMART MONEY HUB <i /> OPERATIONS / MEMBER ANNOUNCEMENTS</span><span data-testid="text-current-role">SESSION ROLE · {session.role.toUpperCase()}</span></footer>
      </div>
    </main>
  );
}
