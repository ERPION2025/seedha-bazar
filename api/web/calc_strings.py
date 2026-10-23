"""Every sentence the calculator's JavaScript can show. Translated on the server and handed to the page as JSON."""
from .i18n import tr

CALC_STRINGS = [
    "Which crop do you want to sell?", "How much do you have?", "Rate near you today", "What does the mandi take from you?",
    "Compare with another market?", "Your result", "Next", "Back", "Skip", "Start over", "Search crop", "Quintal", "Kg", "Tonne", "Bag",
    "Weight of one bag (kg)", "Typical rate near you", "Reported on {date}", "Rates are from mandis reported to Agmarknet (Govt. of India). Your mandi may differ.",
    "Govt MSP", "My own rate", "Rate per quintal (₹)", "Rate per kg (₹)", "per quintal", "per kg", "Mandi", "No rate found near you for this crop. Type your own rate.",
    "Loading rates...", "Rates could not be loaded. Type your own rate.", "up {n}% this week", "down {n}% this week", "Sample data, not real prices",
    "Commission (aadhat) %", "Weighing and loading fees (₹)", "Transport to the mandi (₹)", "Other cuts (₹)", "Not sure? Leave 0. You can change it later.",
    "Best prices in your state today", "Transport to that market (₹)", "A buyer offered me (₹ per quintal)", "Money in your hand at the mandi",
    "Money in your hand from {place}", "A direct sale gives {amount} more at this rate", "The mandi gives {amount} more at this rate",
    "No difference at these rates", "Value at the rate", "Commission", "Fees and other cuts", "Transport", "In your hand", "Cut in between",
    "Seedha Bazar commission on your sale", "This is an estimate. The real result depends on the buyer, the quality of your crop and transport.",
    "Listen", "Send to my WhatsApp", "Send to my phone as SMS", "Share on WhatsApp", "Tell me {crop} rates every day", "List this crop for sale",
    "Sign in to get this on your phone", "Sent to your WhatsApp.", "Sent as SMS to your phone.", "Messages are not switched on yet. WhatsApp will open so you can send it to yourself.",
    "Too many messages today. Try tomorrow.", "Something went wrong. Please try again.", "You will get {crop} rates every day.",
    "Saved. Daily messages start as soon as messaging is switched on.", "Allow location to see rates near you", "Use my location", "Choose place", "Finding your place...",
    "Could not find your place. Choose it from the list.", "Location is blocked. Choose your place from the list.", "Choose your place", "State", "District", "Save",
    "Tap the picture of your crop. If you cannot see it, type its name in the search box.", "Choose", "Your place", "Location not set", "quintal", "kg", "tonne", "bag", "Enter a number bigger than zero", "Pick a crop first", "Amount", "OK",
]


def js_strings(lang: str) -> dict:
    return {s: tr(lang, s) for s in CALC_STRINGS}
