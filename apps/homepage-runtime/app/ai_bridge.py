from __future__ import annotations

from typing import Any

import httpx


class PersonalAIError(RuntimeError):
    pass


class CreatorAIError(PersonalAIError):
    pass


class FreelancerAIError(PersonalAIError):
    pass


class BusinessAIError(RuntimeError):
    pass


def _detail(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return fallback

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
    return fallback


def _generate_personal(
    *,
    enabled: bool,
    url: str,
    token: str,
    timeout_seconds: float,
    endpoint: str,
    need: str,
    choice: str,
    revision: str,
    current_plan: dict[str, Any] | None,
    error_type: type[PersonalAIError],
    assistant_name: str,
    required_list: str,
) -> dict[str, Any]:
    if not enabled:
        raise error_type(f"{assistant_name} belum diaktifkan.")

    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise error_type(
            f"Token internal {assistant_name} belum tersedia."
        )

    body: dict[str, Any] = {
        "need": need,
        "choice": choice,
        "revision": revision,
    }
    if current_plan:
        body["current_plan"] = current_plan

    try:
        response = httpx.post(
            f"{url.rstrip('/')}{endpoint}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {normalized_token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
        )
    except httpx.RequestError as exc:
        raise error_type(
            f"Mesin {assistant_name} sedang tidak dapat dihubungi. "
            "Proyek tetap tersimpan dan dapat dicoba kembali."
        ) from exc

    if response.status_code >= 400:
        raise error_type(
            _detail(
                response,
                f"Mesin {assistant_name} belum dapat membuat rancangan.",
            )
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise error_type(
            f"Format hasil {assistant_name} tidak dapat dibaca."
        ) from exc

    if not isinstance(payload, dict):
        raise error_type(f"Hasil {assistant_name} tidak valid.")

    plan = payload.get("plan")
    meta = payload.get("meta")
    if not isinstance(plan, dict) or not isinstance(meta, dict):
        raise error_type(
            f"Struktur hasil {assistant_name} tidak lengkap."
        )

    required_value = plan.get(required_list)
    if not isinstance(required_value, list) or not required_value:
        raise error_type(
            f"{assistant_name} belum menghasilkan {required_list}."
        )

    return {"plan": plan, "meta": meta}


def generate_creator_plan(
    settings: Any,
    *,
    need: str,
    choice: str,
    revision: str = "",
    current_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _generate_personal(
        enabled=settings.creator_ai_enabled,
        url=settings.creator_ai_url,
        token=settings.creator_ai_token,
        timeout_seconds=settings.creator_ai_timeout_seconds,
        endpoint="/v1/creator/generate",
        need=need,
        choice=choice,
        revision=revision,
        current_plan=current_plan,
        error_type=CreatorAIError,
        assistant_name="Creator AI",
        required_list="ideas",
    )


def generate_freelancer_plan(
    settings: Any,
    *,
    need: str,
    choice: str,
    revision: str = "",
    current_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _generate_personal(
        enabled=settings.freelancer_ai_enabled,
        url=settings.freelancer_ai_url,
        token=settings.freelancer_ai_token,
        timeout_seconds=settings.freelancer_ai_timeout_seconds,
        endpoint="/v1/freelancer/generate",
        need=need,
        choice=choice,
        revision=revision,
        current_plan=current_plan,
        error_type=FreelancerAIError,
        assistant_name="Freelancer AI",
        required_list="milestones",
    )


def simulate_whatsapp_admin(
    settings: Any,
    *,
    business_context: str,
    customer_message: str,
    customer_name: str = "",
    previous_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not settings.business_ai_enabled:
        raise BusinessAIError("WhatsApp AI Admin belum diaktifkan.")

    token = str(settings.business_ai_token or "").strip()
    if not token:
        raise BusinessAIError(
            "Token internal WhatsApp AI Admin belum tersedia."
        )

    body = {
        "business_context": business_context,
        "customer_message": customer_message,
        "customer_name": customer_name,
        "previous_messages": (previous_messages or [])[-8:],
    }

    try:
        response = httpx.post(
            (
                f"{settings.business_ai_url.rstrip('/')}"
                "/v1/business/whatsapp-admin/simulate"
            ),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=httpx.Timeout(
                settings.business_ai_timeout_seconds,
                connect=5.0,
            ),
        )
    except httpx.RequestError as exc:
        raise BusinessAIError(
            "Mesin WhatsApp AI Admin sedang tidak dapat dihubungi. "
            "Data bisnis dan pesan simulasi tetap aman."
        ) from exc

    if response.status_code >= 400:
        raise BusinessAIError(
            _detail(
                response,
                "WhatsApp AI Admin belum dapat menganalisis pesan.",
            )
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise BusinessAIError(
            "Format hasil WhatsApp AI Admin tidak dapat dibaca."
        ) from exc

    analysis = payload.get("analysis")
    meta = payload.get("meta")
    if not isinstance(analysis, dict) or not isinstance(meta, dict):
        raise BusinessAIError(
            "Struktur hasil WhatsApp AI Admin tidak lengkap."
        )

    if not str(analysis.get("draft_reply", "")).strip():
        raise BusinessAIError(
            "WhatsApp AI Admin belum menghasilkan draft balasan."
        )

    return {"analysis": analysis, "meta": meta}



def assist_business_lead(
    settings: Any,
    *,
    business_context: str,
    profile: dict[str, Any],
    lead: dict[str, Any],
) -> dict[str, Any]:
    if not settings.business_operations_enabled:
        raise BusinessAIError(
            "Business Operations AI belum diaktifkan."
        )

    token = str(settings.business_ai_token or "").strip()
    if not token:
        raise BusinessAIError(
            "Token internal Business Operations AI belum tersedia."
        )

    body = {
        "business_context": business_context,
        "profile": profile,
        "lead": lead,
    }

    try:
        response = httpx.post(
            (
                f"{settings.business_ai_url.rstrip('/')}"
                "/v1/business/operations/assist-lead"
            ),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=httpx.Timeout(
                settings.business_ai_timeout_seconds,
                connect=5.0,
            ),
        )
    except httpx.RequestError as exc:
        raise BusinessAIError(
            "Business Operations AI sedang tidak dapat dihubungi. "
            "Data prospek tetap tersimpan."
        ) from exc

    if response.status_code >= 400:
        raise BusinessAIError(
            _detail(
                response,
                "Business Operations AI belum dapat menganalisis prospek.",
            )
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise BusinessAIError(
            "Format hasil Business Operations AI tidak dapat dibaca."
        ) from exc

    assist = payload.get("assist")
    meta = payload.get("meta")
    if not isinstance(assist, dict) or not isinstance(meta, dict):
        raise BusinessAIError(
            "Struktur hasil Business Operations AI tidak lengkap."
        )

    if not str(assist.get("follow_up_draft", "")).strip():
        raise BusinessAIError(
            "Business Operations AI belum menghasilkan draft follow-up."
        )

    return {"assist": assist, "meta": meta}
