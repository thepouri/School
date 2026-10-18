"""Constants extracted from Skool itself.

All these values come from the discovery page chunk and the discovery.json
response, not guesses.
"""

from __future__ import annotations

import itertools
import string

# Page size from pageSize: 30 in the paging component
PAGE_SIZE = 30
# Practical page cap per slice (34 * 30 = 1020)
MAX_PAGES = 34

# From the filter component: choices for the price key
PRICES: tuple[str, ...] = ("free", "free-trial", "paid")
# From the filter component: choices for the type key
TYPES: tuple[str, ...] = ("public", "private")
# From the filter component: choices for the sort key
SORTS: tuple[str, ...] = ("trending", "top-v2")

# slug -> id categories (c parameter)
CATEGORIES: dict[str, str] = {
    "hobbies": "8a7678583d3246a1a1a0a4a994321146",
    "music": "f08071afbd9746b6adb83522451cd280",
    "money": "2830789533b448d8812e7d5d661d776c",
    "spirituality": "ce77e1a8d5824d8497921368a9328dc0",
    "tech": "b1dae7402dda47a0b7aa51334474a158",
    "health": "e85018a1df484d5ea09c43c8b2764586",
    "sports": "ca063c42092041d5a8f48dd1903a1f3b",
    "self_improvement": "5c00cc7aee1048588759b5504380917a",
    "relationships": "fd915e5fee4a496db1c82c527a33ef09",
}
CATEGORY_BY_ID: dict[str, str] = {v: k for k, v in CATEGORIES.items()}

# Important: the lang parameter must take the name, not the code
LANGUAGES: tuple[str, ...] = (
    "english",
    "german",
    "spanish",
    "french",
    "chinese",
    "italian",
    "dutch",
    "vietnamese",
    "arabic",
    "hebrew",
    "danish",
    "romanian",
    "turkish",
    "polish",
    "czech",
    "hungarian",
    "swedish",
    "portuguese",
    "bulgarian",
    "norwegian",
    "finnish",
    "croatian",
    "latvian",
    "slovak",
    "serbian",
    "mongolian",
    "haitian",
    "thai",
    "slovenian",
    "russian",
    "lithuanian",
    "amharic",
    "malay",
    "estonian",
    "greek",
    "ukrainian",
    "swahili",
    "japanese",
    "filipino",
    "persian",
    "welsh",
    "korean",
    "cantonese",
    "indonesian",
    "latin",
    "bengali",
    "catalan",
    "hindi",
)

