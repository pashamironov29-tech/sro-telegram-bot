"""ИИ-помощник СРО: OpenRouter → GigaChat (РФ) → Groq подбирает раздел srogen.ru."""

import re
from difflib import SequenceMatcher

import requests

try:
    from config_keys import OPENROUTER_API_KEY as _CFG_OR_KEY
    from config_keys import OPENROUTER_MODEL as _CFG_OR_MODEL
except ImportError:
    _CFG_OR_KEY = ""
    _CFG_OR_MODEL = "openai/gpt-4.1-mini"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4.1-mini"

try:
    from gigachat_client import chat_completion as _gigachat_chat
    from gigachat_client import credentials_configured as _gigachat_ok
except ImportError:
    def _gigachat_ok():
        return False

    def _gigachat_chat(*_a, **_k):
        raise RuntimeError("gigachat_unavailable")

from partners_data import format_partner_response, get_partners_full_text, match_partner_query
from sro_site_qa import format_sro_site_qa_response, match_sro_site_qa
from voprosy_faq import (
    check_activity_question_conflict,
    format_voprosy_faq_response,
    get_voprosy_item_for_topic,
    match_voprosy_faq,
)

# Карта разделов сайта — можно добавлять новые URL по мере необходимости
SITE_TOPICS = {
    "plan_proverok": {
        "title": "План контрольных проверок",
        "url": "https://www.srogen.ru/kontrol_sro/kontrolniy_komitet/plan_proverok/",
        "description": (
            "план проверок, планы проверок, расписание проверок, график проверок, "
            "когда проверка, сроки проверки, контрольная проверка по месяцам, "
            "календарь проверок"
        ),
    },
    "resultaty_proverok": {
        "title": "Результаты контрольных проверок",
        "url": "https://www.srogen.ru/kontrol_sro/kontrolniy_komitet/resultaty_proverok/",
        "description": (
            "результаты проверок, итоги проверки, сводка проверок за месяц, "
            "сколько проверено с нарушениями и без, статистика контрольных проверок"
        ),
    },
    "perechen_dokumentov": {
        "title": "Перечень проверяемых документов",
        "url": "https://www.srogen.ru/kontrol_sro/kontrolniy_komitet/perechen_documentov/",
        "description": (
            "какие документы нужны для проверки, перечень документов при контроле, "
            "доверенность на проверку, информационный лист, документы для контрольного комитета"
        ),
    },
    "kontrol_sro": {
        "title": "Контроль СРО",
        "url": "https://www.srogen.ru/kontrol_sro/",
        "description": (
            "контроль СРО, контрольный комитет, контроль деятельности членов, "
            "внеплановая проверка, общая информация о контроле"
        ),
    },
    "ob_organizacii_kontrolya": {
        "title": "Об организации контроля",
        "url": "https://www.srogen.ru/kontrol_sro/ob_organizacii/",
        "description": (
            "об организации контроля, как организован контроль в СРО, "
            "положение о контроле, контрольный комитет, порядок проведения проверок"
        ),
    },
    "ustranenie_narusheniy": {
        "title": "Устранение нарушений",
        "url": "https://www.srogen.ru/kontrol_sro/ustranenie_narusheniy/",
        "description": (
            "устранение нарушений, как устранить нарушения, срок устранения нарушений, "
            "нарушения по итогам проверки, исправление нарушений, отчёт об устранении"
        ),
    },
    "nok": {
        "title": "Независимая оценка квалификации (НОК)",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/nok/",
        "description": (
            "НОК, независимая оценка квалификации, экзамен НОК, свидетельство НОК, "
            "сроки сдачи НОК, правила сдачи НОК, ЦОК, какие документы нужны для НОК, "
            "документы для сдачи НОК, документы для независимой оценки квалификации, "
            "что такое нок"
        ),
    },
    "nok_obuchenie": {
        "title": "Подготовка к независимой оценке квалификации",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/obuchenie/",
        "description": (
            "подготовка к НОК, обучение перед НОК, курсы подготовки к НОК, "
            "предэкзаменационная подготовка, как подготовиться к НОК, обучение специалистов"
        ),
    },
    "vstuplenie": {
        "title": "Вступление в СРО",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/",
        "description": (
            "как вступить в СРО, заявка на вступление, документы для вступления, "
            "требования к компании, приём в СРО, новый член"
        ),
    },
    "o_sro": {
        "title": "Об Ассоциации и СРО",
        "url": "https://www.srogen.ru/sro/",
        "description": (
            "что такое СРО, что такое саморегулируемая организация, зачем нужно СРО, "
            "что даёт членство, об ассоциации, саморегулирование в строительстве, "
            "общая информация о СРО, кто такие СРО строителей"
        ),
    },
    "chlenstvo_info": {
        "title": "О членстве в СРО",
        "url": "https://www.srogen.ru/chlenam_sro/informacija_dlja_chlenov_sro/",
        "description": (
            "о членстве в СРО, информация для членов, права и обязанности членов, "
            "действующим членам, информация для действующих членов СРО"
        ),
    },
    "vznosy": {
        "title": "Вступление в СРО — взносы и условия",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/zayavka/",
        "description": (
            "размер взносов, таблица взносов, КФ ВВ, КФ ОДО, компенсационный фонд, "
            "членские взносы, вступительный взнос, стоимость вступления, "
            "уровни ответственности, сколько стоит вступить, размеры взносов"
        ),
    },
    "nrs": {
        "title": "Специалисты и НРС",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/vnesenie-v-reestr/",
        "description": (
            "НРС, национальный реестр специалистов, кураторы НРС, "
            "документы в НРС, квалификационный состав"
        ),
    },
    "vnesenie_v_reestr_spec": {
        "title": "Внесение в реестр специалистов",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/vnesenie-v-reestr/",
        "description": (
            "внесение в реестр специалистов, включение специалиста в реестр, "
            "подача документов на специалиста, добавить специалиста в НРС"
        ),
    },
    "reestr_chlenov": {
        "title": "Реестр членов СРО",
        "url": "https://www.srogen.ru/reestr/",
        "description": (
            "реестр членов СРО, реестр организаций, список членов, "
            "найти компанию в реестре, проверить членство в реестре"
        ),
    },
    "poluchenie_vypiski": {
        "title": "Получение выписки",
        "url": "https://www.srogen.ru/chlenam_sro/poluchenie_vypiski/",
        "description": (
            "получение выписки, как получить выписку, выписка из реестра, "
            "запрос выписки, выписка из реестра членов СРО"
        ),
    },
    "lichniy_kabinet": {
        "title": "Личный кабинет члена СРО",
        "url": "https://www.srogen.ru/chlenam_sro/lichniy_kabinet/",
        "description": (
            "личный кабинет, личный кабинет члена СРО, доступ к личному кабинету, "
            "логин и пароль кабинета, partner@srogen.ru, кабинет на сайте СРО"
        ),
    },
    "reestr": {
        "title": "Изменения в реестр",
        "url": "https://www.srogen.ru/chlenam_sro/dlja_pereoformlenija/",
        "description": (
            "изменения в реестр, внесение изменений, переоформление, "
            "обновление сведений об организации, изменить данные в реестре"
        ),
    },
    "zakonodatelstvo": {
        "title": "Законодательство",
        "url": "https://www.srogen.ru/zakonodatelstvo/",
        "description": "законы, нормативные акты, Градостроительный кодекс, правила и положения СРО",
    },
    "novosti": {
        "title": "Новости и срочная информация",
        "url": "https://www.srogen.ru/novosti/",
        "description": "новости СРО, срочные сообщения, объявления, изменения в законах, мошенники",
    },
    "kontakty": {
        "title": "Контакты Ассоциации",
        "url": "https://www.srogen.ru/kontakty/",
        "description": "контакты, телефоны, адрес офиса, филиалы, представители в регионах, связаться",
    },
    "obrasheniya": {
        "title": "Жалобы и обращения",
        "url": "https://www.srogen.ru/kontakty/zhaloby_i_predlozheniya/",
        "description": "жалобы, предложения, обратная связь, телефон доверия, написать в ассоциацию",
    },
    "nostroy_reestr": {
        "title": "Реестр СРО НОСТРОЙ",
        "url": "https://reestr.nostroy.ru/frame/?path=aHR0cDovL3JlZXN0ci5ub3N0cm95LnJ1L3JlZXN0ci9jbGllbnRzLzg3L21lbWJlcnM",
        "description": (
            "НОСТРОЙ, реестр НОСТРОЙ, реестр СРО НОСТРОЙ, реестр членов НОСТРОЙ, "
            "организации в НОСТРОЙ, члены НОСТРОЙ"
        ),
    },
    "nostroy_nrs": {
        "title": "Реестр специалистов НРС НОСТРОЙ",
        "url": "https://nrs.nostroy.ru/",
        "description": (
            "НРС НОСТРОЙ, реестр специалистов НОСТРОЙ, реестр НРС строителей, "
            "проверить специалиста НОСТРОЙ, национальный реестр специалистов НОСТРОЙ"
        ),
    },
    "nopriz_nrs": {
        "title": "Реестр специалистов НРС НОПРИЗ",
        "url": "https://nrs.nopriz.ru/",
        "description": (
            "НОПРИЗ, реестр НОПРИЗ, реестр НРС НОПРИЗ, реестр специалистов НОПРИЗ, "
            "проектировщики, изыскатели, проверить специалиста НОПРИЗ"
        ),
    },
    "sroki_vstuplenie": {
        "title": "Сроки вступления в СРО",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/",
        "description": (
            "сроки рассмотрения заявки, сроки вступления, сколько ждать вступление, когда примут в СРО, "
            "срок рассмотрения документов, как долго рассматривают заявку, 7 рабочих дней"
        ),
    },
    "vozvrat_vznosa": {
        "title": "Возврат взноса",
        "url": "https://www.srogen.ru/voprosy/",
        "description": (
            "возврат взноса, вернуть взнос, возврат компенсационного фонда, "
            "выход из СРО возврат денег, вернуть КФ ВВ, вернуть КФ ОДО"
        ),
    },
    "stroitelstvo_dlya_sebya": {
        "title": "Строительство для себя",
        "url": "https://www.srogen.ru/voprosy/",
        "description": (
            "строительство для себя, нужно ли СРО для себя, строю дом для себя, "
            "строительство без договора подряда, СРО для частного дома"
        ),
    },
    "trebovaniya_spec": {
        "title": "Требования к специалистам",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/vnesenie-v-reestr/",
        "description": (
            "требования к специалистам, минимум 2 специалиста, квалификационный состав, "
            "штат специалистов, особо опасные объекты руководители, требования к кадрам"
        ),
    },
    "dokumenty_nrs": {
        "title": "Документы для внесения в НРС",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/vnesenie-v-reestr/",
        "description": (
            "документы в НРС, документы для НРС, какие документы на специалиста, "
            "7 документов НРС, пакет документов специалиста, заявление в НРС"
        ),
    },
    "zhaloby": {
        "title": "Жалобы и предложения",
        "url": "https://www.srogen.ru/kontakty/zhaloby_i_predlozheniya/",
        "description": (
            "жалоба, жалобы, предложения, обратная связь, телефон доверия, "
            "написать жалобу, форма обращения"
        ),
    },
    "filialy": {
        "title": "Филиалы и представительства",
        "url": "https://www.srogen.ru/kontakty/predstavitelstva/",
        "description": (
            "филиал, филиалы, представительство, представитель в регионе, "
            "офис в регионе, контакты филиала"
        ),
    },
    "partnery": {
        "title": "Партнёры и НО",
        "url": "https://www.srogen.ru/kontakty/partnery/",
        "description": (
            "партнёры, партнеры, научные организации, учебный центр РСС, "
            "НО партнёры, сотрудничество"
        ),
    },
    "charity": {
        "title": "Благотворительность",
        "url": "https://www.srogen.ru/sro/charity/",
        "description": (
            "благотворительность, благотворительный фонд, помощь, "
            "социальные программы СРО"
        ),
    },
    "blanki_proverka": {
        "title": "Бланки для проверки (контроль СРО)",
        "url": "https://www.srogen.ru/kontrol_sro/kontrolniy_komitet/perechen_documentov/",
        "description": (
            "бланки для проверки, документы для контрольной проверки, доверенность на проверку, "
            "информационный лист, заявление на проверку, положение о контроле — скачать в боте"
        ),
    },
    "blanki_vstuplenie": {
        "title": "Бланки для вступления в СРО",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/",
        "description": (
            "бланки для вступления, заявление о приёме, документы для вступления, "
            "формы для нового члена СРО"
        ),
    },
    "blanki_odo": {
        "title": "Уведомление об ОДО — договоры подряда",
        "url": "https://www.srogen.ru/novosti/srochno/predostavlenie_informatsii_o_dogovorakh_podryada_05032026/",
        "description": (
            "бланк ОДО, уведомление ОДО, уведомление о фактическом совокупном размере "
            "обязательств, договоры подряда, форма уведомления о заключённых контрактах"
        ),
    },
    "blanki_reestr": {
        "title": "Заявление об изменениях в реестре",
        "url": "https://www.srogen.ru/chlenam_sro/dlja_pereoformlenija/",
        "description": (
            "бланк изменений в реестр, заявление о внесении изменений, "
            "переоформление, обновить сведения в реестре — скачать в боте"
        ),
    },
    "blanki_menu": {
        "title": "Бланки и формы — выберите тип",
        "url": "https://www.srogen.ru/vstuplenie_v_sro/",
        "description": (
            "бланки, скачать бланк, формы, шаблоны — уточните: для проверки, "
            "для вступления, ОДО или изменения в реестре"
        ),
    },
}

