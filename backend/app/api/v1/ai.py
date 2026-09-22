"""Phase 8 — AI explanation & vendor reporting endpoints.

All routes are read-only or additive: they never mutate analysis data, they
only add an explanation/report layer on top of the deterministic results.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.rbac import require_permission
from app.services.audit_service import audit_service
from app.ai.explanation import explanation_service
from app.schemas.ai import AIDigestOut, AIExplanationOut, VendorReportOut
from app.services.report_service import build_pdf, build_xlsx, vendor_report

router = APIRouter(
    prefix="/transactions", tags=["ai-reporting"], dependencies=[Depends(get_current_user)]
)


@router.get("/{txn_id}/ai-digest", response_model=AIDigestOut)
def get_ai_digest(txn_id: str, session: Session = Depends(get_db)) -> AIDigestOut:
    """The structured AI input (spec §1) — never raw log files, always bounded."""
    txn = explanation_service.get_transaction(session, txn_id)
    digest = explanation_service.build_digest(session, txn)
    return AIDigestOut.model_validate(digest)


@router.get("/{txn_id}/ai-explanation", response_model=AIExplanationOut)
def get_ai_explanation(txn_id: str, session: Session = Depends(get_db)) -> AIExplanationOut:
    """Latest stored explanation, or 404 if none was generated yet."""
    txn = explanation_service.get_transaction(session, txn_id)
    stored = explanation_service.latest(session, txn)
    if stored is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(
            "No AI explanation generated yet — POST to this endpoint to create one."
        )
    return AIExplanationOut.model_validate(stored)


@router.post(
    "/{txn_id}/ai-explanation",
    response_model=AIExplanationOut,
    status_code=201,
    dependencies=[Depends(require_permission("analysis:run"))],
)
def generate_ai_explanation(txn_id: str, session: Session = Depends(get_db)) -> AIExplanationOut:
    """Generate a new explanation (spec §2), validate it (spec §3) and store it."""
    txn = explanation_service.get_transaction(session, txn_id)
    out = AIExplanationOut.model_validate(explanation_service.generate(session, txn))
    audit_service.record(
        session,
        action="analysis.run",
        entity_type="transaction",
        entity_id=txn.transaction_id,
        detail={"kind": "ai_explanation"},
    )
    session.commit()
    return out


@router.get(
    "/{txn_id}/vendor-report",
    response_model=VendorReportOut,
    dependencies=[Depends(require_permission("reports:generate"))],
)
def get_vendor_report(txn_id: str, session: Session = Depends(get_db)) -> VendorReportOut:
    """Full vendor escalation report (spec §4) — generates the explanation if missing."""
    txn = explanation_service.get_transaction(session, txn_id)
    return VendorReportOut.model_validate(vendor_report(session, txn))


@router.get(
    "/{txn_id}/report.pdf",
    dependencies=[Depends(require_permission("reports:generate"))],
)
def export_report_pdf(txn_id: str, session: Session = Depends(get_db)) -> Response:
    """Professional PDF vendor report (spec §5)."""
    txn = explanation_service.get_transaction(session, txn_id)
    report = vendor_report(session, txn)
    pdf = build_pdf(report)
    audit_service.record(
        session,
        action="report.generated",
        entity_type="transaction",
        entity_id=txn.transaction_id,
        detail={"format": "pdf"},
    )
    session.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="vendor_report_{txn.transaction_id}.pdf"'
        },
    )


@router.get(
    "/{txn_id}/report.xlsx",
    dependencies=[Depends(require_permission("reports:generate"))],
)
def export_report_xlsx(txn_id: str, session: Session = Depends(get_db)) -> Response:
    """Structured Excel workbook (spec §6)."""
    txn = explanation_service.get_transaction(session, txn_id)
    report = vendor_report(session, txn)
    xlsx = build_xlsx(report)
    audit_service.record(
        session,
        action="report.generated",
        entity_type="transaction",
        entity_id=txn.transaction_id,
        detail={"format": "xlsx"},
    )
    session.commit()
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="vendor_report_{txn.transaction_id}.xlsx"'
        },
    )