# Language-appropriate search words. When `--mode search` runs for a given
# language, these are the queries used (instead of the English keyword list),
# because a German/Japanese/… group rarely matches an English query.
# Only languages with a dedicated set are listed; the rest fall back to the
# generic keyword plan.
LANGUAGE_QUERIES: dict[str, tuple[str, ...]] = {
    "german": (
        "kurs", "community", "gruppe", "business", "marketing", "geld",
        "investieren", "lernen", "studium", "schule", "bildung", "coaching",
        "unternehmen", "verkauf", "erfolg", "gesundheit", "fitness", "yoga",
        "kreativ", "musik", "spiritualität", "englisch", "deutsch", "startup",
        "immobilien", "krypto", "handel", "online", "selbständig", "freiheit",
    ),
    "spanish": (
        "curso", "comunidad", "negocio", "marketing", "dinero", "invertir",
        "aprender", "escuela", "educación", "coaching", "empresa", "ventas",
        "éxito", "salud", "fitness", "yoga", "creatividad", "música",
        "espiritualidad", "inglés", "español", "inmuebles", "cripto", "online",
        "independiente", "libertad", "finanzas", "ganar", "trading",
    ),
    "french": (
        "cours", "communauté", "affaires", "marketing", "argent", "investir",
        "apprendre", "école", "éducation", "coaching", "entreprise", "vente",
        "succès", "santé", "fitness", "yoga", "créativité", "musique",
        "spiritualité", "anglais", "français", "immobilier", "crypto", "enligne",
        "indépendant", "liberté", "finance", "gagner", "trading",
    ),
    "chinese": (
        "课程", "社区", "商业", "营销", "钱", "投资", "学习", "学校",
        "教育", "教练", "公司", "销售", "成功", "健康", "健身", "瑜伽",
        "创意", "音乐", "灵性", "英语", "中文", "房地产", "加密", "线上",
        "独立", "自由", "金融", "赚钱", "交易",
    ),
    "italian": (
        "corso", "comunità", "affari", "marketing", "soldi", "investire",
        "imparare", "scuola", "educazione", "coaching", "azienda", "vendite",
        "successo", "salute", "fitness", "yoga", "creatività", "musica",
        "spiritualità", "inglese", "italiano", "immobili", "crypto", "online",
        "indipendente", "libertà", "finanza", "guadagnare", "trading",
    ),
    "dutch": (
        "cursus", "gemeenschap", "zaken", "marketing", "geld", "investeren",
        "leren", "school", "onderwijs", "coaching", "bedrijf", "verkoop",
        "succes", "gezondheid", "fitness", "yoga", "creativiteit", "muziek",
        "spiritualiteit", "engels", "nederlands", "onroerend", "crypto",
        "online", "zelfstandig", "vrijheid", "financiën", "verdienen", "trading",
    ),
    "vietnamese": (
        "khóa học", "cộng đồng", "kinh doanh", "tiếp thị", "tiền", "đầu tư",
        "học tập", "trường", "giáo dục", "huấn luyện", "công ty", "bán hàng",
        "thành công", "sức khỏe", "thể dục", "yoga", "sáng tạo", "âm nhạc",
        "tâm linh", "tiếng anh", "tiếng việt", "bất động sản", "tiền điện tử",
        "trực tuyến", "tự do", "tài chính", "kiếm tiền",
    ),
    "arabic": (
        "دورة", "مجتمع", "أعمال", "تسويق", "مال", "استثمار", "تعلم",
        "مدرسة", "تعليم", "تدريب", "شركة", "مبيعات", "نجاح", "صحة",
        "لياقة", "يوجا", "إبداع", "موسيقى", "روحانية", "إنجليزية", "عربية",
        "عقارات", "عملات رقمية", "أونلاين", "استقلال", "حرية", "تمويل",
        "كسب المال", "تداول",
    ),
    "hebrew": (
        "קורס", "קהילה", "עסקים", "שיווק", "כסף", "השקעות", "ללמוד",
        "בית ספר", "חינוך", "אימון", "חברה", "מכירות", "הצלחה", "בריאות",
        "כושר", "יוגה", "יצירתיות", "מוזיקה", "רוחניות", "אנגלית", "עברית",
        "נדל\"ן", "קריפטו", "אונליין", "עצמאי", "חופש", "פיננסים", "מסחר",
    ),
    "russian": (
        "курс", "сообщество", "бизнес", "маркетинг", "деньги", "инвестиции",
        "учить", "школа", "образование", "коучинг", "компания", "продажи",
        "успех", "здоровье", "фитнес", "йога", "творчество", "музыка",
        "духовность", "английский", "русский", "недвижимость", "крипто",
        "онлайн", "самостоятельный", "свобода", "финансы", "заработок",
        "трейдинг",
    ),
    "portuguese": (
        "curso", "comunidade", "negócio", "marketing", "dinheiro", "investir",
        "aprender", "escola", "educação", "coaching", "empresa", "vendas",
        "sucesso", "saúde", "fitness", "yoga", "criatividade", "música",
        "espiritualidade", "inglês", "português", "imóveis", "cripto",
        "online", "independente", "liberdade", "finanças", "ganhar", "trading",
    ),
    "swedish": (
        "kurs", "gemenskap", "affärer", "marknadsföring", "pengar", "investera",
        "lära", "skola", "utbildning", "coaching", "företag", "försäljning",
        "framgång", "hälsa", "fitness", "yoga", "kreativitet", "musik",
        "andlighet", "engelska", "svenska", "fastigheter", "krypto", "online",
        "självständig", "frihet", "ekonomi", "tjäna", "trading",
    ),
    "polish": (
        "kurs", "społeczność", "biznes", "marketing", "pieniądze", "inwestować",
        "uczyć", "szkoła", "edukacja", "coaching", "firma", "sprzedaż",
        "sukces", "zdrowie", "fitness", "joga", "kreatywność", "muzyka",
        "duchowość", "angielski", "polski", "nieruchomości", "krypto",
        "online", "niezależny", "wolność", "finanse", "zarabiać", "trading",
    ),
    "turkish": (
        "kurs", "topluluk", "iş", "pazarlama", "para", "yatırım", "öğrenmek",
        "okul", "eğitim", "koçluk", "şirket", "satış", "başarı", "sağlık",
        "fitness", "yoga", "yaratıcılık", "müzik", "maneviyat", "ingilizce",
        "türkçe", "gayrimenkul", "kripto", "çevrimiçi", "bağımsız", "özgürlük",
        "finans", "para kazanma", "trading",
    ),
    "danish": (
        "kursus", "fællesskab", "forretning", "markedsføring", "penge",
        "investere", "lære", "skole", "uddannelse", "coaching", "virksomhed",
        "salg", "succes", "sundhed", "fitness", "yoga", "kreativitet", "musik",
        "spiritualitet", "engelsk", "dansk", "ejendomme", "krypto", "online",
        "selvstændig", "frihed", "økonomi", "tjene", "trading",
    ),
    "japanese": (
        "コース", "コミュニティ", "ビジネス", "マーケティング", "お金", "投資",
        "学ぶ", "学校", "教育", "コーチング", "会社", "販売", "成功", "健康",
        "フィットネス", "ヨガ", "創造性", "音楽", "精神性", "英語", "日本語",
        "不動産", "暗号通貨", "オンライン", "独立", "自由", "金融", "稼ぐ",
        "トレーディング",
    ),
    "korean": (
        "과정", "커뮤니티", "비즈니스", "마케팅", "돈", "투자", "배우기",
        "학교", "교육", "코칭", "회사", "판매", "성공", "건강", "피트니스",
        "요가", "창의성", "음악", "영성", "영어", "한국어", "부동산", "암호화폐",
        "온라인", "독립", "자유", "금융", "벌기", "트레이딩",
    ),
    "catalan": (
        "curs", "comunitat", "negoci", "màrqueting", "diners", "invertir",
        "aprendre", "escola", "educació", "coaching", "empresa", "vendes",
        "èxit", "salut", "fitness", "ioga", "creativitat", "música",
        "espiritualitat", "anglès", "català", "immobles", "cripto", "online",
        "independent", "llibertat", "finances", "guanyar", "trading",
    ),
    "indonesian": (
        "kursus", "komunitas", "bisnis", "pemasaran", "uang",
        "investasi", "belajar", "sekolah", "pendidikan", "coaching", "perusahaan",
        "penjualan", "sukses", "kesehatan", "kebugaran", "yoga", "kreativitas",
        "musik", "spiritualitas", "inggris", "indonesia", "properti", "kripto",
        "online", "mandiri", "kebebasan", "keuangan", "menghasilkan", "trading",
    ),
    "filipino": (
        "kurso", "komunidad", "negosyo", "marketing", "pera", "pamumuhunan",
        "matuto", "paaralan", "edukasyon", "coaching", "kumpanya", "benta",
        "tagumpay", "kalusugan", "fitness", "yoga", "kreatibidad", "musika",
        "espirituwalidad", "ingles", "filipino", "property", "crypto", "online",
        "independyente", "kalayaan", "pananalapi", "kumita", "trading",
    ),
    "thai": (
        "คอร์ส", "ชุมชน", "ธุรกิจ", "การตลาด", "เงิน", "การลงทุน", "เรียนรู้",
        "โรงเรียน", "การศึกษา", "โค้ชชิ่ง", "บริษัท", "ขาย", "ความสำเร็จ",
        "สุขภาพ", "ฟิตเนส", "โยคะ", "ความคิดสร้างสรรค์", "ดนตรี", "จิตวิญญาณ",
        "อังกฤษ", "ไทย", "อสังหาริมทรัพย์", "คริปโต", "ออนไลน์", "อิสระ",
        "เสรีภาพ", "การเงิน", "หารายได้", "เทรดดิ้ง",
    ),
    "persian": (
        "دوره", "جامعه", "کسب و کار", "بازاریابی", "پول", "سرمایه‌گذاری",
        "یادگیری", "مدرسه", "آموزش", "مربیگری", "شرکت", "فروش", "موفقیت",
        "سلامت", "تناسب اندام", "یوگا", "خلاقیت", "موسیقی", "معنویت",
        "انگلیسی", "فارسی", "املاک", "کریپتو", "آنلاین", "مستقل", "آزادی",
        "مالی", "کسب درآمد", "معامله",
    ),
    "hindi": (
        "कोर्स", "समुदाय", "व्यापार", "मार्केटिंग", "पैसा", "निवेश",
        "सीखना", "स्कूल", "शिक्षा", "कोचिंग", "कंपनी", "बिक्री", "सफलता",
        "स्वास्थ्य", "फिटनेस", "योग", "रचनात्मकता", "संगीत", "आध्यात्मिकता",
        "अंग्रेजी", "हिंदी", "रियल एस्टेट", "क्रिप्टो", "ऑनलाइन", "स्वतंत्र",
        "स्वतंत्रता", "वित्त", "कमाना", "ट्रेडिंग",
    ),
    "greek": (
        "μάθημα", "κοινότητα", "επιχείρηση", "μάρκετινγκ", "χρήματα",
        "επένδυση", "μαθαίνω", "σχολείο", "εκπαίδευση", "κόουτσινγκ",
        "εταιρεία", "πωλήσεις", "επιτυχία", "υγεία", "γυμναστική", "γιόγκα",
        "δημιουργικότητα", "μουσική", "πνευματικότητα", "αγγλικά", "ελληνικά",
        "ακίνητα", "κρύπτο", "διαδικτυακά", "ανεξάρτητος", "ελευθερία",
        "οικονομικά", "κερδίζω", "συναλλαγές",
    ),
    "ukrainian": (
        "курс", "спільнота", "бізнес", "маркетинг", "гроші", "інвестиції",
        "вчити", "школа", "освіта", "коучинг", "компанія", "продажі",
        "успіх", "здоров'я", "фітнес", "йога", "творчість", "музика",
        "духовність", "англійська", "українська", "нерухомість", "крипто",
        "онлайн", "незалежний", "свобода", "фінанси", "заробіток", "трейдинг",
    ),
    "swahili": (
        "kozi", "jamii", "biashara", "masoko", "pesa", "uwekezaji", "kujifunza",
        "shule", "elimu", "coaching", "kampuni", "mauzo", "mafanikio", "afya",
        "fitness", "yoga", "ubunifu", "muziki", "kiroho", "kiingereza",
        "kiswahili", "mali isiyohamishika", "kripto", "mtandaoni", "uhuru",
        "fedha", "kupata", "biashara ya hisa",
    ),
    "malay": (
        "kursus", "komuniti", "perniagaan", "pemasaran", "wang", "pelaburan",
        "belajar", "sekolah", "pendidikan", "coaching", "syarikat", "jualan",
        "kejayaan", "kesihatan", "kecergasan", "yoga", "kreativiti", "muzik",
        "kerohanian", "inggeris", "melayu", "hartanah", "kripto", "dalam talian",
        "berdikari", "kebebasan", "kewangan", "menjana", "trading",
    ),
    "latin": (
        "cursus", "communitas", "negotium", "mercatura", "pecunia", "investire",
        "discere", "schola", "educatio", "coaching", "societas", "venditio",
        "successus", "salus", "fitness", "yoga", "creativitas", "musica",
        "spiritualitas", "anglica", "latina", "praedia", "crypto", "online",
        "independens", "libertas", "financia", "lucrari", "trading",
    ),
    "bengali": (
        "কোর্স", "সম্প্রদায়", "ব্যবসা", "মার্কেটিং", "টাকা", "বিনিয়োগ",
        "শেখা", "স্কুল", "শিক্ষা", "কোচিং", "কোম্পানি", "বিক্রয়", "সফলতা",
        "স্বাস্থ্য", "ফিটনেস", "যোগ", "সৃজনশীলতা", "সঙ্গীত", "আধ্যাত্মিকতা",
        "ইংরেজি", "বাংলা", "রিয়েল এস্টেট", "ক্রিপ্টো", "অনলাইন", "স্বাধীন",
        "স্বাধীনতা", "অর্থ", "আয়", "ট্রেডিং",
    ),
    "norwegian": (
        "kurs", "fellesskap", "forretning", "markedsføring", "penger",
        "investere", "lære", "skole", "utdanning", "coaching", "selskap",
        "salg", "suksess", "helse", "fitness", "yoga", "kreativitet", "musikk",
        "spiritualitet", "engelsk", "norsk", "eiendom", "krypto", "online",
        "selvstendig", "frihet", "økonomi", "tjene", "trading",
    ),
    "finnish": (
        "kurssi", "yhteisö", "liiketoiminta", "markkinointi", "raha",
        "sijoittaa", "oppia", "koulu", "koulutus", "coaching", "yritys",
        "myynti", "menestys", "terveys", "kunto", "jooga", "luovuus", "musiikki",
        "henkisyys", "englanti", "suomi", "kiinteistöt", "krypto", "verkossa",
        "itsenäinen", "vapaus", "rahoitus", "ansaita", "kaupankäynti",
    ),
    "czech": (
        "kurz", "komunita", "byznys", "marketing", "peníze", "investovat",
        "učit", "škola", "vzdělání", "coaching", "firma", "prodej", "úspěch",
        "zdraví", "fitness", "jóga", "kreativita", "hudba", "spiritualita",
        "angličtina", "čeština", "nemovitosti", "krypto", "online",
        "nezávislý", "svoboda", "finance", "vydělávat", "trading",
    ),
    "croatian": (
        "tečaj", "zajednica", "posao", "marketing", "novac", "investirati",
        "učiti", "škola", "obrazovanje", "coaching", "tvrtka", "prodaja",
        "uspjeh", "zdravlje", "fitness", "joga", "kreativnost", "glazba",
        "duhovnost", "engleski", "hrvatski", "nekretnine", "kripto", "online",
        "neovisan", "sloboda", "financije", "zarađivati", "trading",
    ),
    "romanian": (
        "curs", "comunitate", "afacere", "marketing", "bani", "investiții",
        "învăța", "școală", "educație", "coaching", "companie", "vânzări",
        "succes", "sănătate", "fitness", "yoga", "creativitate", "muzică",
        "spiritualitate", "engleză", "română", "imobiliare", "cripto", "online",
        "independent", "libertate", "finanțe", "câștiga", "trading",
    ),
    "bulgarian": (
        "курс", "общност", "бизнес", "маркетинг", "пари", "инвестиции",
        "уча", "училище", "образование", "коучинг", "компания", "продажби",
        "успех", "здраве", "фитнес", "йога", "креативност", "музика",
        "духовност", "английски", "български", "недвижими имоти", "крипто",
        "онлайн", "независим", "свобода", "финанси", "печеля", "трейдинг",
    ),
    "slovenian": (
        "tečaj", "skupnost", "posel", "marketing", "denar", "investirati",
        "učiti", "šola", "izobraževanje", "coaching", "podjetje", "prodaja",
        "uspeh", "zdravje", "fitness", "joga", "ustvarjalnost", "glasba",
        "duhovnost", "angleščina", "slovenščina", "nepremičnine", "kripto",
        "online", "neodvisen", "svoboda", "finance", "zaslužiti", "trading",
    ),
    "slovak": (
        "kurz", "komunita", "obchod", "marketing", "peniaze", "investovať",
        "učiť", "škola", "vzdelanie", "coaching", "firma", "predaj", "úspech",
        "zdravie", "fitness", "jóga", "kreativita", "hudba", "spiritualita",
        "angličtina", "slovenčina", "nehnuteľnosti", "krypto", "online",
        "nezávislý", "sloboda", "financie", "zarábať", "trading",
    ),
    "serbian": (
        "kurs", "zajednica", "biznis", "marketing", "novac", "investirati",
        "učiti", "škola", "obrazovanje", "coaching", "kompanija", "prodaja",
        "uspeh", "zdravlje", "fitness", "joga", "kreativnost", "muzika",
        "duhovnost", "engleski", "srpski", "nekretnine", "kripto", "online",
        "nezavisan", "sloboda", "finansije", "zaraditi", "trading",
    ),
    "latvian": (
        "kurss", "kopiena", "bizness", "mārketings", "nauda", "investēt",
        "mācīties", "skola", "izglītība", "coaching", "uzņēmums", "pārdošana",
        "panākumi", "veselība", "fitness", "joga", "radošums", "mūzika",
        "garīgums", "angļu", "latviešu", "nekustamais", "kripto", "tiešsaistē",
        "neatkarīgs", "brīvība", "finanses", "nopelnīt", "tirdzniecība",
    ),
    "estonian": (
        "kursus", "kogukond", "äri", "turundus", "raha", "investeerida",
        "õppida", "kool", "haridus", "coaching", "ettevõte", "müük", "edu",
        "tervis", "fitness", "jooga", "loovus", "muusika", "vaimsus",
        "inglise", "eesti", "kinnisvara", "krüpto", "võrgus", "iseseisev",
        "vabadus", "rahandus", "teenida", "kauplemine",
    ),
    "lithuanian": (
        "kursas", "bendruomenė", "verslas", "rinkodara", "pinigai", "investuoti",
        "mokytis", "mokykla", "švietimas", "coaching", "įmonė", "pardavimai",
        "sėkmė", "sveikata", "fitness", "joga", "kūrybiškumas", "muzika",
        "dvasingumas", "anglų", "lietuvių", "nekilnojamasis", "kripto",
        "internete", "nepriklausomas", "laisvė", "finansai", "uždirbti", "trading",
    ),
    "amharic": (
        "ኮርስ", "ማህበረሰብ", "ንግድ", "ግብይት", "ገንዘብ", "ኢንቨስትመንት",
        "መማር", "ትምህርት ቤት", "ትምህርት", "አሰልጣኝ", "ኩባንያ", "ሽያጭ",
        "ስኬት", "ጤና", "አካላዊ እንቅስቃሴ", "ዮጋ", "ፈጠራ", "ሙዚቃ",
        "መንፈሳዊነት", "እንግሊዝኛ", "አማርኛ", "ሪል እስቴት", "ክሪፕቶ",
        "መስመር ላይ", "ነጻ", "ነጻነት", "ፋይናንስ", "ገቢ", "ትሬዲንግ",
    ),
    "welsh": (
        "cwrs", "cymuned", "busnes", "marchnata", "arian", "buddsoddi",
        "dysgu", "ysgol", "addysg", "hyfforddiant", "cwmni", "gwerthiant",
        "llwyddiant", "iechyd", "ffitrwydd", "ioga", "creadigrwydd", "cerddoriaeth",
        "ysbrydolrwydd", "saesneg", "cymraeg", "eiddo", "crypto", "ar-lein",
        "annibynnol", "rhyddid", "cyllid", "ennill", "masnachu",
    ),
    "cantonese": (
        "課程", "社區", "商業", "營銷", "錢", "投資", "學習", "學校",
        "教育", "教練", "公司", "銷售", "成功", "健康", "健身", "瑜伽",
        "創意", "音樂", "靈性", "英文", "粵語", "房地產", "加密貨幣",
        "線上", "獨立", "自由", "金融", "賺錢", "交易",
    ),
    "hungarian": (
        "kurzus", "közösség", "üzlet", "marketing", "pénz", "befektetés",
        "tanulás", "iskola", "oktatás", "coaching", "cég", "értékesítés",
        "siker", "egészség", "fitness", "jóga", "kreativitás", "zene",
        "szellemiség", "angol", "magyar", "ingatlan", "kripto", "online",
        "független", "szabadság", "pénzügy", "kereset", "kereskedés",
    ),
    "mongolian": (
        "сургалт", "нийгэм", "бизнес", "маркетинг", "мөнгө", "хөрөнгө оруулалт",
        "сурах", "сургууль", "боловсрол", "коучинг", "компани", "борлуулалт",
        "амжилт", "эрүүл мэнд", "фитнес", "йог", "бүтээлч", "хөгжим",
        "сүнслэг", "англи", "монгол", "үл хөдлөх", "крипто", "онлайн",
        "бие даасан", "эрх чөлөө", "санхүү", "орлого", "худалдаа",
    ),
    "haitian": (
        "kò", "kominote", "biznis", "maketing", "lajan", "envestisman",
        "aprann", "lekòl", "edikasyon", "coaching", "konpayi", "lavant",
        "siksè", "sante", "fitness", "yoga", "kreyativite", "mizik",
        "espirityalite", "angle", "kreyòl", "imobilye", "kripto", "sou entènèt",
        "endepandan", "libète", "finans", "gen", "komès",
    ),
}