# Быстрый поиск по ключевым словам — надёжнее, чем только ИИ
KEYWORD_RULES = [
    ("o_sro", [
        "что такое сро", "что такое саморегулир", "что такое саморегулируемая",
        "зачем нужно сро", "зачем сро", "что значит сро", "что такое sro",
        "общая информация о сро", "саморегулирование в строительстве",
        "кто такие сро", "что такое сро в строительстве", "об ассоциации",
    ]),
    ("stroitelstvo_dlya_sebya", [
        "строительство для себя", "строю для себя", "дом для себя",
        "нужно ли сро для себя", "без договора подряда",
    ]),
    ("vozvrat_vznosa", [
        "возврат взноса", "вернуть взнос", "вернуть деньги", "возврат кф",
        "возврат компенсационного", "выход из сро возврат",
        "комфонд", "комфонды",
    ]),
    ("sroki_vstuplenie", [
        "срок рассмотрения", "сроки рассмотрения", "срок вступления", "сроки вступления",
        "сколько ждать вступление", "когда примут", "как долго рассматривают",
        "сколько дней прием", "7 рабочих",
    ]),
    ("resultaty_proverok", [
        "результат проверки", "результаты проверок", "итоги проверки", "итоги проверок",
        "акт проверки", "итоги контрольной проверки", "нарушения по проверке",
    ]),
    ("plan_proverok", [
        "план проверок", "планы проверок", "план контрольных", "контрольных проверок",
        "расписание проверок", "график проверок", "график контрольных",
        "когда проверка", "срок проверки", "сроки проверки", "контрольная проверка",
        "календарь проверок",
    ]),
    ("ob_organizacii_kontrolya", [
        "об организации контроля", "организация контроля", "организации контроля",
        "как организован контроль", "положение о контроле", "порядок проведения проверок",
        "контрольный комитет", "кк контроль",
    ]),
    ("kontrol_sro", [
        "контроль сро", "контроль деятельности", "внеплановая проверка",
        "внеплановые проверки", "раздел контроль",
    ]),
    ("ustranenie_narusheniy", [
        "устранение нарушений", "устранить нарушен", "устранению нарушений",
        "исправить нарушен", "срок устранения", "отчёт об устранении",
        "отчет об устранении", "как устранить нарушения", "адк", "дисциплинарн",
    ]),
    ("perechen_dokumentov", [
        "перечень документов", "проверяемые документы", "документы для проверки",
        "документы для контрольной проверки", "документы при проверке",
        "доверенность на проверку", "информационный лист",
    ]),
    ("nok_obuchenie", [
        "подготовка к нок", "подготовка к независимой", "обучение нок",
        "курс нок", "курсы нок", "предэкзаменацион", "как подготовиться к нок",
        "подготовка к независимой оценке", "обучение перед нок",
    ]),
    ("nok", [
        "нок", "независимая оценка", "оценка квалификации", "экзамен нок",
        "свидетельство нок", "цок", "правила сдачи нок", "что такое нок",
        "документы для нок", "документы нок", "какие документы для нок",
        "сроки сдачи нок", "как часто нок",
    ]),
    ("dokumenty_nrs", [
        "документы в нрс", "документы для нрс", "документы на специалиста",
        "7 документов", "пакет документов специалист", "какие документы в нрс",
    ]),
    ("trebovaniya_spec", [
        "требования к специалист", "минимум 2 специалист", "квалификационный состав",
        "штат специалист", "гендиректор нрс", "главный инженер нрс",
    ]),
    ("vnesenie_v_reestr_spec", [
        "внесение в реестр специалистов", "внесение специалиста", "включение специалиста",
        "добавить специалиста", "подача документов на специалиста", "в реестр специалистов",
        "вступить в нрс", "вступление в нрс", "вступить в нрм",
    ]),
    ("nopriz_nrs", [
        "ноприз", "nopriz", "реестр ноприз", "нрс ноприз", "реестр нрс ноприз",
        "реестр специалистов ноприз", "nrs.nopriz", "проектировщик ноприз", "изыскатель ноприз",
    ]),
    ("nostroy_nrs", [
        "нрс нострой", "реестр нрс нострой", "реестр специалистов нострой",
        "реестр специалистов", "нострой реестр спец", "проверить специалиста",
        "найти специалиста", "nrs.nostroy", "нрсник", "нрсники",
        "национальный реестр специалистов",
    ]),
    ("nrs", [
        "куратор нрс", "кураторы нрс",
    ]),
    ("vznosy", [
        "размер взносов", "размеры взносов", "таблица взносов", "сколько стоит вступ",
        "взнос", "взносы", "компенсационный фонд", "кф вв", "кф одо",
        "членский взнос", "членские взносы", "вступительный взнос",
        "уровень ответственности",
    ]),
    ("nostroy_reestr", [
        "reestr nostroy", "реестр нострой", "реестр сро нострой",
        "реестр nostroy", "сайт нострой", "члены нострой", "реестр членов нострой",
        "организации нострой",
    ]),
    ("reestr_chlenov", [
        "реестр членов", "реестр сро", "реестр организаций", "список членов",
        "члены сро", "найти в реестре", "проверить членство",
    ]),
    ("poluchenie_vypiski", [
        "получить выписку", "получение выписки", "как получить выписку",
        "выписка из реестра", "выписку из реестра", "запрос выписки",
        "выписка из сро", "выписка",
    ]),
    ("lichniy_kabinet", [
        "личный кабинет", "личный кабинет члена", "доступ к личному кабинету",
        "логин кабинет", "пароль кабинет", "partner@srogen", "кабинет на сайте",
    ]),
    ("reestr", [
        "изменения в реестр", "внесение изменений", "переоформлен",
        "обновить реестр", "изменить реестр", "изменить данные в реестре",
    ]),
    ("chlenstvo_info", [
        "о членстве", "членство в сро", "информация для членов", "для членов сро",
        "действующим членам", "права и обязанности", "членам сро",
    ]),
    ("vstuplenie", [
        "вступить", "вступление", "как вступить", "стать членом", "подача заявки",
        "документы для вступления", "какие документы для вступления",
        "документы чтобы вступить", "какие документы нужны для вступления",
    ]),
    ("zakonodatelstvo", [
        "закон", "законы", "законодательство", "градостроительный кодекс", "норматив",
        "124-фз", "база законов",
    ]),
    ("novosti", [
        "новост", "срочн", "объявлен", "мошенник",
    ]),
    ("zhaloby", [
        "жалоб", "предложен", "телефон доверия", "форма обращения",
    ]),
    ("filialy", [
        "филиал", "представительств", "представитель в регион", "офис в регион",
    ]),
    ("partnery", [
        "партнёр", "партнер", "партнёры", "партнеры", "учебный центр рсс", "dporss",
        "мотс", "mots", "sro-mots", "сайт мотс", "огпо", "огпп", "sroogpo",
        "srosp", "градстройпроект", "огпс", "sro-gps",
    ]),
    ("charity", [
        "благотворитель", "благотворительность", "дивеевск",
    ]),
    ("blanki_odo", [
        "бланк одо", "бланки одо", "уведомление одо", "уведомление об одо",
        "форма одо", "фактическом совокупном", "что такое одо", "что такое odo",
        "договоры подряда", "уведомление о заключённых контрактах",
    ]),
    ("blanki_vstuplenie", [
        "бланк вступ", "бланки вступ", "бланк для вступления", "бланки для вступления",
        "заявление о прием", "заявление о приёме",
    ]),
    ("blanki_proverka", [
        "бланк провер", "бланки провер", "бланк для проверки", "бланки для проверки",
        "бланк контрол", "доверенность бланк", "информационный лист бланк",
    ]),
    ("blanki_reestr", [
        "бланк изменен", "бланк реестр", "заявление изменен", "заявление о внесении изменений",
    ]),
    ("kontakty", [
        "контакт", "телефон", "адрес", "связаться", "позвонить в сро",
    ]),
]

