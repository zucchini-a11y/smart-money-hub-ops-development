import { useEffect, useState, type ChangeEvent } from 'react';
import { ArrowLeft, Clapperboard, Film, LockKeyhole, Play, RefreshCw, Upload, Video } from 'lucide-react';
import { Link } from 'wouter';
import './member-course-videos.css';

const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
const apiBase = `${basePath}/api`;
const maxUploadBytes = 262_144_000;

type MemberVideo = {
  videoId: string;
  title: string;
  description: string;
  byteSize: number;
  publishedAt: string | null;
};

type OwnerVideo = MemberVideo & {
  fileName: string;
  status: 'awaiting_upload' | 'draft' | 'published';
  createdAt: string;
};

type OwnerVideoList = {
  storageAvailable: boolean;
  maxUploadBytes: number;
  videos: OwnerVideo[];
};

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: 'include',
    cache: 'no-store',
    ...init,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' ? body.error : 'The video request could not be completed.');
  }
  return body as T;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1_000_000) return `${Math.max(1, Math.round(bytes / 1_000))} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function MemberCourseVideoLibrary() {
  const [videos, setVideos] = useState<MemberVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void apiJson<{ videos: MemberVideo[] }>('/member/videos')
      .then((result) => { if (active) setVideos(result.videos); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Video lessons could not be loaded.');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);

  return (
    <main className="mcv-page" data-testid="member-video-library">
      <div className="mcv-shell">
        <header className="mcv-header">
          <Link className="mcv-brand" href="/member/dashboard"><span className="mcv-mark"><Video size={17}/></span><span><strong>VAYDA</strong><small>SMART MONEY HUB</small></span></Link>
          <Link className="mcv-back" href="/member/dashboard"><ArrowLeft size={15}/> Workspace</Link>
        </header>
        <section className="mcv-hero">
          <span className="mcv-kicker"><Clapperboard size={14}/> MEMBER LEARNING</span>
          <h1>Video lessons</h1>
          <p>Watch lessons published for Smart Money Hub members. Your account must be signed in to view or play a video.</p>
        </section>
        {loading ? (
          <div className="mcv-state" role="status">Loading published lessons…</div>
        ) : error ? (
          <div className="mcv-state mcv-error" role="alert"><p>{error}</p><button type="button" onClick={() => setAttempt((value) => value + 1)}><RefreshCw size={14}/> Try again</button></div>
        ) : videos.length === 0 ? (
          <div className="mcv-state mcv-empty" data-testid="member-videos-empty"><Film size={24}/><strong>No video lessons published yet.</strong><span>New lessons will appear here after the Owner publishes them.</span></div>
        ) : (
          <section className="mcv-grid" aria-label="Published video lessons">
            {videos.map((video) => (
              <article className="mcv-card" key={video.videoId} data-testid={`member-video-${video.videoId}`}>
                <video
                  className="mcv-player"
                  controls
                  playsInline
                  preload="metadata"
                  src={`${apiBase}/member/videos/${encodeURIComponent(video.videoId)}/file`}
                  aria-label={`Play ${video.title}`}
                />
                <div className="mcv-card-body">
                  <span className="mcv-card-kicker"><Play size={12}/> VIDEO LESSON</span>
                  <h2>{video.title}</h2>
                  {video.description && <p>{video.description}</p>}
                  <small>{formatFileSize(video.byteSize)} · Member access</small>
                </div>
              </article>
            ))}
          </section>
        )}
        <footer className="mcv-footer"><span><LockKeyhole size={13}/> Private member access</span><span>Education only. Trading involves risk.</span></footer>
      </div>
    </main>
  );
}

export function OwnerMemberCourseVideos() {
  const [data, setData] = useState<OwnerVideoList | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [resumeFiles, setResumeFiles] = useState<Record<string, File>>({});
  const [busyId, setBusyId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function loadVideos() {
    setLoading(true);
    try {
      setData(await apiJson<OwnerVideoList>('/portal/member-course-videos'));
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Member video lessons could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadVideos(); }, []);

  function readFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setError('');
  }

  async function uploadBytes(videoId: string, videoFile: File) {
    if (videoFile.size > maxUploadBytes) throw new Error('Choose an MP4 file no larger than 250 MB.');
    const response = await fetch(`${apiBase}/portal/member-course-videos/${encodeURIComponent(videoId)}/file`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'video/mp4' },
      body: videoFile,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.error === 'string' ? body.error : 'The video upload did not complete.');
  }

  async function createDraftAndUpload() {
    if (!file || !title.trim()) {
      setError('Add a title and select an MP4 video first.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.mp4') || file.size > maxUploadBytes) {
      setError('Choose an MP4 file no larger than 250 MB.');
      return;
    }
    setBusyId('new');
    setError('');
    setNotice('');
    try {
      const draft = await apiJson<OwnerVideo>('/portal/member-course-videos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), description: description.trim(), fileName: file.name, byteSize: file.size }),
      });
      await uploadBytes(draft.videoId, file);
      setTitle('');
      setDescription('');
      setFile(null);
      setNotice('Video uploaded as a draft. Preview it, then publish it for members.');
      await loadVideos();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The video could not be uploaded.');
      await loadVideos();
    } finally {
      setBusyId('');
    }
  }

  async function resumeUpload(video: OwnerVideo) {
    const selectedFile = resumeFiles[video.videoId];
    if (!selectedFile) return;
    if (selectedFile.size !== video.byteSize || !selectedFile.name.toLowerCase().endsWith('.mp4')) {
      setError('Select the original MP4 file with the same size as this draft.');
      return;
    }
    setBusyId(video.videoId);
    setError('');
    try {
      await uploadBytes(video.videoId, selectedFile);
      setResumeFiles((current) => { const next = { ...current }; delete next[video.videoId]; return next; });
      setNotice('Draft video uploaded. Preview it before publishing.');
      await loadVideos();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The upload could not be resumed.');
    } finally {
      setBusyId('');
    }
  }

  async function setPublished(video: OwnerVideo, publish: boolean) {
    setBusyId(video.videoId);
    setError('');
    setNotice('');
    try {
      await apiJson(`/portal/member-course-videos/${encodeURIComponent(video.videoId)}/${publish ? 'publish' : 'unpublish'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      setNotice(publish ? 'Published to authenticated member accounts.' : 'Unpublished. Members can no longer stream this video.');
      await loadVideos();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The publishing action could not be completed.');
    } finally {
      setBusyId('');
    }
  }

  return (
    <main className="mcv-owner-page" data-testid="owner-member-videos">
      <header className="mcv-owner-heading"><div><span className="mcv-kicker"><Clapperboard size={14}/> OWNER · MEMBER ACADEMY</span><h1>Member video lessons</h1><p>Upload and review videos for the signed-in member library. This does not post to Telegram.</p></div><Link className="mcv-back" href="/command-center"><ArrowLeft size={15}/> Command center</Link></header>
      <section className="mcv-owner-grid">
        <form className="mcv-upload-panel" onSubmit={(event) => { event.preventDefault(); void createDraftAndUpload(); }}>
          <span className="mcv-card-kicker"><Upload size={13}/> NEW MEMBER VIDEO</span>
          <label>Lesson title<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={140} required /></label>
          <label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={3000} rows={4} /></label>
          <label>MP4 video<input type="file" accept="video/mp4,.mp4" onChange={readFile} required /></label>
          <small>{file ? `${file.name} · ${formatFileSize(file.size)}` : 'MP4 only · maximum 250 MB'}</small>
          <button className="mcv-primary" type="submit" disabled={busyId === 'new' || !data?.storageAvailable || !file}>
            <Upload size={15}/>{busyId === 'new' ? 'Uploading…' : 'Upload as draft'}
          </button>
          {!data?.storageAvailable && <p className="mcv-note">Persistent storage is not configured. Set MEMBER_VIDEO_STORAGE_DIR on the API host before uploading.</p>}
          <p className="mcv-note">Only Owner accounts can upload. Publishing exposes the lesson to signed-in members, not to visitors or PRO Signals.</p>
        </form>
        <section className="mcv-owner-list" aria-label="Member video drafts and published lessons">
          <div className="mcv-owner-list-head"><div><span className="mcv-card-kicker">CONTENT LIBRARY</span><h2>{data?.videos.length ?? 0} videos</h2></div><button type="button" onClick={() => void loadVideos()} disabled={loading}><RefreshCw size={14}/> Refresh</button></div>
          {loading ? <p className="mcv-owner-empty" role="status">Loading video library…</p>
            : !data?.videos.length ? <p className="mcv-owner-empty">No member video lessons have been uploaded.</p>
              : <div className="mcv-owner-items">{data.videos.map((video) => (
                <article className="mcv-owner-item" key={video.videoId} data-testid={`owner-member-video-${video.videoId}`}>
                  <div className="mcv-owner-item-head"><div><strong>{video.title}</strong><span>{formatFileSize(video.byteSize)} · {video.fileName}</span></div><span className={`mcv-status is-${video.status}`}>{video.status.replace('_', ' ')}</span></div>
                  {video.description && <p>{video.description}</p>}
                  {video.status !== 'awaiting_upload' && <video controls playsInline preload="metadata" src={`${apiBase}/portal/member-course-videos/${encodeURIComponent(video.videoId)}/file`} aria-label={`Preview ${video.title}`} />}
                  {video.status === 'awaiting_upload' ? (
                    <div className="mcv-resume"><input type="file" accept="video/mp4,.mp4" aria-label={`Select original MP4 for ${video.title}`} onChange={(event) => setResumeFiles((current) => ({ ...current, [video.videoId]: event.target.files?.[0] ?? undefined } as Record<string, File>))} /><button type="button" onClick={() => void resumeUpload(video)} disabled={busyId === video.videoId || !resumeFiles[video.videoId]}>{busyId === video.videoId ? 'Uploading…' : 'Resume upload'}</button></div>
                  ) : <div className="mcv-owner-actions">
                    <button type="button" onClick={() => void setPublished(video, video.status !== 'published')} disabled={busyId === video.videoId}>{video.status === 'published' ? 'Unpublish' : 'Publish for members'}</button>
                  </div>}
                </article>
              ))}</div>}
        </section>
      </section>
      {(error || notice) && <div className={`mcv-feedback ${error ? 'is-error' : ''}`} role={error ? 'alert' : 'status'}>{error || notice}</div>}
    </main>
  );
}
