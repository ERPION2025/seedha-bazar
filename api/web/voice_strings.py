"""Every sentence the read-aloud helper can say or show. Translated on the server and handed to every page as JSON."""
from .i18n import tr

LANG_TAG = {"hi": "hi-IN", "mr": "mr-IN", "en": "en-IN"}

VOICE_STRINGS = [
    "Listen", "Listen to this screen", "Read this screen", "What should I do here?", "Pause", "Resume", "Stop", "Close",
    "Slow voice", "Normal voice", "Keep reading new screens", "Reading...", "Paused",
    "Tap Read to start listening.", "This phone cannot read aloud. Try the Chrome browser.",
    "This phone has no voice for your language. Install one in the phone's text-to-speech settings.",
    "You are on: {title}", "Please note:", "Fill in {name}", "Choose {name}", "Tick the box: {name}",
    "You can tap: {list}", "and {n} more options",
    "There is nothing to do on this page. Tap Read this screen to listen to it.", "Nothing on this screen to read.",
    "rupees", "percent",
]


def voice_config(lang: str) -> dict:
    return {"speech": LANG_TAG.get(lang, "hi-IN"), "t": {s: tr(lang, s) for s in VOICE_STRINGS}}