AI_BUTTON = "💬 ИИ-помощник"
FAQ_AI_BUTTON = "💬 Не нашли в FAQ? Спросите ИИ"

from bot_disclaimers import OFFICIAL_SOURCE_DISCLAIMER

AI_MODE_HINT = (
    "🤖 <b>ИИ-помощник СРО Ассоциации</b>\n\n"
    "Задайте вопрос своими словами — я подберу <b>конкретный раздел</b> на официальном сайте "
    "и дам краткий ориентир.\n\n"
    "<i>Примеры: «Размеры взносов», «Нострой реестр специалистов», «План проверок»</i>\n"
    "<i>Организацию ищите кнопкой «🔍 Поиск организации» — ИНН или часть названия "
    "(например «7736…» или «ТаКПО»).</i>\n\n"
    f"{OFFICIAL_SOURCE_DISCLAIMER}\n\n"
    "Чтобы выйти — нажмите «⬅️ Назад в меню»."
)
FAQ_AI_HINT = (
    "🤖 <b>Не нашли ответ в FAQ?</b>\n\n"
    "Задайте вопрос своими словами — ИИ-помощник подберёт нужный раздел на официальном сайте "
    "и даст краткий ориентир.\n\n"
    "<b>Примеры вопросов:</b>\n"
    "• Размеры взносов\n"
    "• Нострой реестр специалистов\n"
    "• План проверок\n"
    "• Документы для вступления\n\n"
    f"{OFFICIAL_SOURCE_DISCLAIMER}\n\n"
    "Чтобы выйти — нажмите «⬅️ Назад в меню»."
)
FAQ_NOT_FOUND_TEXT = (
    "🤔 <b>Не нашли нужный ответ в FAQ?</b>\n\n"
    "Возможно, информация есть на официальном сайте в другом разделе.\n\n"
    "Нажмите кнопку <b>💬 Не нашли в FAQ? Спросите ИИ</b> ниже "
    "или задайте вопрос прямо сейчас — ИИ-помощник подберёт ссылку.\n\n"
    "<b>Примеры:</b>\n"
    "• Размеры взносов\n"
    "• Нострой реестр специалистов\n"
    "• Получение выписки\n\n"
    f"{OFFICIAL_SOURCE_DISCLAIMER}"
)

