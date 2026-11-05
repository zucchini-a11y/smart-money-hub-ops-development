import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getListEducationVideosQueryKey,
  useCreateEducationVideoDraft,
  useListEducationVideos,
  usePublishEducationVideo,
  useUploadEducationVideoFile,
} from '@workspace/api-client-react';
import type { EducationVideo } from '@workspace/api-client-react';
import { ArrowLeft, Check, CircleAlert, Clapperboard, FileVideo2, LockKeyhole, RefreshCw, Upload } from 'lucide-react';
import { Link } from 'wouter';
import { trackEvent } from '@/lib/analytics';

const MAX_BYTES = 50_000_000;
const videoStorageAvailable = false;

function friendlyError(error: unknown) {
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string') return error.message;
  return 'The request could not be completed. Check the status below before taking another action.';
}

function statusText(status: string) {
  const labels: Record<string, string> = {
    awaiting_upload: 'Awaiting upload',
    draft: 'Draft uploaded',
    queued: 'Queued for publishing',
    sending: 'Publishing',
    published: 'Published',
    uncertain: 'Status uncertain',
    failed: 'Failed',
    blocked: 'Blocked',
  };
  return labels[status] ?? status.replaceAll('_', ' ');
}

function fileSize(bytes: number) {
  if (bytes < 1_000_000) return `${Math.max(1, Math.round(bytes / 1000))} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

function validateMp4(file: File) {
  if (!file.name.toLowerCase().endsWith('.mp4') || (file.type && file.type !== 'video/mp4')) return 'Choose an MP4 video file.';
  if (file.size < 1 || file.size > MAX_BYTES) return 'The video must be smaller than 50 MB.';
  return '';
}

function dateLabel(value?: string | null) {
  if (!value) return 'Not published';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function VideoStatus({ status }: { status: string }) {
  return <span className={`education-status education-status-${status}`} data-testid={`video-status-${status}`}>{statusText(status)}</span>;
}

export default function EducationVideos() {
  const queryClient = useQueryClient();
  const listKey = getListEducationVideosQueryKey();
  const query = useListEducationVideos({ query: { queryKey: listKey } });
  const createDraft = useCreateEducationVideoDraft();
  const uploadFile = useUploadEducationVideoFile();
  const publishVideo = usePublishEducationVideo();
  const [title, setTitle] = useState('');
  const [caption, setCaption] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [formError, setFormError] = useState('');
  const [actionError, setActionError] = useState('');
  const [activeVideoId, setActiveVideoId] = useState<string | null>(null);
  const [uploadBlockedIds, setUploadBlockedIds] = useState<string[]>([]);
  const [publishBlockedIds, setPublishBlockedIds] = useState<string[]>([]);
  const [resumeFiles, setResumeFiles] = useState<Record<string, File | undefined>>({});
  const [resumeErrors, setResumeErrors] = useState<Record<string, string | undefined>>({});
  const data = query.data;
  const videos = useMemo(() => data?.videos ?? [], [data?.videos]);

  useEffect(() => {
    const confirmedDraftIds = new Set(videos.filter((video) => video.status === 'draft').map((video) => video.videoId));
    if (!confirmedDraftIds.size) return;
    setUploadBlockedIds((current) => current.filter((videoId) => !confirmedDraftIds.has(videoId)));
  }, [videos]);

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0] ?? null;
    setFormError('');
    if (!videoStorageAvailable) {
      setFile(null);
      event.target.value = '';
      setFormError('MP4 uploads are paused until secure file storage is available.');
      return;
    }
    if (!picked) {
      setFile(null);
      return;
    }
    const validationMessage = validateMp4(picked);
    if (validationMessage) {
      setFile(null);
      event.target.value = '';
      setFormError(validationMessage);
      return;
    }
    setFile(picked);
  };

  const chooseResumeFile = (video: EducationVideo, event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0] ?? null;
    event.target.value = '';
    setResumeErrors((current) => ({ ...current, [video.videoId]: undefined }));
    if (!picked) {
      setResumeFiles((current) => ({ ...current, [video.videoId]: undefined }));
      return;
    }
    const validationMessage = validateMp4(picked);
    if (validationMessage) {
      setResumeFiles((current) => ({ ...current, [video.videoId]: undefined }));
      setResumeErrors((current) => ({ ...current, [video.videoId]: validationMessage }));
      return;
    }
    if (picked.name !== video.fileName || picked.size !== video.byteSize) {
      setResumeFiles((current) => ({ ...current, [video.videoId]: undefined }));
      setResumeErrors((current) => ({ ...current, [video.videoId]: `Choose the original file (${video.fileName}, ${fileSize(video.byteSize)}) to resume this upload.` }));
      return;
    }
    setResumeFiles((current) => ({ ...current, [video.videoId]: picked }));
  };

  const resumeUpload = (video: EducationVideo) => {
    const selectedFile = resumeFiles[video.videoId];
    if (!videoStorageAvailable || !selectedFile || video.status !== 'awaiting_upload') return;
    setActionError('');
    setActiveVideoId(video.videoId);
    uploadFile.mutate({ videoId: video.videoId, data: selectedFile }, {
      onSuccess: (uploaded) => {
        trackEvent('education_video_upload_completed');
        setResumeFiles((current) => ({ ...current, [video.videoId]: undefined }));
        setResumeErrors((current) => ({ ...current, [video.videoId]: undefined }));
        setUploadBlockedIds((current) => current.filter((id) => id !== uploaded.videoId));
        void queryClient.invalidateQueries({ queryKey: listKey });
        if (uploaded.status !== 'draft') {
          setActionError(`Upload finished with status “${statusText(uploaded.status)}”. Review the item status below. This action only uploads the file; it does not publish to Telegram.`);
        }
      },
      onError: (error) => {
        setUploadBlockedIds((current) => current.includes(video.videoId) ? current : [...current, video.videoId]);
        setActionError(`Upload status could not be confirmed: ${friendlyError(error)} Refresh the list before deciding whether to resume. Resuming uploads the file only; it does not publish to Telegram.`);
        void queryClient.invalidateQueries({ queryKey: listKey });
      },
    });
  };

  const createAndUpload = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError('');
    setActionError('');
    if (!videoStorageAvailable) {
      setFormError('MP4 uploads are paused until secure file storage is available.');
      return;
    }
    if (!file) {
      setFormError('Choose an MP4 video file to continue.');
      return;
    }
    const cleanTitle = title.trim();
    const cleanCaption = caption.trim();
    if (cleanTitle.length < 2 || cleanTitle.length > 120) {
      setFormError('Title must be 2 to 120 characters.');
      return;
    }
    if (!cleanCaption || cleanCaption.length > 900) {
      setFormError('Caption must be 1 to 900 characters.');
      return;
    }
    const selectedFile = file;
    createDraft.mutate({
      data: {
        title: cleanTitle,
        caption: cleanCaption,
        fileName: selectedFile.name,
        byteSize: selectedFile.size,
        contentType: 'video/mp4',
        requestId: crypto.randomUUID(),
      },
    }, {
      onSuccess: (draft) => {
        trackEvent('education_video_draft_created');
        setTitle('');
        setCaption('');
        setFile(null);
        const input = document.getElementById('education-video-file') as HTMLInputElement | null;
        if (input) input.value = '';
        setActiveVideoId(draft.videoId);
        void queryClient.invalidateQueries({ queryKey: listKey });
        if (draft.status !== 'awaiting_upload') {
          setActionError(`Draft created with status “${statusText(draft.status)}”. No upload retry is available from this page.`);
          return;
        }
        uploadFile.mutate({ videoId: draft.videoId, data: selectedFile }, {
          onSuccess: (uploaded) => {
            trackEvent('education_video_upload_completed');
            setActiveVideoId(uploaded.videoId);
            void queryClient.invalidateQueries({ queryKey: listKey });
            if (uploaded.status !== 'draft') {
              setActionError(`Upload finished with status “${statusText(uploaded.status)}”. Review the item status below.`);
            }
          },
          onError: (error) => {
            setUploadBlockedIds((current) => current.includes(draft.videoId) ? current : [...current, draft.videoId]);
            setActionError(`Upload status could not be confirmed: ${friendlyError(error)} Check the item status below. If it is still awaiting upload, resume uploads the file only; it does not publish to Telegram.`);
            void queryClient.invalidateQueries({ queryKey: listKey });
          },
        });
      },
      onError: (error) => setFormError(friendlyError(error)),
    });
  };

  const publish = (video: EducationVideo) => {
    if (!videoStorageAvailable) {
      setActionError('Publishing is paused until secure video storage is available.');
      return;
    }
    setActionError('');
    publishVideo.mutate({
      videoId: video.videoId,
      data: { requestId: crypto.randomUUID() },
    }, {
      onSuccess: (published) => {
        trackEvent('education_video_publish_result', { status: published.status });
        setActiveVideoId(published.videoId);
        void queryClient.invalidateQueries({ queryKey: listKey });
        if (published.status === 'uncertain' || published.status === 'failed') {
          setActionError(`Publishing returned “${statusText(published.status)}”. Do not submit it again.`);
        }
      },
      onError: (error) => {
        setPublishBlockedIds((current) => current.includes(video.videoId) ? current : [...current, video.videoId]);
        setActionError(`Publishing status could not be confirmed: ${friendlyError(error)} Do not submit it again. Refresh the list to check its status.`);
        void queryClient.invalidateQueries({ queryKey: listKey });
      },
    });
  };

  const publishAllowed = Boolean(data?.targetAvailable && data.publishingEnabled);
  const busy = createDraft.isPending || uploadFile.isPending || publishVideo.isPending;

  return <main className="page command-page education-page">
    <div className="command-kicker"><span className="command-kicker-mark"><Clapperboard size={15}/></span><span>OWNER WORKSPACE</span><i/>MEMBER EDUCATION</div>
    <div className="education-heading">
      <div>
        <Link className="education-back" href="/command-center"><ArrowLeft size={15}/> Command center</Link>
        <div className="eyebrow">LESSON LIBRARY</div>
        <h1>Education videos</h1>
        <p className="subheading">Prepare a lesson, review its caption, then publish when you are ready.</p>
      </div>
      <div className="education-private"><LockKeyhole size={15}/><span>Owner only</span></div>
    </div>

    <section className="education-destination destination-paused" data-testid="education-storage-gate">
      <div className="education-destination-icon"><LockKeyhole size={17}/></div>
      <div className="education-destination-copy">
        <span className="eyebrow">SECURE VIDEO STORAGE</span>
          <strong>Owner session active</strong>
          <p>MP4 upload, preview, and publishing are paused until persistent file storage is available. No video files are saved on the server.</p>
      </div>
    </section>

    {query.isLoading ? <section className="education-loading" aria-label="Loading education videos" data-testid="education-loading">
      <div className="education-skeleton-head"><div className="skeleton"/><div className="skeleton"/></div>
      <div className="education-skeleton-grid"><div className="education-skeleton-card"><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></div><div className="education-skeleton-card"><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></div></div>
    </section> : query.isError ? <section className="education-feedback" data-testid="education-error">
      <div className="education-state-icon"><CircleAlert size={20}/></div><h2>Videos could not be loaded</h2><p>{friendlyError(query.error)}</p>
      <button className="btn btn-outline" onClick={() => query.refetch()} disabled={query.isFetching} data-testid="button-retry-education-list"><RefreshCw size={14}/>{query.isFetching ? 'Loading' : 'Try again'}</button>
    </section> : data ? <>
      <section className={`education-destination ${publishAllowed ? 'destination-ready' : 'destination-paused'}`} data-testid="education-destination">
        <div className="education-destination-icon"><LockKeyhole size={17}/></div>
        <div className="education-destination-copy">
          <span className="eyebrow">PUBLISHING DESTINATION</span>
          <strong>{data.targetLabel || 'Destination not available'}</strong>
          <p>{data.notice || (publishAllowed ? 'Publishing is available. Each video still requires your confirmation.' : 'Publishing is currently unavailable.')}</p>
        </div>
        <span className="education-gate">{publishAllowed ? 'Publishing available' : 'Publishing unavailable'}</span>
      </section>

      <section className="education-composer" aria-labelledby="education-compose-title">
        <div className="education-composer-head">
          <div className="education-step">01</div>
          <div><div className="eyebrow">NEW LESSON</div><h2 id="education-compose-title">Build a video draft</h2><p>Choose an MP4, then add the title and exact caption members will see.</p></div>
        </div>
        <form className="education-form" onSubmit={createAndUpload}>
          <div className="education-file-input">
            <FileVideo2 size={20}/>
            <div className="education-file-copy"><strong>{file ? file.name : 'Choose an MP4 video'}</strong><span>{file ? `${fileSize(file.size)} · Ready to upload` : 'MP4 only · Maximum file size 50 MB'}</span></div>
              <label className="btn btn-outline education-choose" htmlFor="education-video-file" aria-disabled={!videoStorageAvailable} data-testid="button-choose-video"><Upload size={14}/>{file ? 'Change file' : 'Choose file'}</label>
              <input id="education-video-file" className="education-file-native" type="file" accept="video/mp4,.mp4" onChange={chooseFile} disabled={!videoStorageAvailable} data-testid="input-education-video-file"/>
          </div>
          <div className="education-fields">
            <div className="form-field"><label className="form-label" htmlFor="education-title">Lesson title</label><input className="field-input" id="education-title" value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder="For example, Reading a price chart" required data-testid="input-education-title"/><span className="education-count">{title.length}/120</span></div>
            <div className="form-field"><label className="form-label" htmlFor="education-caption">Caption</label><textarea className="reply-area education-caption-input" id="education-caption" value={caption} maxLength={900} onChange={(event) => setCaption(event.target.value)} placeholder="Write the caption exactly as it should appear to members." required data-testid="input-education-caption"/><span className="education-count">{caption.length}/900</span></div>
          </div>
          {formError && <div className="notice notice-error" role="alert" data-testid="education-form-error">{formError}</div>}
          {actionError && <div className="notice notice-error education-action-error" role="alert" data-testid="education-action-error">{actionError}</div>}
          <div className="education-form-footer"><p>Creating a draft uploads the selected file. Publishing is always a separate action.</p><button className="btn btn-primary btn-large" type="submit" disabled={busy || !file || !videoStorageAvailable} data-testid="button-create-education-draft">{createDraft.isPending ? 'Creating draft…' : uploadFile.isPending ? 'Uploading video…' : 'Create draft and upload'}<Upload size={15}/></button></div>
        </form>
      </section>

      <section className="education-library" aria-labelledby="education-library-title">
        <div className="education-library-head"><div><div className="eyebrow">SAVED LESSONS</div><h2 id="education-library-title">Video library</h2><p>Review each item’s status before taking the next step.</p></div><span className="education-total" data-testid="education-video-count">{videos.length} {videos.length === 1 ? 'video' : 'videos'}</span></div>
        {query.isFetching && <div className="education-refreshing" role="status">Updating video statuses…</div>}
        {videos.length === 0 ? <div className="education-empty" data-testid="education-empty"><div className="education-state-icon"><Clapperboard size={20}/></div><h3>No lessons yet</h3><p>Your created drafts and published lessons will appear here.</p></div> : <div className="education-video-list">
          {videos.map((video) => {
            const uploaded = video.status === 'draft';
              const canPublish = videoStorageAvailable && uploaded && publishAllowed && !uploadBlockedIds.includes(video.videoId) && !publishBlockedIds.includes(video.videoId);
             const hasUploadedFile = videoStorageAvailable && video.status !== 'awaiting_upload' && video.status !== 'failed';
            const previewUrl = `/api/portal/education-videos/${encodeURIComponent(video.videoId)}/file`;
            return <article className={`education-video-card ${activeVideoId === video.videoId ? 'is-current' : ''}`} key={video.videoId} data-testid={`education-video-${video.videoId}`}>
              <div className="education-video-main">
                <div className="education-video-title-row"><div><h3>{video.title}</h3><span className="education-file-meta">{video.fileName} · {fileSize(video.byteSize)}</span></div><VideoStatus status={video.status}/></div>
                {hasUploadedFile && <div className="education-preview">
                  <video controls preload="metadata" src={previewUrl} aria-label={`Preview of ${video.title}`} data-testid={`video-preview-${video.videoId}`}/>
                  <div className="education-caption-preview"><span className="eyebrow">CAPTION PREVIEW</span><p data-testid={`video-caption-${video.videoId}`}>{video.caption}</p></div>
                </div>}
                {!hasUploadedFile && <p className="education-status-note">{video.status === 'awaiting_upload' ? 'This draft is waiting for its MP4 file. Resuming uploads the file only; it does not send anything to Telegram.' : 'This item failed. No retry is available from this page.'}</p>}
                {video.status === 'published' && <p className="education-status-note">Published {dateLabel(video.publishedAt)} to {video.targetLabel || data.targetLabel}.</p>}
                {video.status === 'uncertain' && <p className="education-status-note">The final publishing outcome is not confirmed. Do not submit this item again.</p>}
                {video.status === 'blocked' && <p className="education-status-note">This item is blocked and cannot be published.</p>}
                {(video.status === 'queued' || video.status === 'sending') && <p className="education-status-note">Publishing is in progress. Do not submit this item again.</p>}
                {uploaded && <div className="education-upload-meta"><span>Created {dateLabel(video.createdAt)}</span><span>Destination · {video.targetLabel || data.targetLabel}</span></div>}
              </div>
              {canPublish && <div className="education-video-action">
                <div><strong>Ready to publish?</strong><span>Review the video and caption before sending.</span></div>
                <button className="btn btn-primary" onClick={() => publish(video)} disabled={busy} data-testid={`button-publish-video-${video.videoId}`}>{publishVideo.isPending && activeVideoId === video.videoId ? 'Publishing…' : 'Publish lesson'}<Check size={15}/></button>
              </div>}
              {video.status === 'awaiting_upload' && <div className="education-resume">
                <div className="education-resume-heading"><strong>Resume file upload</strong><span>Choose the original MP4. This does not publish to Telegram.</span></div>
                <div className="education-resume-controls">
                  <label className="btn btn-outline education-resume-choose" htmlFor={`resume-video-${video.videoId}`} data-testid={`button-choose-resume-video-${video.videoId}`}><FileVideo2 size={14}/>{resumeFiles[video.videoId]?.name ?? 'Choose MP4'}</label>
                    <input id={`resume-video-${video.videoId}`} className="education-file-native" type="file" accept="video/mp4,.mp4" onChange={(event) => chooseResumeFile(video, event)} disabled={!videoStorageAvailable} data-testid={`input-resume-video-${video.videoId}`}/>
                    <button className="btn btn-primary" onClick={() => resumeUpload(video)} disabled={busy || !videoStorageAvailable || !resumeFiles[video.videoId]} data-testid={`button-resume-upload-${video.videoId}`}>{uploadFile.isPending && activeVideoId === video.videoId ? 'Uploading…' : 'Upload / Resume'}<Upload size={14}/></button>
                </div>
                {resumeErrors[video.videoId] && <p className="education-resume-error" role="alert" data-testid={`resume-upload-error-${video.videoId}`}>{resumeErrors[video.videoId]}</p>}
              </div>}
              {uploaded && !publishAllowed && <div className="education-gated-note" data-testid={`publish-gated-${video.videoId}`}>Publishing is unavailable until the destination and publishing setting are ready.</div>}
            </article>;
          })}
        </div>}
      </section>
      <div className="education-footnote"><LockKeyhole size={14}/><span>This workspace is for the owner. Publishing is handled by the portal service and remains subject to its authorization and destination checks.</span></div>
    </> : null}
  </main>;
}