# Frequent words in community names/descriptions. Covers the common Skool
# niches: business/marketing, money/investing, health/fitness, tech/AI,
# education, creative, spirituality, relationships, languages, hobbies and
# more — plus a few non-English seeds. `default_query_plan()` runs these first
# (high yield), then falls back to single letters.
KEYWORD_SEEDS: tuple[str, ...] = (
    # business / marketing / freelancing
    "academy", "agency", "affiliate", "amazon", "b2b", "b2c", "biz",
    "brand", "branding", "business", "client", "coach", "coaching",
    "consulting", "copy", "copywriting", "crm", "digital", "email", "funnel",
    "launch", "leads", "marketing", "sales", "salesforce", "seo", "smm",
    "socmed", "social", "website", "wordpress", "shopify", "etsy", "ebay",
    # money / investing / trading
    "bitcoin", "crypto", "defi", "dividend", "finance", "financial",
    "forex", "freedom", "invest", "investing", "nft", "passive", "profit",
    "revenue", "rich", "stocks", "trading", "wealth", "money", "income",
    # health / fitness / wellness
    "body", "diet", "exercise", "fasting", "fitness", "gym", "health",
    "keto", "meditation", "mental", "mindset", "muscle", "nutrition",
    "pilates", "protein", "sleep", "strength", "weight", "wellness", "yoga",
    # tech / ai / dev
    "ai", "app", "apps", "automation", "backend", "blockchain", "code",
    "coding", "computer", "data", "database", "deep", "dev", "developer",
    "engineering", "frontend", "fullstack", "gpt", "javascript", "machine",
    "ml", "openai", "programming", "python", "react", "robot", "sass",
    "saas", "security", "software", "startup", "tech", "web", "web3",
    # education / learning
    "academic", "certificate", "class", "classroom", "college", "course",
    "curriculum", "degree", "edu", "education", "exam", "grad", "graduate",
    "homework", "language", "learn", "learning", "lesson", "math", "science",
    "school", "student", "study", "teacher", "teaching", "tutor", "university",
    # creative / media / content
    "art", "artist", "audio", "book", "books", "camera", "content", "create",
    "creator", "design", "designer", "drawing", "editing", "editor", "film",
    "filmmaking", "guitar", "illustration", "music", "musician", "painting",
    "photo", "photography", "podcast", "singing", "video", "writer", "writing",
    "youtube", "streaming", "gaming", "game", "twitch", "esports",
    # career / personal growth
    "career", "cv", "freelance", "interview", "job", "leadership", "linkedin",
    "network", "networking", "productivity", "public", "speaking", "resume",
    "self", "success", "skills", "speaking", "entrepreneur", "founder",
    # relationships / family / life
    "dating", "family", "kids", "marriage", "parenting", "relationship",
    "relationships", "divorce", "baby", "men", "women", "life", "lifestyle",
    "home", "house", "garden", "cooking", "food", "travel", "dog", "cat",
    "pets", "fashion", "beauty", "makeup", "hair", "style", "fitness",
    # spirituality / self-improvement
    "astrology", "bible", "buddhism", "christian", "church", "faith",
    "god", "gratitude", "healing", "holistic", "islam", "manifest", "prayer",
    "spiritual", "spirituality", "tarot", "meditation",
    # hobbies / interests
    "chess", "craft", "dance", "diy", "gardening", "hiking", "hobby",
    "knitting", "motorcycle", "music", "photography", "poker", "running",
    "sailing", "surf", "swimming", "tennis", "travel",
    # niche communities
    "agency", "amazon", "crypto", "dropshipping", "ecom", "ecommerce",
    "forex", "golf", "mma", "nursing", "nurse", "real estate", "realestate",
    "realtor", "skool", "社群", "club", "tribe", "society", "network", "hub",
    "lab", "studio", "mastermind", "community",
    # non-English seeds (Skool hosts many languages)
    "aprende", "curso", "negocio", "dinero", "marketing", "emprendedor",
    "bildung", "geld", "kurs", "geschäft", "lernen", "schule",
    "défi", "argent", "cours", "affaires", "apprendre",
    "corso", "imparare", "soldi", "affari", "scuola",
    "curso", "aprender", "negócio", "dinheiro",
    "курс", "бизнес", "деньги", "обучение", "заработок",
    "kurs", "naucz", "pieniądze", "biznes",
    "คอร์ส", "ธุรกิจ", "เงิน", "เรียน",
    "kursus", "belajar", "bisnis", "uang",
)