ai_mode_users = set()
faq_mode_users = set()
search_mode_users = set()


def is_ai_mode(chat_id):
    return chat_id in ai_mode_users


def enter_ai_mode(chat_id):
    search_mode_users.discard(chat_id)
    ai_mode_users.add(chat_id)


def exit_ai_mode(chat_id):
    ai_mode_users.discard(chat_id)


def is_faq_mode(chat_id):
    return chat_id in faq_mode_users


def enter_faq_mode(chat_id):
    search_mode_users.discard(chat_id)
    faq_mode_users.add(chat_id)


def exit_faq_mode(chat_id):
    faq_mode_users.discard(chat_id)


def is_search_mode(chat_id):
    return chat_id in search_mode_users


def enter_search_mode(chat_id):
    ai_mode_users.discard(chat_id)
    faq_mode_users.discard(chat_id)
    search_mode_users.add(chat_id)


def exit_search_mode(chat_id):
    search_mode_users.discard(chat_id)


def _normalize(text):
    return re.sub(r"\s+", " ", text.lower().strip())


def _mentions_nrs(normalized: str) -> bool:
    """НРС и частые опечатки: нрм, нрк и т.п."""
    if "nrs" in normalized or "нрс" in normalized:
        return True
    if re.search(r"\bнр[скм]\b", normalized):
        return True
    for word in normalized.split():
        token = re.sub(r"[^\wа-яё]", "", word, flags=re.IGNORECASE)
        if len(token) == 3 and token.startswith("нр"):
            if SequenceMatcher(None, token, "нрс").ratio() >= 0.66:
                return True
    return False


def _match_nrs_topic(normalized: str):
    if not _mentions_nrs(normalized):
        return None
    if "ноприз" in normalized or "nopriz" in normalized:
        return "nopriz_nrs"
    if any(w in normalized for w in ("документ", "какие нужн", "пакет документ")):
        return "dokumenty_nrs"
    if any(w in normalized for w in ("вступ", "внесен", "включ", "добавить", "попасть")):
        return "vnesenie_v_reestr_spec"
    if "куратор" in normalized:
        return "nrs"
    if "реестр" in normalized or "специал" in normalized:
        return "nostroy_nrs"
    return "nostroy_nrs"


def _match_by_keywords(question):
    normalized = _normalize(question)

    if re.search(r"что\s+(такое|это)\s+сро\b", normalized):
        return "o_sro"
    if "зачем" in normalized and re.search(r"\bсро\b", normalized):
        return "o_sro"
    if normalized in ("сро", "что сро", "что такое сро"):
        return "o_sro"

    if re.search(r"что\s+(такое|это)\s+одо\b", normalized) or normalized in ("одо", "что одо", "что такое одо"):
        return "blanki_odo"
    if re.search(r"\bодо\b", normalized) or re.search(r"\bodo\b", normalized):
        if not any(w in normalized for w in (
            "кф одо", "кф вв", "размер взнос", "таблица взнос", "сколько стоит вступ",
            "компенсационный фонд", "компенсационный", "вступительный взнос",
            "членский взнос", "уровень ответственности",
        )):
            return "blanki_odo"

    if "выписк" in normalized:
        return "poluchenie_vypiski"

    if re.search(r"\bбланк", normalized) or "скачать форму" in normalized:
        blanki_topic = _match_blanki_topic(normalized)
        if blanki_topic:
            return blanki_topic

    if any(w in normalized for w in ("строительство для себя", "строю для себя", "дом для себя")):
        return "stroitelstvo_dlya_sebya"
    if "возврат" in normalized and "взнос" in normalized:
        return "vozvrat_vznosa"
    # «срок в ступление» (с опечаткой-пробелом) тоже ловим через «ступлен»
    if "срок" in normalized and any(
        w in normalized
        for w in ("рассмотр", "вступ", "ступлен", "заявк", "прием", "примут")
    ):
        return "sroki_vstuplenie"

    if "план" in normalized and "провер" in normalized:
        return "plan_proverok"
    if ("результат" in normalized or "итог" in normalized) and "провер" in normalized:
        return "resultaty_proverok"
    if ("подготов" in normalized or "обучен" in normalized) and "нок" in normalized:
        return "nok_obuchenie"
    if "ноприз" in normalized or "nopriz" in normalized:
        return "nopriz_nrs"
    if "нострой" in normalized or "nostroy" in normalized:
        if re.search(r"специал|спецал|спец\b|нрс|nrs", normalized) or re.search(
            r"реестр.{0,20}спец", normalized
        ):
            return "nostroy_nrs"
        return "nostroy_reestr"

    nrs_topic = _match_nrs_topic(normalized)
    if nrs_topic:
        return nrs_topic

    if any(w in normalized for w in ("размер взнос", "таблица взнос", "сколько стоит вступ", "кф вв", "кф одо")):
        return "vznosy"

    has_docs = any(w in normalized for w in ("документ", "документы", "какие документ", "какие нужн"))
    if has_docs:
        if "нок" in normalized or "независим" in normalized or "оценк" in normalized and "квалиф" in normalized:
            return "nok"
        if "вступ" in normalized or "стать член" in normalized:
            if not _mentions_nrs(normalized):
                return "vstuplenie"
        if "специалист" in normalized or _mentions_nrs(normalized):
            return "dokumenty_nrs"
        if any(w in normalized for w in ("провер", "контрол", "комитет", "информационн")):
            return "perechen_dokumentov"

    for topic_id, keywords in KEYWORD_RULES:
        if topic_id == "kontakty" and _is_internal_directory_lookup(question, normalized):
            continue
        if any(keyword in normalized for keyword in keywords):
            return topic_id
    return None


def _is_internal_directory_lookup(question: str, normalized: str) -> bool:
    """«Телефон Иванова» — справочник сотрудников, не раздел kontakty на сайте."""
    from contacts_search import _DIRECTORY_HINTS, _strip_directory_hints

    lower = normalized
    has_hint = any(re.search(rf"\b{re.escape(hint)}\b", lower) for hint in _DIRECTORY_HINTS)
    if not has_hint:
        return False
    # «контакты» / «телефон» без фамилии — раздел сайта, не справочник
    remainder = _strip_directory_hints(lower)
    if not remainder or len(re.sub(r"[^а-яё]", "", remainder)) < 3:
        return False
    if any(
        lower.startswith(q)
        for q in (
            "где ",
            "как ",
            "что ",
            "адрес ",
            "контакт ",
            "контакты ",
            "офис ",
            "филиал",
        )
    ):
        return False
    return bool(re.search(r"[а-я]{2,}", lower))


_FUZZY_PHRASES = None


def _get_fuzzy_phrases():
    global _FUZZY_PHRASES
    if _FUZZY_PHRASES is None:
        phrases = []
        seen = set()
        for topic_id, keywords in KEYWORD_RULES:
            for keyword in keywords:
                if keyword not in seen:
                    phrases.append((keyword, topic_id))
                    seen.add(keyword)
        for topic_id, topic in SITE_TOPICS.items():
            title = _normalize(topic["title"])
            if title not in seen:
                phrases.append((title, topic_id))
                seen.add(title)
        _FUZZY_PHRASES = phrases
    return _FUZZY_PHRASES


def is_non_directory_site_query(text: str) -> bool:
    """Тема сайта/FAQ/разделов — не телефонный справочник (без рекурсии в directory)."""
    if match_sro_site_qa(text) or match_voprosy_faq(text):
        return True
    if _match_by_keywords(text):
        return True
    normalized = _normalize(text)
    if " " not in normalized:
        return False
    if _fuzzy_match_topic(text, skip_directory_check=True)[0]:
        return True
    return False


