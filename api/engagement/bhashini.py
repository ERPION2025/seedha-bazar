"""Optional: Bhashini (Government of India's free language platform) for speech-to-text and translation on the server,
in 22 Indian languages. Register at bhashini.gov.in, then set BHASHINI_USER_ID and BHASHINI_API_KEY.

Without it, speech is turned into text by the phone's browser, and topics are found in Hindi, Marathi and English text.
Every call fails safe: on any error the caller simply gets nothing back.
"""
import base64
import json
import logging
import urllib.request

from django.conf import settings

from config.netutil import ssl_context

log = logging.getLogger("seedha.bhashini")
CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
PIPELINE_ID = "64392f96daac500b55c543cd"  # MeitY's public pipeline


def configured() -> bool:
    return bool(settings.BHASHINI_USER_ID and settings.BHASHINI_API_KEY)


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:  # noqa: S310 - fixed government hosts
        return json.loads(r.read())


def _run(task: str, lang_cfg: dict, input_data: dict) -> dict | None:
    if not configured():
        return None
    try:
        cfg = _post(CONFIG_URL, {"pipelineTasks": [{"taskType": task, "config": {"language": lang_cfg}}], "pipelineRequestConfig": {"pipelineId": PIPELINE_ID}},
                    {"userID": settings.BHASHINI_USER_ID, "ulcaApiKey": settings.BHASHINI_API_KEY})
        ep = cfg["pipelineInferenceAPIEndPoint"]
        service = cfg["pipelineResponseConfig"][0]["config"][0]["serviceId"]
        auth = ep["inferenceApiKey"]
        return _post(ep["callbackUrl"], {"pipelineTasks": [{"taskType": task, "config": {"language": lang_cfg, "serviceId": service}}], "inputData": input_data},
                     {auth["name"]: auth["value"]})
    except Exception as e:  # noqa: BLE001
        log.warning("bhashini %s failed: %s", task, e)
        return None


def translate_to_en(text: str, lang: str) -> str:
    src = lang.split("-")[0]
    if src == "en" or not text:
        return text
    out = _run("translation", {"sourceLanguage": src, "targetLanguage": "en"}, {"input": [{"source": text[:2000]}]})
    try:
        return out["pipelineResponse"][0]["output"][0]["target"]
    except (TypeError, KeyError, IndexError):
        return ""


def speech_to_text(audio_bytes: bytes, lang: str) -> str:
    out = _run("asr", {"sourceLanguage": lang.split("-")[0]}, {"audio": [{"audioContent": base64.b64encode(audio_bytes).decode()}]})
    try:
        return out["pipelineResponse"][0]["output"][0]["source"]
    except (TypeError, KeyError, IndexError):
        return ""
