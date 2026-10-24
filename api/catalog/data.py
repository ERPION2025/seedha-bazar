"""Everything Seedha Bazar can trade, in four forms, and how one becomes another.

raw      grains, pulses, oilseeds, dry spices, cane: sold as harvested
fresh    vegetables, fruit, mushrooms, leaves: short shelf life, sold quickly
semi     processed in bulk: dried, ground, split, pressed, pulped (sold loose, or packed in retail packs)

Names carry Hindi and Marathi so every page and message can say them. Plain data, no database: it is reviewed in code.
Prices and yields for processed goods are STARTER ESTIMATES for planning. They are shown as such, and listings on the
platform replace them with real prices as they appear (see pricing.py). Staff should review them before launch.
"""

RAW, FRESH, SEMI, LIVE = "raw", "fresh", "semi", "live"
KINDS = (RAW, FRESH, SEMI, LIVE)

# key: (english, hindi, marathi, emoji, kind)
PRODUCTS = {
    # --- raw: grains, pulses, oilseeds (these names already existed; their translations live in web/translations.py) ---
    "wheat": ("Wheat", "गेहूँ", "गहू", "🌾", RAW), "rice": ("Rice", "चावल", "तांदूळ", "🍚", RAW), "soybean": ("Soybean", "सोयाबीन", "सोयाबीन", "🫘", RAW),
    "maize": ("Maize", "मक्का", "मका", "🌽", RAW), "gram": ("Gram (chana)", "चना", "हरभरा", "🫘", RAW), "lentil": ("Lentil (masoor)", "मसूर", "मसूर", "🫘", RAW),
    "mustard": ("Mustard", "सरसों", "मोहरी", "🌼", RAW), "tur": ("Tur (arhar)", "तुअर (अरहर)", "तूर", "🫘", RAW), "moong": ("Moong (green gram)", "मूँग", "मूग", "🫘", RAW),
    "urad": ("Urad (black gram)", "उड़द", "उडीद", "🫘", RAW), "kodo": ("Kodo millet", "कोदो", "कोदो", "🌾", RAW), "kutki": ("Kutki millet", "कुटकी", "कुटकी", "🌾", RAW),
    "sawa": ("Sawa millet", "सावाँ", "सावा", "🌾", RAW), "ragi": ("Ragi", "रागी", "नाचणी", "🌾", RAW), "jowar": ("Jowar", "ज्वार", "ज्वारी", "🌾", RAW),
    "bajra": ("Bajra", "बाजरा", "बाजरी", "🌾", RAW), "barley": ("Barley", "जौ", "जव", "🌾", RAW), "groundnut": ("Groundnut", "मूँगफली", "भुईमूग", "🥜", RAW),
    "sunflower": ("Sunflower", "सूरजमुखी", "सूर्यफूल", "🌻", RAW), "sesame": ("Sesame (til)", "तिल", "तीळ", "⚪", RAW), "safflower": ("Safflower", "कुसुम", "करडई", "🌼", RAW),
    "cotton": ("Cotton", "कपास", "कापूस", "☁️", RAW), "sugarcane": ("Sugarcane", "गन्ना", "ऊस", "🎋", RAW),
    "turmeric": ("Turmeric", "हल्दी", "हळद", "🟡", RAW), "red_chilli": ("Dry red chilli", "सूखी लाल मिर्च", "सुकी लाल मिरची", "🌶️", RAW),
    "coriander": ("Coriander seed", "धनिया", "धणे", "🌿", RAW),
    # --- fresh: vegetables ---
    "onion": ("Onion", "प्याज़", "कांदा", "🧅", FRESH), "potato": ("Potato", "आलू", "बटाटा", "🥔", FRESH), "tomato": ("Tomato", "टमाटर", "टोमॅटो", "🍅", FRESH),
    "green_chilli": ("Green chilli", "हरी मिर्च", "हिरवी मिरची", "🌶️", FRESH), "garlic": ("Garlic", "लहसुन", "लसूण", "🧄", FRESH), "ginger": ("Ginger", "अदरक", "आले", "🫚", FRESH),
    "brinjal": ("Brinjal (baingan)", "बैंगन", "वांगी", "🍆", FRESH), "cauliflower": ("Cauliflower", "फूलगोभी", "फुलकोबी", "🥦", FRESH), "cabbage": ("Cabbage", "पत्तागोभी", "पानकोबी", "🥬", FRESH),
    "okra": ("Okra (bhindi)", "भिंडी", "भेंडी", "🥒", FRESH), "peas": ("Green peas", "हरी मटर", "हिरवे वाटाणे", "🫛", FRESH), "carrot": ("Carrot", "गाजर", "गाजर", "🥕", FRESH),
    "spinach": ("Spinach (palak)", "पालक", "पालक", "🥬", FRESH), "moringa_leaf": ("Moringa leaves", "सहजन की पत्ती", "शेवग्याची पाने", "🌿", FRESH),
    "mushroom": ("Mushroom", "मशरूम", "अळिंबी (मशरूम)", "🍄", FRESH),
    # --- fresh: fruit ---
    "banana": ("Banana", "केला", "केळी", "🍌", FRESH), "mango": ("Mango", "आम", "आंबा", "🥭", FRESH), "orange": ("Orange / citrus", "संतरा", "संत्री", "🍊", FRESH),
    "guava": ("Guava", "अमरूद", "पेरू", "🍐", FRESH), "papaya": ("Papaya", "पपीता", "पपई", "🍈", FRESH), "pomegranate": ("Pomegranate", "अनार", "डाळिंब", "🍎", FRESH),
    "lemon": ("Lemon", "नींबू", "लिंबू", "🍋", FRESH), "custard_apple": ("Custard apple (sitaphal)", "सीताफल", "सीताफळ", "🍏", FRESH), "aonla": ("Amla (aonla)", "आँवला", "आवळा", "🟢", FRESH),
    # --- semi-finished: pulses, grains, oils ---
    "atta": ("Wheat flour (atta)", "गेहूँ का आटा", "गव्हाचे पीठ", "🫓", "semi"), "wheat_dalia": ("Wheat dalia", "गेहूँ का दलिया", "गव्हाचा दलिया", "🥣", "semi"),
    "chana_dal": ("Chana dal", "चना दाल", "हरभरा डाळ", "🫘", "semi"), "besan": ("Besan (gram flour)", "बेसन", "बेसन", "🫓", "semi"),
    "tur_dal": ("Tur dal", "अरहर दाल", "तूर डाळ", "🫘", "semi"), "moong_dal": ("Moong dal", "मूँग दाल", "मूग डाळ", "🫘", "semi"),
    "urad_dal": ("Urad dal", "उड़द दाल", "उडीद डाळ", "🫘", "semi"), "masoor_dal": ("Masoor dal", "मसूर दाल", "मसूर डाळ", "🫘", "semi"),
    "rice_milled": ("Milled rice", "मिल का चावल", "गिरणीतला तांदूळ", "🍚", "semi"), "ragi_flour": ("Ragi flour", "रागी का आटा", "नाचणीचे पीठ", "🫓", "semi"),
    "millet_flour": ("Millet flour", "मिलेट का आटा", "भरड धान्याचे पीठ", "🫓", "semi"), "maize_flour": ("Maize flour", "मक्का का आटा", "मक्याचे पीठ", "🫓", "semi"),
    "soybean_oil": ("Soybean oil", "सोयाबीन तेल", "सोयाबीन तेल", "🛢️", "semi"), "mustard_oil": ("Mustard oil (kachi ghani)", "सरसों का तेल (कच्ची घानी)", "मोहरीचे तेल (कच्ची घाणी)", "🛢️", "semi"),
    "groundnut_oil": ("Groundnut oil", "मूँगफली का तेल", "शेंगदाणा तेल", "🛢️", "semi"), "sesame_oil": ("Sesame oil", "तिल का तेल", "तिळाचे तेल", "🛢️", "semi"),
    "sunflower_oil": ("Sunflower oil", "सूरजमुखी का तेल", "सूर्यफूल तेल", "🛢️", "semi"), "jaggery": ("Jaggery (gur)", "गुड़", "गूळ", "🟤", "semi"),
    # --- semi-finished: spices ---
    "turmeric_powder": ("Turmeric powder", "हल्दी पाउडर", "हळद पावडर", "🟡", "semi"), "chilli_powder": ("Red chilli powder", "लाल मिर्च पाउडर", "लाल मिरची पावडर", "🌶️", "semi"),
    "coriander_powder": ("Coriander powder", "धनिया पाउडर", "धणे पावडर", "🌿", "semi"), "dry_ginger": ("Dry ginger (sonth)", "सोंठ (सूखी अदरक)", "सुंठ", "🫚", "semi"),
    "garlic_flakes": ("Dried garlic flakes", "सूखे लहसुन के फ्लेक्स", "वाळलेल्या लसणाचे फ्लेक्स", "🧄", "semi"), "green_chilli_paste": ("Green chilli paste", "हरी मिर्च का पेस्ट", "हिरव्या मिरचीची पेस्ट", "🌶️", "semi"),
    # --- semi-finished: vegetables and mushrooms ---
    "dry_mushroom": ("Dried mushroom", "सूखा मशरूम", "सुका मशरूम", "🍄", "semi"), "mushroom_powder": ("Mushroom powder", "मशरूम पाउडर", "मशरूम पावडर", "🍄", "semi"),
    "moringa_powder": ("Moringa leaf powder", "सहजन पत्ती पाउडर", "शेवग्याच्या पानांची पावडर", "🌿", "semi"), "spinach_powder": ("Spinach powder", "पालक पाउडर", "पालक पावडर", "🥬", "semi"),
    "tomato_puree": ("Tomato puree", "टमाटर प्यूरी", "टोमॅटो प्युरी", "🍅", "semi"), "dried_tomato": ("Dried tomato", "सूखे टमाटर", "वाळलेले टोमॅटो", "🍅", "semi"),
    "onion_flakes": ("Dehydrated onion flakes", "सूखे प्याज़ के फ्लेक्स", "वाळलेल्या कांद्याचे फ्लेक्स", "🧅", "semi"), "potato_chips": ("Potato chips", "आलू चिप्स", "बटाटा चिप्स", "🥔", "semi"),
    "frozen_peas": ("Frozen green peas", "फ्रोज़न हरी मटर", "गोठवलेले हिरवे वाटाणे", "🫛", "semi"),
    # --- semi-finished: fruit ---
    "banana_chips": ("Banana chips", "केले के चिप्स", "केळी चिप्स", "🍌", "semi"), "banana_flour": ("Raw banana flour", "कच्चे केले का आटा", "कच्च्या केळीचे पीठ", "🍌", "semi"),
    "mango_pulp": ("Mango pulp", "आम का पल्प", "आंब्याचा गर", "🥭", "semi"), "amchur": ("Amchur (dry mango powder)", "अमचूर", "आमचूर", "🥭", "semi"),
    "mango_pickle": ("Mango pickle", "आम का अचार", "आंब्याचे लोणचे", "🥭", "semi"), "lemon_pickle": ("Lemon pickle", "नींबू का अचार", "लिंबाचे लोणचे", "🍋", "semi"),
    "guava_jam": ("Guava jam / jelly", "अमरूद जैम / जेली", "पेरूचा जाम / जेली", "🍐", "semi"), "aonla_candy": ("Amla candy", "आँवला कैंडी", "आवळा कँडी", "🟢", "semi"),
    "custard_apple_pulp": ("Custard apple pulp", "सीताफल पल्प", "सीताफळ गर", "🍏", "semi"), "orange_juice": ("Orange juice / squash", "संतरा जूस / स्क्वैश", "संत्र्याचा रस / स्क्वॅश", "🍊", "semi"),
    "anardana": ("Anardana (dried pomegranate seed)", "अनारदाना", "अनारदाना", "🍎", "semi"),
    # Livelihoods beyond crops: dairy, poultry, fish, bees, silk, pigs ("live" keeps them out of crop lists and mandi rates)
    "milk": ("Milk", "दूध", "दूध", "🥛", LIVE), "ghee": ("Ghee", "घी", "तूप", "🧈", LIVE), "paneer": ("Paneer", "पनीर", "पनीर", "🧀", LIVE),
    "eggs": ("Eggs", "अंडे", "अंडी", "🥚", LIVE), "broiler": ("Broiler chicken (live)", "ब्रॉयलर मुर्गा (ज़िंदा)", "ब्रॉयलर कोंबडी (जिवंत)", "🐔", LIVE),
    "desi_chicken": ("Desi chicken (live)", "देसी मुर्गा (ज़िंदा)", "गावठी कोंबडी (जिवंत)", "🐓", LIVE),
    "fish": ("Fish (rohu, catla, mrigal)", "मछली (रोहू, कतला, मृगल)", "मासे (रोहू, कटला, मृगळ)", "🐟", LIVE),
    "honey": ("Honey", "शहद", "मध", "🍯", LIVE), "beeswax": ("Beeswax", "मधुमक्खी का मोम", "मधमाशीचे मेण", "🕯️", LIVE),
    "cocoons": ("Silk cocoons", "रेशम कोया", "रेशीम कोष", "🐛", LIVE), "silk_yarn": ("Raw silk yarn", "कच्चा रेशम धागा", "कच्चा रेशीम धागा", "🧵", LIVE),
    "pigs": ("Pigs (live)", "सूअर (ज़िंदा)", "डुक्कर (जिवंत)", "🐖", LIVE), "piglets": ("Piglets", "सूअर के बच्चे", "डुक्कराची पिल्ले", "🐷", LIVE),
}