def _fuzzy_match_topic(question, min_ratio=0.78, *, skip_directory_check=False):
    """Находит раздел при опечатках в запросе."""
    normalized = _normalize(question)
    if len(normalized) < 4:
        return None, None

    if not skip_directory_check:
        try:
            from contacts_search import looks_like_directory_person_query

            if looks_like_directory_person_query(question):
                return None, None
        except ImportError:
            pass

    best_topic = None
    best_phrase = None
    best_ratio = 0.0

    for phrase, topic_id in _get_fuzzy_phrases():
        if len(normalized) < 6 and len(phrase) > len(normalized) + 2:
            continue
        ratio = SequenceMatcher(None, normalized, phrase).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_topic = topic_id
            best_phrase = phrase

    if best_ratio >= min_ratio and best_topic:
        display = SITE_TOPICS[best_topic]["title"]
        return best_topic, display

    return None, None


def should_route_to_ai(question):
    """Определяет, что текст — вопрос для ИИ, а не поиск организации."""
    if _match_by_keywords(question):
        return True
    if _fuzzy_match_topic(question)[0]:
        return True
    if match_voprosy_faq(question):
        return True
    if match_sro_site_qa(question):
        return True

    normalized = _normalize(question)
    if "?" in question:
        return True

    question_starts = (
        "где ", "как ", "что ", "что такое ", "когда ", "можно ", "нужно ",
        "необходимо ", "требуется ", "обязан ",
        "подскаж", "расскаж", "скажи ", "хочу ", "интересует",
        "где взять", "где найти", "где посмотреть", "где узнать",
    )
    return normalized.startswith(question_starts)


def _build_topics_prompt():
    lines = []
    for topic_id, topic in SITE_TOPICS.items():
        lines.append(
            f"{topic_id}: {topic['title']} — {topic['description']} — URL: {topic['url']}"
        )
    return "\n".join(lines)


def _match_blanki_topic(normalized):
    """Подбирает тип бланков по уточнению в запросе."""
    if "odo" in normalized or "одо" in normalized or "совокупн" in normalized and "обязательств" in normalized:
        return "blanki_odo"
    if any(w in normalized for w in ("вступ", "прием", "приём", "новый член")):
        return "blanki_vstuplenie"
    if any(w in normalized for w in ("изменен", "переоформ", "внесении изменений")):
        return "blanki_reestr"
    if any(w in normalized for w in ("провер", "контрол", "доверен", "информационн", "проверяем")):
        return "blanki_proverka"
    return "blanki_menu"


_BLANKI_BOT_HINTS = {
    "blanki_proverka": (
        "📄 <b>Бланки для проверки</b> — в боте:\n\n"
        "Введите <b>ИНН</b> → «Скачать документы»:\n"
        "• 1. Информационный лист\n"
        "• 3. Заявление на проверку\n"
        "• 4. Форма доверенности\n"
        "• 6. Положения о контроле\n\n"
        "Или: FAQ → «Проверяемые документы»"
    ),
    "blanki_vstuplenie": (
        "📄 <b>Бланки для вступления</b> — в боте:\n\n"
        "<b>Полезная информация</b> → FAQ → «Перечень документов для вступления»\n\n"
        "На сайте — перечень документов для вступления:"
    ),
    "blanki_odo": (
        "📄 <b>ОДО</b> — уведомление о фактическом совокупном размере обязательств "
        "по договорам подряда (заключение, расторжение, исполнение).\n\n"
        "Порядок и форма — на официальной странице СРО (ссылка ниже).\n\n"
        "📩 Направлять на: <code>odokk@srogen.ru</code>\n\n"
        "Скачать форму в боте: введите <b>ИНН</b> → «Скачать документы» → «7. Уведомление ОДО»"
    ),
    "blanki_reestr": (
        "📄 <b>Изменения в реестре</b> — в боте:\n\n"
        "Введите <b>ИНН</b> → «Скачать документы» → «2. Заявление о внесении изменений»"
    ),
}


def _format_blanki_response(question, topic_id):
    if topic_id == "blanki_menu":
        return {
            "ok": True,
            "text": (
                f"🤖 По вашему вопросу «<b>{question}</b>» — уточните тип бланков:\n\n"
                "🔹 <b>Для проверки</b> — напишите «бланки для проверки»\n"
                "🔹 <b>Для вступления</b> — «бланки для вступления»\n"
                "🔹 <b>Уведомление ОДО</b> — «бланк ОДО»\n"
                "🔹 <b>Изменения в реестре</b> — «бланк изменений в реестр»\n\n"
                "Или введите <b>ИНН</b> → «Скачать документы» — там все формы списком.\n\n"
                f"{OFFICIAL_SOURCE_DISCLAIMER}"
            ),
        }

    topic = SITE_TOPICS[topic_id]
    hint = _BLANKI_BOT_HINTS[topic_id]
    site_line = f"🔗 {topic['url']}\n\n" if topic.get("url") else ""

    return {
        "ok": True,
        "text": (
            f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
            f"{hint}\n"
            f"{site_line}"
            f"{OFFICIAL_SOURCE_DISCLAIMER}"
        ),
    }


def _is_blanki_topic(topic_id):
    return topic_id and (topic_id.startswith("blanki_") or topic_id == "blanki_menu")


_TOPIC_DIRECT_ANSWERS = {}

# Разделы-«навигация»: ссылка на URL, без готового «Кратко» в voprosy_faq
_KEYWORD_NAV_ONLY_TOPICS = frozenset({
    "plan_proverok",
    "resultaty_proverok",
    "perechen_dokumentov",
    "kontrol_sro",
    "ob_organizacii_kontrolya",
    "nok",
    "nok_obuchenie",
    "nostroy_reestr",
    "nostroy_nrs",
    "nopriz_nrs",
    "nrs",
    "vnesenie_v_reestr_spec",
    "dokumenty_nrs",
    "trebovaniya_spec",
    "reestr_chlenov",
    "lichniy_kabinet",
    "reestr",
    "novosti",
    "zhaloby",
    "filialy",
    "partnery",
    "charity",
    "kontakty",
    "sroki_vstuplenie",
})


def _keyword_topic_blocks_voprosy(topic_id):
    return topic_id is not None and topic_id in _KEYWORD_NAV_ONLY_TOPICS