# Extra multi-word and longer-tail phrases often used in Skool group names.
KEYWORD_PHRASES: tuple[str, ...] = (
    "artificial intelligence", "digital marketing", "real estate",
    "passive income", "online business", "content creation", "personal brand",
    "day trading", "crypto trading", "stock market", "weight loss",
    "online course", "social media", "copywriting course", "web development",
    "machine learning", "lead generation", "email marketing", "side hustle",
    "financial freedom", "high ticket", "course creation",
    # more long-tail
    "affiliate marketing", "blogging", "brand building", "business coaching",
    "career change", "crypto investing", "customer acquisition", "data science",
    "digital products", "ecommerce store", "facebook ads", "freelance writing",
    "growth hacking", "instagram growth", "online coaching", "personal finance",
    "product launch", "public speaking", "retirement planning", "seo services",
    "small business", "social proof", "video editing", "web design",
    "content strategy", "email list", "sales funnel", "tiktok growth",
    "youtube automation", "ai tools", "chatgpt", "midjourney", "prompt engineering",
    "sports betting", "cricket", "football", "soccer", "basketball", "boxing",
    "bodybuilding", "running club", "cycling", "hiking group", "fishing",
    "hunting", "camping", "photography tips", "filmmaking course",
    "drawing tutorial", "painting course", "writing community",
    "poetry", "storytelling", "screenwriting", "comedy", "improv",
    "dance class", "ballet", "hip hop", "salsa", "piano", "violin", "singing",
    "language learning", "spanish course", "english speaking", "french course",
    "german course", "japanese learning", "korean learning", "chinese learning",
    "meditation course", "mindfulness", "breathwork", "cold plunge",
    "biohacking", "longevity", "anti aging", "hormone health", "women health",
    "men health", "gut health", "mental health", "anxiety", "depression",
    "addiction recovery", "sober living", "quitting smoking", "no fap",
    "bible study", "prayer group", "worship", "worship music", "prophecy",
    "end times", "missions", "youth group", "mens group", "womens group",
    "couples retreat", "dating advice", "marriage advice", "single parents",
    "adoption", "foster care", "homeschool", "unschooling", "montessori",
    "college admissions", "study abroad", "scholarship", "test prep",
    "sat prep", "toefl", "ielts", "gmat", "gre", "mcat", "lsat",
    "real estate investing", "wholesaling", "fix and flip", "property management",
    "airbnb", "vacation rental", "mortgage", "credit repair", "credit score",
    "debt free", "budgeting", "frugal living", "minimalism", "tiny house",
    "van life", "digital nomad", "remote work", "work from home", "freelancer",
    "side business", "passive income ideas", "crypto airdrop", "nft art",
    "metaverse", "web3 community", "defi farming", "staking", "solana",
    "ethereum", "bitcoin mining", "day trade", "swing trade", "options trading",
    "futures trading", "forex trading", "stock analysis", "dividend investing",
    "value investing", "index funds", "etf", "retirement", "401k", "ira",
    "insurance", "tax strategy", "accounting", "bookkeeping", "payroll",
    "human resources", "recruiting", "sales training", "cold calling",
    "cold email", "appointment setting", "closing deals", "negotiation",
    "pricing strategy", "product management", "project management", "agile",
    "scrum", "devops", "cloud computing", "aws", "azure", "kubernetes",
    "cybersecurity", "ethical hacking", "penetration testing", "bug bounty",
    "blockchain development", "smart contracts", "solidity", "rust",
    "golang", "typescript", "nextjs", "tailwind", "flutter", "react native",
    "ios development", "android development", "game development", "unity",
    "unreal", "blender", "3d modeling", "animation", "motion graphics",
    "ui design", "ux design", "product design", "graphic design", "logo design",
    "brand identity", "print on demand", "t shirt design", "merch",
    "podcast editing", "video production", "youtube channel", "twitch stream",
    "discord community", "telegram group", "substack", "newsletter",
    "community building", "membership site", "course platform", "teachable",
    "kajabi", "clickfunnels", "activecampaign", "convertkit", "sendgrid",
    "notion", "obsidian", "roam", "productivity system", "time management",
    "goal setting", "habit building", "morning routine", "journaling",
    "gratitude journal", "vision board", "manifestation", "law of attraction",
    "numpy", "pandas", "tensorflow", "pytorch", "r programming", "sql",
    "excel", "google sheets", "power bi", "tableau", "data analytics",
    "business intelligence", "sap", "oracle", "wordpress plugin",
    "shopify store", "amazon fba", "amazon kdp", "kindle publishing",
    "self publishing", "ghostwriting", "copywriting tips", "content writing",
    "technical writing", "grant writing", "screenwriting course",
)

