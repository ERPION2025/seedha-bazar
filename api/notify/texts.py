"""Message wording. One entry per message type, in English, Hindi and Marathi.

SMS in India must use templates registered with the operator (DLT). When a provider is connected, register each text below as a
template and keep the {placeholders} in the same order. Keep them short.
"""

TEXTS = {
    "input_update": {
        "en": "Seedha Bazar: {what} ({product}). See: {link}",
        "hi": "सीधा बाज़ार: {what} ({product})। देखें: {link}",
        "mr": "सीधा बाज़ार: {what} ({product}). पाहा: {link}",
    },
    "issue_alert": {
        "en": "Seedha Bazar: {what} in {place}. Open: {link}",
        "hi": "सीधा बाज़ार: {place} में {what}। खोलें: {link}",
        "mr": "सीधा बाज़ार: {place} मध्ये {what}. उघडा: {link}",
    },
    "issue_reply": {
        "en": "Seedha Bazar: an expert answered your problem. Open: {link}",
        "hi": "सीधा बाज़ार: विशेषज्ञ ने आपकी समस्या का जवाब दिया। खोलें: {link}",
        "mr": "सीधा बाज़ार: तज्ज्ञाने तुमच्या समस्येला उत्तर दिले. उघडा: {link}",
    },
    "input_offer": {
        "en": "Seedha Bazar: {centre} offers {item} for {place}. See and request: {link}",
        "hi": "सीधा बाज़ार: {centre} {place} के लिए {item} दे रहा है। देखें और माँगें: {link}",
        "mr": "सीधा बाज़ार: {centre} {place} साठी {item} देत आहे. पाहा व मागणी करा: {link}",
    },
    "deal_request": {
        "en": "Seedha Bazar: a buyer asks you for {product} ({qty}). See the offer and reply: {link}",
        "hi": "सीधा बाज़ार: एक खरीदार आपसे {product} ({qty}) माँग रहा है। प्रस्ताव देखें और जवाब दें: {link}",
        "mr": "सीधा बाज़ार: एक खरेदीदार तुमच्याकडे {product} ({qty}) मागत आहे. प्रस्ताव पाहा व उत्तर द्या: {link}",
    },
    "deal_update": {
        "en": "Seedha Bazar: {what}. Order for {product}: {link}",
        "hi": "सीधा बाज़ार: {what}। {product} का ऑर्डर: {link}",
        "mr": "सीधा बाज़ार: {what}. {product} ची ऑर्डर: {link}",
    },
    "calc_result": {
        "en": "Seedha Bazar: {crop}, {qty}. At the mandi you get {hand} in hand ({cut} is cut in between). This is an estimate.",
        "hi": "सीधा बाज़ार: {crop}, {qty}। मंडी में हाथ में {hand} आएगा ({cut} बीच में कटेगा)। यह अनुमान है।",
        "mr": "सीधा बाज़ार: {crop}, {qty}. मंडीत हातात {hand} येईल ({cut} मध्ये कापले जाईल). हा अंदाज आहे.",
    },
    "calc_result_direct": {
        "en": "Seedha Bazar: {crop}, {qty}. Mandi: {hand} in hand. Direct sale: {direct} in hand. Difference: {gap}. This is an estimate.",
        "hi": "सीधा बाज़ार: {crop}, {qty}। मंडी: हाथ में {hand}। सीधी बिक्री: हाथ में {direct}। फ़र्क: {gap}। यह अनुमान है।",
        "mr": "सीधा बाज़ार: {crop}, {qty}. मंडी: हातात {hand}. थेट विक्री: हातात {direct}. फरक: {gap}. हा अंदाज आहे.",
    },
    "rate_alert": {
        "en": "Seedha Bazar: {crop} in {place} on {date}: {price} per quintal.{msp} Mandi-reported rates.",
        "hi": "सीधा बाज़ार: {place} में {date} को {crop}: {price} प्रति क्विंटल।{msp} मंडी द्वारा बताए भाव।",
        "mr": "सीधा बाज़ार: {place} मध्ये {date} रोजी {crop}: {price} प्रति क्विंटल.{msp} मंडीने कळवलेले भाव.",
    },
    "enquiry_received": {
        "en": "Seedha Bazar: a buyer is interested in your {crop} ({qty}). Open to reply: {link}",
        "hi": "सीधा बाज़ार: एक खरीदार को आपकी {crop} ({qty}) में दिलचस्पी है। जवाब देने के लिए खोलें: {link}",
        "mr": "सीधा बाज़ार: एका खरेदीदाराला तुमच्या {crop} ({qty}) मध्ये रस आहे. उत्तर देण्यासाठी उघडा: {link}",
    },
    "enquiry_accepted": {
        "en": "Seedha Bazar: the seller accepted your enquiry for {crop}. You can now see their contact: {link}",
        "hi": "सीधा बाज़ार: विक्रेता ने {crop} के लिए आपकी पूछताछ मंज़ूर की। अब आप उनका संपर्क देख सकते हैं: {link}",
        "mr": "सीधा बाज़ार: विक्रेत्याने {crop} साठी तुमची चौकशी मंजूर केली. आता तुम्ही त्यांचा संपर्क पाहू शकता: {link}",
    },
    "enquiry_declined": {
        "en": "Seedha Bazar: the seller cannot take your enquiry for {crop} right now. See other listings: {link}",
        "hi": "सीधा बाज़ार: विक्रेता अभी {crop} के लिए आपकी पूछताछ नहीं ले सकते। दूसरी लिस्टिंग देखें: {link}",
        "mr": "सीधा बाज़ार: विक्रेता सध्या {crop} साठी तुमची चौकशी घेऊ शकत नाहीत. इतर लिस्टिंग पहा: {link}",
    },
    "enquiry_message": {
        "en": "Seedha Bazar: new message about {crop}. Open to read: {link}",
        "hi": "सीधा बाज़ार: {crop} के बारे में नया संदेश। पढ़ने के लिए खोलें: {link}",
        "mr": "सीधा बाज़ार: {crop} बद्दल नवीन संदेश. वाचण्यासाठी उघडा: {link}",
    },
}


def render(template: str, lang: str, params: dict) -> str:
    variants = TEXTS[template]
    return variants.get(lang, variants["en"]).format(**params)
