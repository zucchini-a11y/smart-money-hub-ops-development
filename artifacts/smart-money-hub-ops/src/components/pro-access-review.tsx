import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  getGetProMemberApplicationQueryKey,
  getListProMemberApplicationsQueryKey,
  useGetProMemberApplication,
  useListProMemberApplications,
  useSubmitProMemberReviewDecision,
} from "@workspace/api-client-react";
import { ArrowLeft, Check, FileImage, RefreshCw, ShieldCheck } from "lucide-react";
import { Link } from "wouter";

type ReviewAction =
  | "approve_registration"
  | "reject_registration"
  | "verify_funding"
  | "reject_funding"
  | "approve"
  | "reject"
  | "request_evidence";

const filters = [
  ["needs_review", "Needs review"],
  ["evidence_requested", "Evidence requested"],
  ["approved", "Approved"],
  ["rejected", "Not approved"],
  ["not_yet_eligible", "Not yet eligible"],
  ["all", "All applications"],
] as const;

function readable(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value?: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString();
}

function latestCommandNeedsReview(status?: string) {
  return status === "queued" || status === "processing" || status === "uncertain";
}

export default function ProAccessReview() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<(typeof filters)[number][0]>("needs_review");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [action, setAction] = useState<ReviewAction | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");
  const [errorText, setErrorText] = useState("");
  const [evidenceError, setEvidenceError] = useState(false);

  const listQuery = useListProMemberApplications(
    { status: filter, limit: 50 },
    { query: {
      queryKey: getListProMemberApplicationsQueryKey({ status: filter, limit: 50 }),
      staleTime: 15_000,
      refetchOnMount: "always",
    } },
  );
  const detailQuery = useGetProMemberApplication(selectedId ?? "", {
    query: {
      queryKey: getGetProMemberApplicationQueryKey(selectedId ?? ""),
      enabled: Boolean(selectedId),
      staleTime: 5_000,
    },
  });
  const submitDecision = useSubmitProMemberReviewDecision();

  const application = detailQuery.data?.application;
  const pendingCommand = latestCommandNeedsReview(detailQuery.data?.latestCommand?.status);
  const currentItems = listQuery.data?.applications ?? [];
  const canApprove = Boolean(application &&
    ["pending_review", "legacy_review"].includes(application.status) &&
    ["approved", "verified"].includes(application.registrationStatus) &&
    application.fundingStatus === "verified");
  const canApproveRegistration = Boolean(application &&
    ["pending_review", "legacy_review"].includes(application.status) &&
    ["pending_review", "unverified"].includes(application.registrationStatus));
  const canRejectRegistration = canApproveRegistration;
  const canVerifyFunding = Boolean(application &&
    ["pending_review", "legacy_review", "information_requested", "approved"].includes(application.status) &&
    application.fundingStatus === "pending_review" && application.hasEvidence);
  const canRejectFunding = Boolean(application &&
    ["pending_review", "legacy_review", "information_requested"].includes(application.status) &&
    application.fundingStatus === "pending_review" && application.hasEvidence);
  const canReject = Boolean(application &&
    !["approved", "rejected", "not_yet_eligible", "revoked"].includes(application.status) &&
    ["approved", "verified"].includes(application.registrationStatus) &&
    application.fundingStatus === "verified");
  const canRequestEvidence = Boolean(application &&
    ["pending_review", "legacy_review", "information_requested", "approved"].includes(application.status) &&
    application.fundingStatus !== "pending_review" &&
    application.fundingStatus !== "evidence_requested" &&
    ["approved", "verified"].includes(application.registrationStatus));

  const refreshAfterSubmit = async (requestId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: getListProMemberApplicationsQueryKey({ status: filter, limit: 50 }) }),
      queryClient.invalidateQueries({ queryKey: getGetProMemberApplicationQueryKey(requestId) }),
    ]);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!application || !action || !reason.trim()) return;
    const labels: Record<ReviewAction, string> = {
      approve_registration: "approve PRO education eligibility only",
      reject_registration: "reject the PRO registration",
      verify_funding: "verify the funded account",
      reject_funding: "reject the funded-account evidence",
      approve: "approve PRO access",
      reject: "not approve this application",
      request_evidence: "request updated funding evidence",
    };
    if (!window.confirm(`Confirm you want to ${labels[action]} for ${application.username || `Telegram user ${application.userId}`}?`)) return;
    setErrorText("");
    setNotice("");
    submitDecision.mutate({
      requestId: application.requestId,
      data: {
        action,
        reason: reason.trim(),
        idempotencyKey: window.crypto.randomUUID(),
        expectedUpdated: application.updated,
      },
    }, {
      onSuccess: async (command) => {
        setNotice(`Decision saved to the isolated review queue. Current status: ${readable(command.status)}.`);
        setAction(null);
        setReason("");
        await refreshAfterSubmit(application.requestId);
      },
      onError: (failure) => {
        const message = failure as { data?: { error?: string }; message?: string };
        setErrorText(message.data?.error ?? message.message ?? "The decision could not be queued. Reload the application and try again.");
      },
    });
  };

  const openApplication = (requestId: string) => {
    setSelectedId(requestId);
    setAction(null);
    setReason("");
    setNotice("");
    setErrorText("");
    setEvidenceError(false);
  };

  return <main className="page pro-review-page" data-testid="pro-access-review">
    <div className="page-heading">
      <div>
        <div className="eyebrow">OWNER TOOLS · DEVELOPMENT ONLY</div>
        <h1>PRO access review</h1>
        <p className="subheading">Review registration and funding evidence separately. Decisions are processed by the isolated test bot.</p>
      </div>
      <Link className="btn btn-outline btn-large" href="/command-center"><ArrowLeft size={15}/>Command center</Link>
    </div>

    <section className="command-scope" aria-label="Review environment">
      <div className="scope-icon"><ShieldCheck size={18}/></div>
      <div><strong>Isolated Development review</strong><p>Production applications, credentials, and channels are not connected to this page.</p></div>
      <span className="readonly-tag">OWNER ONLY</span>
    </section>

    {notice && <div className="notice notice-info" role="status">{notice}</div>}
    {errorText && <div className="notice notice-error" role="alert">{errorText}</div>}

    <section className="section-panel">
      <div className="section-head">
        <div><h2 className="section-title">Applications</h2><p className="section-note">Applicant answers and Telegram file identifiers are not shown in the list.</p></div>
        <div className="form-field" style={{ minWidth: 190 }}>
          <label className="form-label" htmlFor="pro-review-filter">Filter applications</label>
          <select id="pro-review-filter" className="field-select" value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
            {filters.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select>
        </div>
      </div>
      {listQuery.isLoading ? <div className="loading-state">Loading applications…</div>
        : listQuery.isError ? <div className="notice notice-error" role="alert">Applications could not be loaded. <button className="btn btn-quiet" onClick={() => listQuery.refetch()}>Try again</button></div>
          : currentItems.length === 0 ? <div className="empty-state"><strong>No applications in this view</strong><p>Try another filter or check again later.</p></div>
            : <div className="pro-application-list">{currentItems.map((item) => <button
              className={`pro-application-row ${selectedId === item.requestId ? "selected" : ""}`}
              key={item.requestId}
              onClick={() => openApplication(item.requestId)}
              data-testid={`pro-application-${item.requestId}`}
            >
              <span className="pro-applicant"><strong>{item.username ? `@${item.username}` : `Telegram user ${item.userId}`}</strong><small>Updated {formatDate(item.updated)}</small></span>
               <span className="pro-app-status">{readable(item.status)}<small>Registration: {readable(item.registrationStatus)} · Funding: {readable(item.fundingStatus)}</small></span>
              <span className="pro-evidence-state">{item.hasEvidence ? <><FileImage size={15}/>Evidence received</> : "No evidence"}<small>{item.evidenceSubmittedAt ? formatDate(item.evidenceSubmittedAt) : "No submission date"}</small></span>
            </button>)}</div>}
    </section>

    {selectedId && <section className="section-panel pro-review-detail" aria-live="polite">
      <div className="section-head">
        <div><h2 className="section-title">Application details</h2><p className="section-note">Review only the information needed for the PRO decision.</p></div>
        <button className="btn btn-quiet" onClick={() => { setSelectedId(null); setAction(null); }}><ArrowLeft size={14}/>Back to list</button>
      </div>
      {detailQuery.isLoading ? <div className="loading-state">Loading application details…</div>
        : detailQuery.isError || !application ? <div className="notice notice-error" role="alert">This application is unavailable or may have changed. <button className="btn btn-quiet" onClick={() => detailQuery.refetch()}>Reload</button></div>
          : <>
            <div className="pro-detail-grid">
              <div><span>Applicant</span><strong>{application.username ? `@${application.username}` : "No Telegram username"}</strong></div>
              <div><span>Telegram account</span><strong>{application.userId}</strong></div>
              <div><span>Application status</span><strong>{readable(application.status)}</strong></div>
              <div><span>PRO registration</span><strong>{readable(application.registrationStatus)}</strong></div>
              <div><span>Funded-account verification</span><strong>{readable(application.fundingStatus)}</strong></div>
              <div><span>PRO education eligibility</span><strong>{readable(application.educationEligibility)}</strong></div>
              <div><span>PRO Signals access</span><strong>{readable(application.channelAccessStatus)}</strong></div>
              <div><span>Evidence submitted</span><strong>{formatDate(application.evidenceSubmittedAt)}</strong></div>
              <div><span>Application opened</span><strong>{formatDate(application.created)}</strong></div>
              <div><span>Last updated</span><strong>{formatDate(application.updated)}</strong></div>
            </div>

            {application.hasEvidence && <div className="pro-evidence-panel">
              <div className="section-head"><div><h3>Private funding evidence</h3><p className="section-note">Loaded through the authenticated Development portal; it is not cached or sent to a channel.</p></div><span className="readonly-tag">PRIVATE</span></div>
              {evidenceError ? <div className="notice notice-error" role="alert">The evidence could not be loaded. Check the private test bot configuration and try again.</div>
                : application.evidenceKind === "application/pdf"
                  ? <iframe title="Private funding evidence" src={`/api/portal/pro-applications/${encodeURIComponent(application.requestId)}/evidence`} className="pro-evidence-frame" onError={() => setEvidenceError(true)}/>
                  : <img alt="Private funding evidence submitted by the applicant" className="pro-evidence-image" src={`/api/portal/pro-applications/${encodeURIComponent(application.requestId)}/evidence`} onError={() => setEvidenceError(true)}/>}
            </div>}

            {pendingCommand && <div className={`notice ${detailQuery.data?.latestCommand?.status === "uncertain" ? "notice-error" : "notice-info"}`} role="status">
              {detailQuery.data?.latestCommand?.status === "uncertain"
                ? "The last action has an uncertain delivery result. Check the member chat and existing invite operation before taking another action. It will not be retried automatically."
                : `A ${readable(detailQuery.data?.latestCommand?.action ?? "review")} action is ${readable(detailQuery.data?.latestCommand?.status ?? "processing")}. Refresh the application to check its result.`}
              <button className="btn btn-quiet" onClick={() => detailQuery.refetch()}><RefreshCw size={14}/>Refresh status</button>
            </div>}

            <div className="pro-review-actions">
              <h3>Review decision</h3>
              <p className="section-note">Registration approval unlocks education eligibility only. The PRO Signals invite is issued only after registration approval and separate funded-account verification.</p>
              <div className="pro-action-buttons">
                <button className="btn btn-primary btn-large" disabled={!canApproveRegistration || pendingCommand} onClick={() => { setAction("approve_registration"); setReason(""); }}><Check size={15}/>Approve registration</button>
                <button className="btn btn-outline btn-large" disabled={!canRejectRegistration || pendingCommand} onClick={() => { setAction("reject_registration"); setReason(""); }}>Reject registration</button>
                <button className="btn btn-primary btn-large" disabled={!canVerifyFunding || pendingCommand} onClick={() => { setAction("verify_funding"); setReason(""); }}><ShieldCheck size={15}/>Verify funded account</button>
                <button className="btn btn-outline btn-large" disabled={!canRejectFunding || pendingCommand} onClick={() => { setAction("reject_funding"); setReason(""); }}>Reject funding evidence</button>
                <button className="btn btn-outline btn-large" disabled={!canApprove || pendingCommand} onClick={() => { setAction("approve"); setReason(""); }}><Check size={15}/>Review PRO Signals access</button>
                <button className="btn btn-outline btn-large" disabled={!canRequestEvidence || pendingCommand} onClick={() => { setAction("request_evidence"); setReason(""); }}><FileImage size={15}/>Request updated evidence</button>
                <button className="btn btn-outline btn-large" disabled={!canReject || pendingCommand} onClick={() => { setAction("reject"); setReason(""); }}>Do not approve</button>
              </div>
              {pendingCommand && <p className="section-note">A review action is already queued or needs manual review.</p>}
            </div>

            {action && <form className="pro-decision-form" onSubmit={submit}>
              <div className="eyebrow">CONFIRM OWNER DECISION</div>
              <h3>{action === "approve_registration" ? "Approve registration and education eligibility?" : action === "reject_registration" ? "Reject PRO registration?" : action === "verify_funding" ? "Verify the funded account?" : action === "reject_funding" ? "Reject funded-account evidence?" : action === "approve" ? "Review PRO Signals access?" : action === "reject" ? "Do not approve this application?" : "Request updated funding evidence?"}</h3>
              {action === "approve_registration" && <p>This unlocks education eligibility only. It does not create or send a PRO Signals invite.</p>}
              {action === "reject_registration" && <p>This blocks new PRO education eligibility. Existing channel membership is not automatically removed.</p>}
              {action === "verify_funding" && <p>If registration is already approved, the isolated bot will use the existing PRO Signals invite workflow. Otherwise, no channel access is granted yet.</p>}
              {action === "reject_funding" && <p>PRO Signals access remains locked. Any approved education entitlement remains separate.</p>}
              {action === "approve" && <p>Use this only for a legacy or recovery case after both requirements are already verified. The isolated test bot will use its existing invite workflow.</p>}
              {action === "reject" && <p>The member will receive a private status update with alternative access options. Other destination access will not be changed.</p>}
              {action === "request_evidence" && <p>The member will receive a private button to submit updated evidence. Existing approved access, if any, will remain unchanged during review.</p>}
              <label className="form-label" htmlFor="pro-review-reason">Reason or message to the applicant</label>
              <textarea id="pro-review-reason" className="field-textarea" required minLength={1} maxLength={1200} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Write a clear, respectful explanation."/>
              <div className="modal-actions">
                <button type="button" className="btn btn-outline" onClick={() => setAction(null)} disabled={submitDecision.isPending}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitDecision.isPending || !reason.trim()}>{submitDecision.isPending ? "Saving…" : "Confirm and save decision"}</button>
              </div>
            </form>}

            <div className="pro-review-history">
              <h3>Review history</h3>
              {!detailQuery.data?.history.length ? <p className="section-note">No review history is recorded yet.</p>
                : <ol>{detailQuery.data.history.map((event) => <li key={`${event.eventId}-${event.created}`}>
                  <div><strong>{readable(event.action)}</strong><span>{event.actor} · {formatDate(event.created)}</span></div>
                  {event.reason && <p>{event.reason}</p>}
                  {event.status !== "recorded" && <small>{readable(event.status)} · delivery {readable(event.deliveryStatus)}</small>}
                </li>)}</ol>}
            </div>
          </>}
    </section>}
  </main>;
}