# Non-Latin / multi-script query seeds. Skool hosts communities in many
# scripts; a pure Latin-only query plan would miss groups whose names use
# CJK, Cyrillic, Arabic, Hebrew, Hangul, Kana or Indic scripts. These short
# single-script tokens (one per script) act as catch-alls: any group name in
# that script contains at least one of them.
NON_LATIN_SEEDS: tuple[str, ...] = (
    # CJK (Chinese, Japanese kanji, Korean hangul)
    "学", "学び", "会", "社", "部", "教", "日本語", "中国", "한국", "커뮤니티", "배움",
    # Cyrillic (Russian, Ukrainian, Bulgarian, Serbian)
    "сообщество", "бизнес", "обучение", "курс", "клуб", "сообщ", "учёба", "заработок",
    # Arabic / Persian
    "مجتمع", "تعلم", "دورة", "مال", "تداول", "كورس", "جروب", "بیزنس", "آموزش", "پول",
    # Hebrew
    "קהילה", "ללמוד", "עסק", "כסף", "מסחר",
    # Greek
    "κοινότητα", "μάθηση", "επιχείρηση", "χρήματα",
    # Thai
    "ชุมชน", "เรียน", "ธุรกิจ", "เงิน",
    # Vietnamese
    "cộng đồng", "học", "kinh doanh", "tiền",
    # Indonesian / Malay
    "komunitas", "belajar", "bisnis", "uang",
    # Hindi / Indic
    "समुदाय", "सीखें", "व्यापार", "पैसा",
    # Japanese hiragana/katakana
    "コミュニティ", "ビジネス", "マーケティング",
)