_TOPIC_BRIEF = {
    "vstuplenie": (
        "Для вступления нужен пакет документов по требованиям СРО: заявление, "
        "учредительные документы, сведения о специалистах и др. "
        "Актуальный перечень и формы — на странице «Вступление в СРО»."
    ),
    "sroki_vstuplenie": (
        "Заполните заявку на вступление: специалист Ассоциации свяжется с вами "
        "и проконсультирует по подготовке документов. "
        "Актуальные сроки рассмотрения — на официальном сайте вашего СРО."
    ),
    "poluchenie_vypiski": (
        "Выписку из реестра членов СРО запрашивают через сайт (форма в разделе "
        "«Получение выписки») или по e-mail СРО с указанием ИНН и рег. номера. "
        "С 01.07.2017 действует единая форма выписки — без перечня видов работ."
    ),
    "lichniy_kabinet": (
        "Личный кабинет члена СРО — на официальном сайте. "
        "Доступ выдаётся при вступлении; для восстановления пароля напишите в СРО "
        "(название организации, ИНН, рег. номер)."
    ),
    "perechen_dokumentov": (
        "Перед контрольной проверкой готовят документы по перечню СРО: учредительные "
        "документы, сведения о специалистах, договоры, ОДО, страхование и др. "
        "Бланки (доверенность, информационный лист, заявление на проверку) можно "
        "<b>скачать прямо в боте</b>: введите ИНН → «Скачать документы». "
        "Полный перечень — в разделе на сайте ниже."
    ),
    "chlenstvo_info": (
        "В разделе для членов СРО — права и обязанности, порядок работы, "
        "полезные ссылки и памятки. Актуальные требования и формы — на сайте вашего СРО."
    ),
    "reestr": (
        "Чтобы изменить сведения в реестре (адрес, руководитель, специалисты и др.), "
        "подайте заявление о внесении изменений с подтверждающими документами. "
        "Форма и порядок — в разделе «Изменения в реестр» на сайте СРО."
    ),
    "plan_proverok": (
        "План контрольных проверок членов СРО публикуется на сайте в разделе "
        "контрольного комитета. Сроки и состав проверок — по утверждённому плану; "
        "уточнения — у контрольного комитета вашего СРО."
    ),
    "ustranenie_narusheniy": (
        "По итогам проверки при выявлении нарушений СРО выставляет срок их устранения. "
        "Нужно подготовить документы, подтверждающие исправление, и направить в СРО "
        "в установленный срок. Порядок — в разделе «Устранение нарушений»."
    ),
    # --- приоритет 1 ---
    "nok": (
        "НОК — независимая оценка квалификации. Экзамен сдаётся очно в ЦОК "
        "<b>не реже 1 раза в 5 лет</b>. Без действующего НОК специалиста исключают "
        "из НРС (возврат — не раньше чем через 2 года); для компаний на ООТСУ "
        "это может быть основанием для исключения из СРО. "
        "Сроки НОК проверяйте на nostroy.ru / nopriz.ru."
    ),
    "dokumenty_nrs": (
        "Для внесения специалиста в НРС нужен нотариально заверенный пакет: "
        "заявление + обычно <b>7 документов</b> (диплом, стаж, свидетельство НОК, "
        "справка об отсутствии судимости, СНИЛС и др.). "
        "Полный список — в боте: «Специалисты и НОК» → «Документы в НРС»."
    ),
    "trebovaniya_spec": (
        "В штате по основному месту работы — <b>не менее 2 специалистов</b> "
        "в НРС (для строителей — НРС НОСТРОЙ). Нужны профильное высшее образование, "
        "стаж и действующее НОК. На ООТСУ — отдельные требования к числу "
        "руководителей в НРС. Подробности — на сайте и в кнопке "
        "«Требования к специалистам»."
    ),
    "vnesenie_v_reestr_spec": (
        "Чтобы добавить специалиста в НРС, подготовьте нотариально заверенное "
        "заявление и комплект документов, направьте кураторам НРС СРО. "
        "После включения сведения появятся в реестре НОСТРОЙ или НОПРИЗ "
        "(в зависимости от вида деятельности)."
    ),
    "nrs": (
        "НРС — национальный реестр специалистов. Кураторы СРО помогают с пакетом "
        "документов и проверкой диплома по перечню Минстроя. "
        "Контакты кураторов — в боте: «Специалисты и НОК» → «Кураторы НРС»."
    ),
    "resultaty_proverok": (
        "В разделе «Результаты контрольных проверок» — <b>сводные таблицы по месяцам</b>: "
        "сколько организаций было в плане, сколько фактически проверено, "
        "сколько <b>с нарушениями</b> и <b>без</b>. Файл за нужный месяц — по ссылке на сайте. "
        "Это статистика по СРО, не акты по каждой компании. "
        "Итоги проверки вашей организации — в реестре (карточка) или у контрольного комитета."
    ),
    "nostroy_reestr": (
        "Реестр СРО / организаций НОСТРОЙ — это реестр <b>членов СРО</b> "
        "(юридических лиц), не специалистов. Проверка: "
        "<code>https://reestr.nostroy.ru</code>. "
        "Специалистов ищите в НРС НОСТРОЙ (отдельный реестр)."
    ),
    "nostroy_nrs": (
        "НРС НОСТРОЙ — реестр <b>специалистов</b> в строительстве. "
        "Проверить специалиста: <code>https://nrs.nostroy.ru</code>. "
        "Реестр организаций СРО — другой сайт (reestr.nostroy.ru)."
    ),
    # --- приоритет 2 ---
    "kontrol_sro": (
        "Контроль СРО — плановые и внеплановые проверки членов. "
        "Плановая проверка — не реже 1 раза в год; внеплановая — по жалобе "
        "или иным основаниям. Разделы: план, перечень документов, результаты, "
        "устранение нарушений."
    ),
    "ob_organizacii_kontrolya": (
        "Порядок контроля описан в положении о контроле СРО: кто проводит проверку, "
        "какие сроки и документы, как оформляются результаты. "
        "Актуальный текст — в разделе «Об организации контроля» на сайте."
    ),
    "nok_obuchenie": (
        "Перед НОК можно пройти подготовку (лекции, тесты, симулятор экзамена) — "
        "например, в учебном центре РСС. Без НОК специалиста исключают из НРС. "
        "Запись и программа — в разделе «Подготовка к НОК» на сайте / в боте."
    ),
    "reestr_chlenov": (
        "Реестр членов СРО — публичный список организаций. "
        "В боте быстрее: введите <b>ИНН</b> или название — откроется карточка "
        "со статусом, планом проверок и бланками. Полный реестр — также на сайте СРО."
    ),
    "zhaloby": (
        "Жалобу или предложение можно отправить через онлайн-форму на сайте СРО, "
        "по e-mail или на телефон доверия. Укажите ФИО, контакты и суть обращения. "
        "Форма и телефоны — по ссылке ниже."
    ),
    "kontakty": (
        "Контакты СРО (телефон, e-mail, адрес) — на странице «Контакты». "
        "Общий многоканальный: <code>+7 (495) 775-81-11</code>. "
        "Карточку организации — через «🔍 Поиск организации» (ИНН или название)."
    ),
    "filialy": (
        "У Ассоциации есть филиалы и представители в регионах. "
        "Адреса и контакты — в разделе «Филиалы и представительства» на сайте. "
        "По конкретному региону уточняйте на странице или по телефону СРО."
    ),
}


def _format_direct_faq_response(question, topic_id):
    return {
        "ok": True,
        "text": (
            f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
            f"{_TOPIC_DIRECT_ANSWERS[topic_id]}\n\n"
            f"{OFFICIAL_SOURCE_DISCLAIMER}"
        ),
    }


def resolve_topic_url(topic_id: str, profile: dict | None = None) -> str:
    """URL раздела с сайта выбранного СРО (путь ОГПС → путь партнёра)."""
    from urllib.parse import urljoin, urlparse

    from sro_about import rewrite_srogen_path_for_sro

    topic = SITE_TOPICS.get(topic_id) or {}
    default_url = topic.get("url") or ""
    if not default_url:
        return ""
    sro_id = (profile or {}).get("id") or "OGPS"
    site = (profile or {}).get("site") or "https://www.srogen.ru"
    path = rewrite_srogen_path_for_sro(sro_id, urlparse(default_url).path or "/")
    return urljoin(site.rstrip("/") + "/", path.lstrip("/"))


def _topic_sro_caption(topic_title: str, profile: dict | None) -> str:
    if not profile:
        return topic_title
    short = profile.get("short_title") or profile.get("name") or ""
    if not short:
        return topic_title
    return f"{topic_title} — {short}"


def _context_hint_for_topic(profile: dict | None, explicit_sro: bool) -> str:
    if explicit_sro:
        return ""
    return (
        "\n\n<i>Сейчас ссылка для Ассоциации «ГЕН» (ОГПС). "
        "Если вы в другом СРО — введите <b>ИНН</b> и выберите своё СРО, "
        "тогда откроется план и разделы вашего сайта.</i>"
    )