# Which raw or fresh product each conversion starts from, and what comes out.
# yield: kg of output per 100 kg of input (low, high). cost: processing cost in rupees per kg of input.
# price: typical selling price of the output in rupees per kg (low, high), loose, wholesale. STARTER ESTIMATES.
# needs: keys of NEEDS. how: one plain sentence in English, Hindi, Marathi.
NEEDS = {
    "dryer": ("Solar or electric dryer", "सोलर या इलेक्ट्रिक ड्रायर", "सोलर किंवा इलेक्ट्रिक ड्रायर"),
    "grinder": ("Grinder or pulveriser", "ग्राइंडर / पल्वराइज़र", "ग्राइंडर / पल्व्हरायझर"),
    "mill": ("Flour or dal mill", "आटा या दाल मिल", "पीठ किंवा डाळ गिरणी"),
    "expeller": ("Oil expeller (ghani)", "तेल घानी", "तेल घाणी"),
    "pulper": ("Pulper and cooking vessel", "पल्पर और बर्तन", "पल्पर व भांडी"),
    "fryer": ("Fryer and packing", "फ्रायर और पैकिंग", "फ्रायर व पॅकिंग"),
    "cold": ("Cold storage or freezer", "कोल्ड स्टोरेज / फ्रीज़र", "कोल्ड स्टोरेज / फ्रीझर"),
    "boiler": ("Jaggery boiler (kolhu)", "गुड़ भट्टी (कोल्हू)", "गूळ भट्टी (कोल्हू)"),
    "fssai": ("FSSAI licence", "FSSAI लाइसेंस", "FSSAI परवाना"),
    "pack": ("Packing and labels", "पैकिंग और लेबल", "पॅकिंग व लेबल"),
}