# The english search plan is the generic keyword set.
LANGUAGE_QUERIES["english"] = KEYWORD_SEEDS


def alphabet_queries() -> list[str]:
    """Single letters and digits."""
    return list(string.ascii_lowercase) + list(string.digits)


def bigram_queries() -> list[str]:
    """Two-letter combos — for when single letters hit the cap."""
    letters = string.ascii_lowercase
    return [a + b for a, b in itertools.product(letters, letters)]


def default_query_plan(include_bigrams: bool = True) -> list[str]:
    """Default query order, ordered by yield:

      1. high-yield keyword seeds (most specific, best signal)
      2. multi-word phrases
      3. non-Latin single-script tokens (catches CJK/Cyrillic/Arabic… names)
      4. single letters + digits
      5. bigrams (aa…zz) — the exhaustive fallback: every ASCII group name
         of length >= 2 contains at least one bigram, so running them all
         guarantees near-total ASCII coverage (at the cost of ~676 queries).

    Set `include_bigrams=False` to stop before the bigram sweep.
    """
    seen: set[str] = set()
    plan: list[str] = []
    for term in (
        list(KEYWORD_SEEDS)
        + list(KEYWORD_PHRASES)
        + list(NON_LATIN_SEEDS)
        + alphabet_queries()
        + (bigram_queries() if include_bigrams else [])
    ):
        if term not in seen:
            seen.add(term)
            plan.append(term)
    return plan