def _format_site_link_response(
    question, topic_id, suggested_phrase=None, profile=None, explicit_sro=False, brief_override=None
):
    topic = SITE_TOPICS[topic_id]
    brief = brief_override or _TOPIC_BRIEF.get(topic_id)
    if not brief:
        return _format_topic_response(
            question,
            topic_id,
            suggested_phrase=suggested_phrase,
            profile=profile,
            explicit_sro=explicit_sro,
        )
    url = resolve_topic_url(topic_id, profile)
    title = _topic_sro_caption(topic["title"], profile)
    hint = _context_hint_for_topic(profile, explicit_sro)
    return {
        "ok": True,
        "text": (
            f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
            f"💡 <b>Кратко:</b> {brief}\n\n"
            f"📄 Подробно — в разделе «<b>{title}</b>»:\n"
            f"🔗 {url}\n"
            f"{hint}\n"
            f"{OFFICIAL_SOURCE_DISCLAIMER}"
        ),
    }


def _route_topic_response(
    question, topic_id, suggested_phrase=None, profile=None, explicit_sro=False
):
    if _is_blanki_topic(topic_id):
        return _format_blanki_response(question, topic_id)
    if topic_id == "vznosy":
        from sro_fees import format_fees_short_message

        sro_id = (profile or {}).get("id") or "OGPS"
        short = format_fees_short_message(sro_id)
        url = resolve_topic_url(topic_id, profile)
        hint = _context_hint_for_topic(profile, explicit_sro)
        return {
            "ok": True,
            "text": (
                f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
                f"{short}\n\n"
                f"🔗 Подробнее на сайте: {url}"
                f"{hint}\n\n"
                f"{OFFICIAL_SOURCE_DISCLAIMER}"
            ),
        }
    if topic_id == "lichniy_kabinet":
        from sro_about import sro_has_lichniy_kabinet
        from sro_contacts import SRO_CONTACTS

        sro_id = (profile or {}).get("id") or "OGPS"
        if not sro_has_lichniy_kabinet(sro_id):
            email = (SRO_CONTACTS.get(sro_id) or {}).get("email") or "info@srogen.ru"
            name = (profile or {}).get("short_title") or (profile or {}).get("name") or "СРО"
            return {
                "ok": True,
                "text": (
                    f"🤖 По вашему вопросу «<b>{question}</b>»:\n\n"
                    f"На сайте <b>{name}</b> отдельной страницы личного кабинета нет.\n"
                    f"Напишите на почту: <code>{email}</code> "
                    "(название организации, ИНН, рег. номер в СРО)."
                ),
            }
        email = (SRO_CONTACTS.get(sro_id) or {}).get("email") or "info@srogen.ru"
        brief = (
            "Личный кабинет члена СРО — на официальном сайте. "
            f"Доступ выдаётся при вступлении; для восстановления пароля — <code>{email}</code> "
            "(название организации, ИНН, рег. номер в СРО)."
        )
        return _format_site_link_response(
            question,
            topic_id,
            suggested_phrase=suggested_phrase,
            profile=profile,
            explicit_sro=explicit_sro,
            brief_override=brief,
        )
    if topic_id == "poluchenie_vypiski":
        from sro_contacts import SRO_CONTACTS

        sro_id = (profile or {}).get("id") or "OGPS"
        email = (SRO_CONTACTS.get(sro_id) or {}).get("email") or "info@srogen.ru"
        brief = (
            "Выписку из реестра членов СРО запрашивают через сайт (форма в разделе "
            "«Получение выписки») или по e-mail "
            f"<code>{email}</code> с указанием ИНН и рег. номера. "
            "С 01.07.2017 действует единая форма выписки — без перечня видов работ."
        )
        return _format_site_link_response(
            question,
            topic_id,
            suggested_phrase=suggested_phrase,
            profile=profile,
            explicit_sro=explicit_sro,
            brief_override=brief,
        )
    if topic_id in _TOPIC_DIRECT_ANSWERS:
        return _format_direct_faq_response(question, topic_id)
    if topic_id in _TOPIC_BRIEF:
        return _format_site_link_response(
            question,
            topic_id,
            suggested_phrase=suggested_phrase,
            profile=profile,
            explicit_sro=explicit_sro,
        )
    topic = SITE_TOPICS.get(topic_id, {})
    if topic.get("url", "").rstrip("/").endswith("/voprosy"):
        item = (
            match_voprosy_faq(question, activity=(profile or {}).get("activity"))
            or get_voprosy_item_for_topic(topic_id)
            or {"label": topic["title"]}
        )
        return format_voprosy_faq_response(question, item, profile=profile)
    return _format_topic_response(
        question,
        topic_id,
        suggested_phrase=suggested_phrase,
        profile=profile,
        explicit_sro=explicit_sro,
    )


def _format_topic_response(
    question, topic_id, suggested_phrase=None, profile=None, explicit_sro=False
):
    topic = SITE_TOPICS[topic_id]
    url = resolve_topic_url(topic_id, profile)
    title = _topic_sro_caption(topic["title"], profile)
    hint = _context_hint_for_topic(profile, explicit_sro)

    if suggested_phrase and _normalize(question) != _normalize(suggested_phrase):
        intro = (
            f"🤖 Вы написали: «<b>{question}</b>»\n"
            f"Возможно, вы имели в виду: <b>{suggested_phrase}</b>\n\n"
            "Рекомендую раздел:"
        )
    else:
        intro = f"🤖 По вашему вопросу «<b>{question}</b>» рекомендую раздел:"

    return {
        "ok": True,
        "text": (
            f"{intro}\n\n"
            f"📂 <b>{title}</b>\n"
            f"🔗 {url}\n"
            f"{hint}\n"
            f"{OFFICIAL_SOURCE_DISCLAIMER}"
        ),
    }


def _topic_router_prompt(question):
    return f"""Ты помощник СРО Ассоциации «Объединение генеральных подрядчиков в строительстве» (сайт srogen.ru).
Это НЕ Minecraft и НЕ другой бот — только СРО / строительство / членство.

Пользователь задал вопрос. Выбери ОДИН наиболее подходящий раздел сайта из списка.
Не придумывай факты. Не отвечай на вопрос — только выбери ID раздела.

Примеры:
- "где планы проверок" -> plan_proverok
- "результаты проверок" -> resultaty_proverok
- "подготовка к НОК" -> nok_obuchenie
- "размеры взносов" -> vznosy
- "возврат взноса" -> vozvrat_vznosa
- "сроки рассмотрения заявки" -> sroki_vstuplenie
- "строительство для себя" -> stroitelstvo_dlya_sebya
- "документы в НРС" -> dokumenty_nrs
- "вступить в нрс" -> vnesenie_v_reestr_spec
- "вступить в нрм" -> vnesenie_v_reestr_spec
- "требования к специалистам" -> trebovaniya_spec
- "реестр НОСТРОЙ" -> nostroy_reestr
- "реестр специалистов НОСТРОЙ" -> nostroy_nrs
- "нострой реестр специалистов" -> nostroy_nrs
- "просто нострой" -> nostroy_reestr
- "реестр НРС" -> nostroy_nrs
- "реестр НОПРИЗ" -> nopriz_nrs
- "ноприз" -> nopriz_nrs
- "информация про НОК" -> nok
- "какие документы для нок" -> nok
- "какие документы для вступления" -> vstuplenie
- "какие документы для проверки" -> perechen_dokumentov
- "что такое СРО" -> o_sro
- "зачем нужно СРО" -> o_sro
- "что такое одо" -> blanki_odo
- "уведомление одо" -> blanki_odo
- "выписка из СРО" -> poluchenie_vypiski
- "личный кабинет" -> lichniy_kabinet
- "бланки для проверки" -> blanki_proverka
- "бланки для вступления" -> blanki_vstuplenie
- "бланк ОДО" -> blanki_odo
- "бланк изменений" -> blanki_reestr
- "просто бланки" -> blanki_menu
- "жалоба" -> zhaloby
- "филиал" -> filialy

Важно: nostroy_nrs — реестр СПЕЦИАЛИСТОВ (nrs.nostroy.ru). nostroy_reestr — реестр ОРГАНИЗАЦИЙ/СРО (reestr.nostroy.ru).

Разделы:
{_build_topics_prompt()}

Если вопрос не про СРО, строительство, членство, специалистов или деятельность ассоциации — ответь: NONE

Вопрос: {question}

Ответь СТРОГО одним словом: ID раздела (например plan_proverok) или NONE."""