CONVERSIONS = [
    # from, to, yield (low, high), cost per kg input, price per kg out (low, high), needs, how (en, hi, mr)
    ("mushroom", "dry_mushroom", (8, 12), 12, (700, 1400), ("dryer", "pack", "fssai"), ("Wash, slice and dry at 50-60°C until it snaps. Pack airtight.", "धोकर, काटकर 50-60°C पर कड़क होने तक सुखाएँ। हवाबंद पैक करें।", "धुऊन, कापून 50-60°C वर कडक होईपर्यंत वाळवा. हवाबंद पॅक करा.")),
    ("mushroom", "mushroom_powder", (8, 11), 15, (900, 1800), ("dryer", "grinder", "fssai"), ("Dry fully, grind fine and sieve. Sell as soup or health powder.", "पूरा सुखाकर बारीक पीसें और छानें। सूप या हेल्थ पाउडर के रूप में बेचें।", "पूर्ण वाळवून बारीक दळा व चाळा. सूप किंवा हेल्थ पावडर म्हणून विका.")),
    ("moringa_leaf", "moringa_powder", (10, 14), 10, (300, 600), ("dryer", "grinder", "pack"), ("Shade-dry the leaves, grind and sieve. Sold as a health food.", "पत्तियों को छाँव में सुखाएँ, पीसें और छानें। हेल्थ फ़ूड के रूप में बिकता है।", "पाने सावलीत वाळवा, दळा व चाळा. हेल्थ फूड म्हणून विकले जाते.")),
    ("spinach", "spinach_powder", (6, 9), 10, (250, 500), ("dryer", "grinder"), ("Wash, dry at low heat, grind and pack airtight.", "धोकर कम तापमान पर सुखाएँ, पीसें और हवाबंद पैक करें।", "धुऊन कमी तापमानावर वाळवा, दळा व हवाबंद पॅक करा.")),
    ("tomato", "tomato_puree", (25, 40), 6, (60, 110), ("pulper", "fssai", "pack"), ("Boil, pulp, strain and cook down. Fill hot in clean jars or pouches.", "उबालें, पल्प बनाएँ, छानें और गाढ़ा करें। गरम ही साफ़ जार या पाउच में भरें।", "उकळा, गर करा, गाळा व दाट करा. गरम असतानाच स्वच्छ बरणी/पाऊचमध्ये भरा.")),
    ("tomato", "dried_tomato", (5, 8), 12, (450, 900), ("dryer", "pack"), ("Slice, salt lightly and dry until leathery. Pack in oil or airtight.", "काटें, हल्का नमक लगाएँ और चमड़े जैसा होने तक सुखाएँ। हवाबंद पैक करें।", "कापा, थोडे मीठ लावा व चामड्यासारखे होईपर्यंत वाळवा. हवाबंद पॅक करा.")),
    ("onion", "onion_flakes", (10, 14), 9, (140, 300), ("dryer", "fssai", "pack"), ("Peel, slice and dry at 55°C. Used by food makers and hotels.", "छीलें, काटें और 55°C पर सुखाएँ। फ़ूड कंपनियाँ और होटल खरीदते हैं।", "सोला, कापा व 55°C वर वाळवा. फूड कंपन्या व हॉटेल खरेदी करतात.")),
    ("garlic", "garlic_flakes", (30, 38), 10, (250, 500), ("dryer", "pack"), ("Peel, slice and dry. Keeps for a year when sealed.", "छीलें, काटें और सुखाएँ। बंद रखने पर साल भर चलता है।", "सोला, कापा व वाळवा. बंद ठेवल्यास वर्षभर टिकते.")),
    ("ginger", "dry_ginger", (18, 24), 8, (250, 600), ("dryer",), ("Wash, peel lightly and sun-dry for 7-10 days.", "धोएँ, हल्का छीलें और 7-10 दिन धूप में सुखाएँ।", "धुवा, हलकेच सोला व 7-10 दिवस उन्हात वाळवा.")),
    ("potato", "potato_chips", (20, 28), 40, (180, 320), ("fryer", "fssai", "pack"), ("Slice thin, wash, fry and pack in sealed pouches.", "पतला काटें, धोएँ, तलें और सील पाउच में पैक करें।", "पातळ कापा, धुवा, तळा व सीलबंद पाऊचमध्ये पॅक करा.")),
    ("green_chilli", "green_chilli_paste", (90, 95), 25, (80, 140), ("grinder", "fssai", "pack"), ("Grind with a little salt and oil and fill in jars.", "थोड़े नमक और तेल के साथ पीसें और जार में भरें।", "थोडे मीठ व तेलासह वाटा आणि बरणीत भरा.")),
    ("turmeric", "turmeric_powder", (88, 94), 6, (160, 320), ("grinder", "fssai", "pack"), ("Clean, dry, grind fine and pack. Brands pay more for tested curcumin.", "साफ़ करें, सुखाएँ, बारीक पीसें और पैक करें। टेस्टेड करक्यूमिन पर अच्छा दाम मिलता है।", "स्वच्छ करा, वाळवा, बारीक दळा व पॅक करा. तपासलेल्या कर्क्युमिनला चांगला भाव मिळतो.")),
    ("red_chilli", "chilli_powder", (85, 92), 6, (280, 550), ("grinder", "fssai", "pack"), ("Remove stalks, dry, grind and pack in small sealed packets.", "डंठल हटाएँ, सुखाएँ, पीसें और छोटे सील पैकेट में रखें।", "देठ काढा, वाळवा, दळा व लहान सीलबंद पाकिटात भरा.")),
    ("coriander", "coriander_powder", (90, 95), 5, (130, 260), ("grinder", "pack"), ("Clean and roast lightly, grind and pack.", "साफ़ करके हल्का भूनें, पीसें और पैक करें।", "स्वच्छ करून हलके भाजा, दळा व पॅक करा.")),
    ("banana", "banana_chips", (28, 35), 45, (200, 340), ("fryer", "fssai", "pack"), ("Peel raw banana, slice, fry in oil and pack.", "कच्चे केले छीलें, काटें, तेल में तलें और पैक करें।", "कच्ची केळी सोला, कापा, तेलात तळा व पॅक करा.")),
    ("banana", "banana_flour", (18, 24), 12, (120, 260), ("dryer", "grinder", "pack"), ("Slice raw banana, dry and grind. Gluten-free flour.", "कच्चे केले काटकर सुखाएँ और पीसें। ग्लूटन-फ्री आटा।", "कच्ची केळी कापून वाळवा व दळा. ग्लुटेन-फ्री पीठ.")),
    ("mango", "mango_pulp", (45, 55), 15, (70, 140), ("pulper", "fssai", "pack"), ("Ripe mango pulped, heated and filled in sealed tins or pouches.", "पके आम का पल्प निकालकर गरम करें और सील टिन/पाउच में भरें।", "पिकलेल्या आंब्याचा गर काढून गरम करा व सीलबंद डबा/पाऊचमध्ये भरा.")),
    ("mango", "amchur", (8, 12), 10, (250, 480), ("dryer", "grinder"), ("Raw mango slices sun-dried, then ground to powder.", "कच्चे आम के टुकड़े धूप में सुखाकर पीसें।", "कैरीच्या फोडी उन्हात वाळवून दळा.")),
    ("mango", "mango_pickle", (110, 140), 90, (160, 320), ("pack", "fssai"), ("Raw mango with oil and spices, matured in jars for 2 weeks.", "कच्चे आम को तेल-मसालों के साथ जार में 2 हफ़्ते पकाएँ।", "कैरी तेल-मसाल्यांसह बरणीत 2 आठवडे मुरवा.")),
    ("lemon", "lemon_pickle", (110, 130), 70, (140, 260), ("pack", "fssai"), ("Lemon with salt and spices, matured in jars.", "नींबू को नमक-मसालों के साथ जार में पकाएँ।", "लिंबू मीठ-मसाल्यांसह बरणीत मुरवा.")),
    ("guava", "guava_jam", (80, 95), 60, (120, 220), ("pulper", "fssai", "pack"), ("Pulp with sugar and pectin, cook and fill hot.", "पल्प को चीनी और पेक्टिन के साथ पकाकर गरम भरें।", "गर साखर व पेक्टिनसह शिजवून गरम भरा.")),
    ("aonla", "aonla_candy", (70, 90), 55, (180, 350), ("pulper", "dryer", "fssai"), ("Prick, soak in sugar syrup and dry. Sells well as a health snack.", "छेदकर चीनी की चाशनी में भिगोएँ और सुखाएँ। हेल्थ स्नैक के रूप में अच्छा बिकता है।", "टोचून साखरेच्या पाकात भिजवा व वाळवा. हेल्थ स्नॅक म्हणून चांगले विकले जाते.")),
    ("custard_apple", "custard_apple_pulp", (35, 45), 20, (200, 400), ("pulper", "cold", "fssai"), ("Remove seeds, pulp and freeze. Ice-cream makers buy it.", "बीज निकालकर पल्प बनाएँ और फ्रीज़ करें। आइसक्रीम वाले खरीदते हैं।", "बिया काढून गर करा व गोठवा. आईस्क्रीम उत्पादक खरेदी करतात.")),
    ("orange", "orange_juice", (35, 45), 12, (60, 110), ("pulper", "fssai", "pack"), ("Press, strain and pasteurise. Pack in sealed bottles.", "निचोड़ें, छानें और पास्चराइज़ करें। सील बोतल में भरें।", "पिळा, गाळा व पाश्चराइज करा. सीलबंद बाटलीत भरा.")),
    ("peas", "frozen_peas", (40, 46), 12, (90, 150), ("cold", "fssai", "pack"), ("Shell, blanch and freeze fast. Needs an unbroken cold chain.", "दाने निकालें, ब्लांच करें और तेज़ी से फ्रीज़ करें। कोल्ड चेन ज़रूरी है।", "दाणे काढा, ब्लांच करा व झटकन गोठवा. शीतसाखळी आवश्यक.")),
    ("pomegranate", "anardana", (6, 9), 20, (500, 900), ("dryer", "pack"), ("Separate the seeds and sun-dry until sticky-dry.", "दाने अलग करके धूप में सुखाएँ।", "दाणे वेगळे करून उन्हात वाळवा.")),
    ("sugarcane", "jaggery", (9, 12), 4, (40, 70), ("boiler", "pack"), ("Crush, boil the juice, stir and mould. Chemical-free jaggery sells higher.", "रस निकालकर उबालें, चलाएँ और ढालें। रसायन-मुक्त गुड़ ऊँचे दाम पर बिकता है।", "रस काढून उकळा, ढवळा व साचात ओता. रसायनमुक्त गूळ जास्त भावाने विकतो.")),
    ("wheat", "atta", (76, 82), 2.5, (28, 42), ("mill", "pack"), ("Clean, condition and mill. Brands pay for clean, packed atta.", "साफ़ करके पिसवाएँ। साफ़ पैक आटे का दाम अच्छा मिलता है।", "स्वच्छ करून दळा. स्वच्छ पॅक पिठाला चांगला भाव.")),
    ("wheat", "wheat_dalia", (70, 78), 3, (30, 45), ("mill", "pack"), ("Break the grain coarsely and sieve.", "दाने को मोटा तोड़कर छानें।", "दाणे जाडसर फोडून चाळा.")),
    ("gram", "chana_dal", (76, 82), 3, (70, 95), ("mill", "pack"), ("Clean, split and polish in a dal mill.", "साफ़ करके दाल मिल में तोड़ें और पॉलिश करें।", "स्वच्छ करून डाळ गिरणीत फोडा व पॉलिश करा.")),
    ("gram", "besan", (88, 94), 4, (75, 100), ("mill", "pack"), ("Mill the dal into fine flour and pack.", "दाल को बारीक पीसकर पैक करें।", "डाळ बारीक दळून पॅक करा.")),
    ("tur", "tur_dal", (70, 76), 4, (110, 150), ("mill", "pack"), ("Clean, de-husk and split in a dal mill.", "साफ़ करके दाल मिल में छिलका हटाएँ और तोड़ें।", "स्वच्छ करून डाळ गिरणीत साल काढा व फोडा.")),
    ("moong", "moong_dal", (76, 82), 4, (100, 135), ("mill", "pack"), ("Split and polish; keep the green husk for moong chilka.", "तोड़ें और पॉलिश करें; छिलका अलग बेचा जा सकता है।", "फोडा व पॉलिश करा; साल वेगळे विकता येते.")),
    ("urad", "urad_dal", (76, 82), 4, (100, 140), ("mill", "pack"), ("De-husk and split in a dal mill.", "दाल मिल में छिलका हटाएँ और तोड़ें।", "डाळ गिरणीत साल काढा व फोडा.")),
    ("lentil", "masoor_dal", (74, 80), 4, (75, 100), ("mill", "pack"), ("De-husk and split.", "छिलका हटाकर तोड़ें।", "साल काढून फोडा.")),
    ("rice", "rice_milled", (64, 69), 2, (32, 60), ("mill", "pack"), ("Hull and polish paddy in a rice mill. Bran and husk have value too.", "धान को राइस मिल में छीलें और पॉलिश करें। भूसी और चोकर भी बिकते हैं।", "भात गिरणीत भात सोलून पॉलिश करा. कोंडा व तूसही विकले जातात.")),
    ("ragi", "ragi_flour", (92, 96), 3, (40, 80), ("mill", "pack"), ("Clean and mill. Demand is rising for millet foods.", "साफ़ करके पीसें। मिलेट फ़ूड की माँग बढ़ रही है।", "स्वच्छ करून दळा. भरड धान्याला मागणी वाढत आहे.")),
    ("kodo", "millet_flour", (88, 95), 3, (45, 95), ("mill", "pack"), ("De-husk and mill into flour. Same steps for kutki, sawa, jowar and bajra.", "छिलका हटाकर आटा पीसें। कुटकी, सावाँ, ज्वार, बाजरा के लिए भी यही तरीका।", "साल काढून पीठ दळा. कुटकी, सावा, ज्वारी, बाजरीसाठीही हीच पद्धत.")),
    ("kutki", "millet_flour", (88, 95), 3, (45, 95), ("mill", "pack"), ("De-husk and mill into flour.", "छिलका हटाकर आटा पीसें।", "साल काढून पीठ दळा.")),
    ("sawa", "millet_flour", (88, 95), 3, (45, 95), ("mill", "pack"), ("De-husk and mill into flour.", "छिलका हटाकर आटा पीसें।", "साल काढून पीठ दळा.")),
    ("jowar", "millet_flour", (88, 95), 3, (40, 75), ("mill", "pack"), ("Clean and mill into flour.", "साफ़ करके आटा पीसें।", "स्वच्छ करून पीठ दळा.")),
    ("bajra", "millet_flour", (88, 95), 3, (40, 75), ("mill", "pack"), ("Clean and mill into flour.", "साफ़ करके आटा पीसें।", "स्वच्छ करून पीठ दळा.")),
    ("maize", "maize_flour", (80, 88), 2.5, (30, 48), ("mill", "pack"), ("Dry, clean and mill into flour or grits.", "सुखाकर साफ़ करें और आटा या दलिया पीसें।", "वाळवून स्वच्छ करा व पीठ किंवा भरडा दळा.")),
    ("soybean", "soybean_oil", (14, 17), 6, (130, 180), ("expeller", "fssai", "pack"), ("Cold-press the clean seed. The cake is sold as feed.", "साफ़ बीज को कोल्ड-प्रेस करें। खली चारे के रूप में बिकती है।", "स्वच्छ बिया कोल्ड-प्रेस करा. पेंड पशुखाद्य म्हणून विकली जाते.")),
    ("mustard", "mustard_oil", (32, 36), 5, (150, 210), ("expeller", "fssai", "pack"), ("Press in a kachi ghani expeller; settle and filter. The cake is sold as feed.", "कच्ची घानी में पेरें, बैठने दें और छानें। खली चारे में बिकती है।", "कच्ची घाणीत गाळा, ठेवू द्या व गाळून घ्या. पेंड पशुखाद्य म्हणून विकली जाते.")),
    ("groundnut", "groundnut_oil", (33, 40), 6, (170, 260), ("expeller", "fssai", "pack"), ("Shell, clean and cold-press. The cake is sold as feed.", "छीलें, साफ़ करें और कोल्ड-प्रेस करें। खली चारे में बिकती है।", "सोलून, स्वच्छ करून कोल्ड-प्रेस करा. पेंड पशुखाद्य म्हणून विकली जाते.")),
    ("sesame", "sesame_oil", (36, 42), 8, (320, 480), ("expeller", "fssai", "pack"), ("Clean and cold-press. Premium oil.", "साफ़ करके कोल्ड-प्रेस करें। प्रीमियम तेल।", "स्वच्छ करून कोल्ड-प्रेस करा. प्रीमियम तेल.")),
    ("sunflower", "sunflower_oil", (28, 34), 6, (120, 170), ("expeller", "fssai", "pack"), ("Clean and cold-press.", "साफ़ करके कोल्ड-प्रेस करें।", "स्वच्छ करून कोल्ड-प्रेस करा.")),
]

PACKS = ("bulk", "packed")  # a processed listing is sold loose in bulk, or packed in retail packs
