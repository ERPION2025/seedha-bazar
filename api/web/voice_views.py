"""Speak to Seedha Bazar: record with the microphone (after a clear yes), turn speech into text in 12 Indian languages,
and see and get told about content on the topics you talk about most."""
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import audit
from engagement import bhashini, voice
from engagement.models import VoiceConsent, VoiceNote

from .helpers import ok
from .market_views import base_for
from .voice_strings import LANG_TAG

MAX_AUDIO = 3 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "video/webm"}


def page(request):
    u = request.user
    if not u.is_authenticated:
        return redirect("/login/?next=/voice/")
    consent = VoiceConsent.objects.filter(user=u).first()
    ctx = {"consent": consent, "languages": voice.LANGUAGES, "default_lang": LANG_TAG.get(request.lang, "hi-IN"), "base_tpl": base_for(u),
           "server_stt": bhashini.configured()}
    if consent:
        ctx["notes"] = VoiceNote.objects.filter(user=u)[:20]
        ctx["fy"] = voice.for_you(u, request.lang)
    return render(request, "web/voice.html", ctx)


@require_POST
def agree(request):
    if not request.user.is_authenticated:
        raise Http404
    VoiceConsent.objects.update_or_create(user=request.user, defaults={"keep_audio": request.POST.get("keep_audio") == "1", "given_at": timezone.now()})
    audit.log("voice_consent", actor=request.user, target=request.user, request=request, keep_audio=request.POST.get("keep_audio") == "1")
    return redirect("/voice/")


@require_POST
def withdraw(request):
    if not request.user.is_authenticated:
        raise Http404
    for v in VoiceNote.objects.filter(user=request.user):
        if v.audio:
            v.audio.delete(save=False)
    VoiceNote.objects.filter(user=request.user).delete()
    VoiceConsent.objects.filter(user=request.user).delete()
    audit.log("voice_withdrawn", actor=request.user, target=request.user, request=request)
    ok(request, "Your voice notes are deleted and the microphone permission is withdrawn here. You can also block the microphone in your browser settings.")
    return redirect("/voice/")


@require_POST
def save(request):
    u = request.user
    if not u.is_authenticated:
        return JsonResponse({"error": "sign_in"}, status=401)
    consent = VoiceConsent.objects.filter(user=u).first()
    if consent is None:
        return JsonResponse({"error": "consent"}, status=403)
    lang = request.POST.get("language", "hi-IN")
    lang = lang if lang in voice.CODES else "hi-IN"
    text = (request.POST.get("text") or "").strip()[:4000]
    audio = request.FILES.get("audio")
    if audio and ((audio.content_type or "").split(";")[0] not in AUDIO_TYPES or audio.size > MAX_AUDIO):
        audio = None
    source = "phone"
    if not text and audio is not None and bhashini.configured():
        text = bhashini.speech_to_text(audio.read(), lang)
        audio.seek(0)
        source = "bhashini"
    if not text and audio is None:
        return JsonResponse({"error": "empty"}, status=400)
    text_en = bhashini.translate_to_en(text, lang) if lang.split("-")[0] not in ("hi", "mr", "en") else ""
    topics, crops = voice.analyse(text, text_en)
    v = VoiceNote.objects.create(user=u, language=lang, text=text, text_en=text_en, topics=topics, crops=crops, source=source)
    if audio is not None and consent.keep_audio:
        v.audio.save("voice.webm", audio, save=True)
    return JsonResponse({"id": v.pk, "text": text, "topics": topics, "crops": crops})


@require_POST
def delete(request, pk):
    v = VoiceNote.objects.filter(pk=pk, user=request.user).first() if request.user.is_authenticated else None
    if v is None:
        raise Http404
    if v.audio:
        v.audio.delete(save=False)
    v.delete()
    return redirect("/voice/")


@require_POST
def to_expert(request, pk):
    """Send what was said to the district's KVK as a problem."""
    v = VoiceNote.objects.filter(pk=pk, user=request.user).first() if request.user.is_authenticated else None
    if v is None or not v.text:
        raise Http404
    from accounts.errors import ApiError
    from issues import services as issue_services
    category = "pest" if "advisory" in v.topics else "weather" if "weather" in v.topics else "market" if "price" in v.topics else "other"
    try:
        issue = issue_services.raise_issue(request.user, {"description": v.text, "category": category, "crop": (v.crops or [""])[0], "via_voice": True}, request)
    except ApiError:
        return redirect("/help/")
    return redirect(f"/help/{issue.pk}/")