def _parse_topic_id(answer):
    topic_id = (answer or "").strip().lower().split()[0]
    return topic_id.strip(".,:;\"'")


def _openrouter_key():
    return (_CFG_OR_KEY or "").strip()


def _openrouter_model():
    return (_CFG_OR_MODEL or OPENROUTER_DEFAULT_MODEL).strip() or OPENROUTER_DEFAULT_MODEL


def _ask_openrouter_topic(question, api_key):
    prompt = _topic_router_prompt(question)
    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://www.srogen.ru",
            "X-Title": "SRO GOLD Bot",
        },
        json={
            "model": _openrouter_model(),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 32,
        },
        timeout=45,
    )
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]
    return _parse_topic_id(answer)


def _ask_groq(question, api_key):
    prompt = _topic_router_prompt(question)
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=30,
    )
    response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]
    return _parse_topic_id(answer)


def _ask_gigachat_topic(question):
    prompt = _topic_router_prompt(question)
    answer = _gigachat_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=32,
        temperature=0.0,
    )
    return _parse_topic_id(answer)


def _ask_topic_id(question, groq_api_key):
    """OpenRouter → GigaChat (РФ) → Groq. Ошибки верхнего → следующий."""
    or_key = _openrouter_key()
    if or_key:
        try:
            return _ask_openrouter_topic(question, or_key), "openrouter"
        except Exception:
            pass
    if _gigachat_ok():
        try:
            return _ask_gigachat_topic(question), "gigachat"
        except Exception:
            pass
    if groq_api_key and groq_api_key.strip():
        return _ask_groq(question, groq_api_key), "groq"
    return None, None


def match_topic_local(question):
    """Быстрый локальный подбор раздела (ключевые слова и опечатки), без LLM."""
    topic_id = _match_by_keywords(question)
    if topic_id:
        return topic_id, None
    return _fuzzy_match_topic(question)


def get_ai_response_groq(question, api_key, chat_id=None, profile=None):
    """Подбор раздела: OpenRouter → GigaChat (РФ) → Groq."""
    explicit_sro = False
    if profile is None:
        profile, _, explicit_sro = _ai_sro_context(chat_id)
    else:
        from sro_context import get_user_sro_id

        explicit_sro = bool(get_user_sro_id(chat_id)) if chat_id is not None else False

    or_key = _openrouter_key()
    groq_ok = bool(api_key and api_key.strip())
    if not or_key and not _gigachat_ok() and not groq_ok:
        return {
            "ok": False,
            "text": (
                "⚠️ ИИ-помощник пока не настроен.\n\n"
                "Нужен ключ:\n"
                "1. OpenRouter → OPENROUTER_API_KEY\n"
                "2. Или GigaChat (Сбер, РФ) → GIGACHAT_CREDENTIALS\n"
                "3. Или Groq → GROQ_API_KEY\n"
                "4. Перезапустите бота\n\n"
                "Пока что актуальная информация на сайте:\n"
                "https://www.srogen.ru/"
            ),
        }

    try:
        topic_id, _backend = _ask_topic_id(question, api_key)
        if topic_id is None:
            raise RuntimeError("no llm backend")

        if topic_id == "none" or topic_id not in SITE_TOPICS:
            voprosy_res = _try_voprosy_answer(
                question, profile, (profile or {}).get("activity")
            )
            if voprosy_res:
                return voprosy_res
            try:
                from doc_qa import probe_document_hit, set_doc_fallback_pending

                hit = probe_document_hit(
                    question, sro_id=(profile or {}).get("id")
                )
                if hit.get("hit"):
                    if chat_id is not None:
                        set_doc_fallback_pending(chat_id, question)
                    return {
                        "ok": True,
                        "doc_fallback": True,
                        "text": hit.get("offer_text") or "",
                    }
            except Exception:
                pass
            site = (profile or {}).get("site", "https://www.srogen.ru")
            return {
                "ok": True,
                "text": (
                    f"🤖 По вопросу «<b>{question}</b>» в базе бота точного ответа нет.\n\n"
                    "Рекомендую посмотреть на официальном сайте:\n"
                    f"🔗 {site}/\n\n"
                    "Или свяжитесь с Ассоциацией:\n"
                    "📞 +7 (495) 775-81-11\n"
                    "📧 info@srogen.ru"
                ),
            }

        if _is_blanki_topic(topic_id):
            return _format_blanki_response(question, topic_id)

        return _route_topic_response(
            question,
            topic_id,
            profile=profile,
            explicit_sro=explicit_sro,
        )

    except Exception:
        return {
            "ok": False,
            "text": (
                "⚠️ ИИ-помощник временно недоступен. Попробуйте позже или "
                "перейдите на сайт: https://www.srogen.ru/"
            ),
        }


def _ai_sro_context(chat_id):
    from sro_context import get_user_profile, get_user_sro_id
    from sro_profiles import get_sro_profile

    explicit_sro = bool(get_user_sro_id(chat_id)) if chat_id is not None else False
    profile = get_user_profile(chat_id) if chat_id is not None else None
    if not profile:
        profile = get_sro_profile("OGPS")
        explicit_sro = False
    activity = profile.get("activity") if profile else None
    return profile, activity, explicit_sro


def _try_voprosy_answer(question, profile, activity):
    conflict = check_activity_question_conflict(question, activity)
    if conflict:
        return conflict
    item = match_voprosy_faq(question, activity=activity)
    if not item:
        return None
    return format_voprosy_faq_response(question, item, profile=profile)


def local_ai_route_kind(question, chat_id=None):
    """Куда уйдёт вопрос без Groq: partner | blanki | voprosy | site_qa | topic | groq."""
    _, activity, _ = _ai_sro_context(chat_id)
    if match_partner_query(question):
        return "partner"
    topic_id, _ = match_topic_local(question)
    if topic_id and _is_blanki_topic(topic_id):
        return "blanki"
    if match_voprosy_faq(question, activity=activity) and not _keyword_topic_blocks_voprosy(topic_id):
        item = match_voprosy_faq(question, activity=activity)
        if item and not item.get("_scope_blocked"):
            return "voprosy"
    if match_sro_site_qa(question):
        return "site_qa"
    if topic_id:
        return "topic"
    return "groq"


def get_ai_response(question, api_key, chat_id=None):
    profile, activity, explicit_sro = _ai_sro_context(chat_id)

    partner_match = match_partner_query(question)
    if partner_match:
        return format_partner_response(question, partner_match)

    # Вопросы «как в положении» важнее ссылки на раздел сайта (реестр и т.п.)
    try:
        from doc_qa import question_prefers_documents, try_doc_fallback_offer

        if question_prefers_documents(question):
            doc_offer = try_doc_fallback_offer(
                question,
                chat_id=chat_id,
                sro_id=(profile or {}).get("id"),
            )
            if doc_offer:
                return doc_offer
    except Exception:
        pass

    topic_id, suggested = match_topic_local(question)

    if topic_id and _is_blanki_topic(topic_id):
        return _route_topic_response(
            question,
            topic_id,
            suggested_phrase=suggested,
            profile=profile,
            explicit_sro=explicit_sro,
        )

    voprosy_res = _try_voprosy_answer(question, profile, activity)
    if voprosy_res and not _keyword_topic_blocks_voprosy(topic_id):
        return voprosy_res

    site_qa_item = match_sro_site_qa(question)
    if site_qa_item:
        return format_sro_site_qa_response(question, site_qa_item)

    if topic_id:
        return _route_topic_response(
            question,
            topic_id,
            suggested_phrase=suggested,
            profile=profile,
            explicit_sro=explicit_sro,
        )
    return get_ai_response_groq(question, api_key, chat_id=chat_id, profile=profile)
