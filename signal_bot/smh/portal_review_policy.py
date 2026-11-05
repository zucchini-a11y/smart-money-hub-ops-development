"""Shared decision-state validation for the isolated portal-to-bot review queue."""

def _has_submitted_evidence(application):
    try:
        return bool(application["evidence_file_id"])
    except (KeyError, IndexError, TypeError):
        return False


def may_process_review_action(application, action):
    status = application["status"]
    registration = application["registration_status"]
    funding = application["funding_status"]
    registration_approved = registration in ("approved", "verified")
    reviewable = status in ("pending_review", "legacy_review", "information_requested")
    if action == "approve_registration":
        return (
            status in ("pending_review", "legacy_review")
            and registration in ("pending_review", "unverified")
        )
    if action == "reject_registration":
        return (
            status in ("pending_review", "legacy_review")
            and registration in ("pending_review", "unverified")
        )
    if action == "verify_funding":
        return status in (
            "pending_review", "legacy_review", "information_requested", "approved"
        ) and funding == "pending_review" and _has_submitted_evidence(application)
    if action == "reject_funding":
        return (
            reviewable and status != "approved" and funding == "pending_review"
            and _has_submitted_evidence(application)
        )
    if action == "approve":
        return (
            status in ("pending_review", "legacy_review")
            and registration_approved
            and funding == "verified"
        )
    if action == "reject":
        return (
            status not in ("approved", "rejected", "not_yet_eligible", "revoked")
            and registration != "pending_review"
            and funding != "pending_review"
        )
    if action == "request_evidence":
        if status not in ("pending_review", "legacy_review", "information_requested", "approved"):
            return False
        if funding in ("pending_review", "evidence_requested"):
            return False
        return status != "approved" or registration_approved
    return False
