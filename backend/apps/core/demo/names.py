"""Synthetic Sudanese patients for the demo: names in Arabic with English transliterations.

Names follow the Sudanese pattern of a given name, the father's name, the grandfather's name
and often a family or tribal name. Everything is drawn from a seeded ``random.Random``, so
the same seed gives the same 500 people. No real person is described: the parts are common
names combined at random, and phone numbers fall in mobile ranges without being real numbers.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

__all__ = ["Person", "make_people"]

#: (Arabic, English) given names.
MALE: tuple[tuple[str, str], ...] = (
    ("محمد", "Mohamed"),
    ("أحمد", "Ahmed"),
    ("عثمان", "Osman"),
    ("عبدالله", "Abdalla"),
    ("إبراهيم", "Ibrahim"),
    ("مصطفى", "Mustafa"),
    ("حسن", "Hassan"),
    ("حسين", "Hussein"),
    ("يوسف", "Yousif"),
    ("خالد", "Khalid"),
    ("عمر", "Omer"),
    ("صلاح", "Salah"),
    ("الطيب", "Altayeb"),
    ("علي", "Ali"),
    ("عبدالرحمن", "Abdelrahman"),
    ("عبدالرحيم", "Abdelrahim"),
    ("عبدالعزيز", "Abdelaziz"),
    ("عبدالمنعم", "Abdelmoneim"),
    ("بكري", "Bakri"),
    ("الفاتح", "Alfatih"),
    ("معتز", "Mutaz"),
    ("مجدي", "Magdi"),
    ("طارق", "Tarig"),
    ("هشام", "Hisham"),
    ("ياسر", "Yasir"),
    ("أنور", "Anwar"),
    ("مأمون", "Mamoun"),
    ("نزار", "Nizar"),
    ("وليد", "Waleed"),
    ("عادل", "Adil"),
    ("كمال", "Kamal"),
    ("جعفر", "Gaafar"),
    ("الصادق", "Alsadig"),
    ("المعز", "Almuiz"),
    ("محجوب", "Mahjoub"),
    ("بابكر", "Babiker"),
    ("سيف الدين", "Saifeldin"),
    ("نصر الدين", "Nasreldin"),
    ("عماد", "Imad"),
    ("أسامة", "Osama"),
    ("مازن", "Mazin"),
    ("حمزة", "Hamza"),
    ("منتصر", "Muntasir"),
    ("قاسم", "Gasim"),
    ("آدم", "Adam"),
    ("موسى", "Musa"),
    ("عيسى", "Eisa"),
    ("هارون", "Haroun"),
    ("إدريس", "Idris"),
    ("الزبير", "Alzubair"),
)

FEMALE: tuple[tuple[str, str], ...] = (
    ("فاطمة", "Fatima"),
    ("آمنة", "Amna"),
    ("مريم", "Mariam"),
    ("هالة", "Hala"),
    ("سارة", "Sara"),
    ("نادية", "Nadia"),
    ("زينب", "Zainab"),
    ("رشا", "Rasha"),
    ("سلمى", "Salma"),
    ("إيمان", "Iman"),
    ("منى", "Muna"),
    ("هبة", "Hiba"),
    ("عائشة", "Aisha"),
    ("خديجة", "Khadija"),
    ("حواء", "Hawa"),
    ("سعاد", "Suad"),
    ("نفيسة", "Nafisa"),
    ("إخلاص", "Ikhlas"),
    ("إنتصار", "Intisar"),
    ("أسماء", "Asma"),
    ("ريم", "Reem"),
    ("ولاء", "Walaa"),
    ("سمية", "Sumaya"),
    ("ثريا", "Thuraya"),
    ("عفاف", "Afaf"),
    ("سهير", "Suhair"),
    ("نجلاء", "Najlaa"),
    ("رحاب", "Rehab"),
    ("مها", "Maha"),
    ("لمياء", "Lamia"),
    ("تسنيم", "Tasneem"),
    ("أميرة", "Amira"),
    ("رقية", "Ruqaya"),
    ("حليمة", "Halima"),
    ("بثينة", "Buthaina"),
    ("وفاء", "Wafaa"),
    ("نسرين", "Nesreen"),
    ("شذى", "Shaza"),
    ("دعاء", "Duaa"),
    ("مشاعر", "Mashaer"),
    ("سوسن", "Sawsan"),
    ("هند", "Hind"),
    ("نوال", "Nawal"),
    ("سامية", "Samia"),
    ("عواطف", "Awatif"),
    ("آسيا", "Asia"),
    ("روضة", "Rawda"),
    ("ملاذ", "Malaz"),
    ("رزان", "Razan"),
    ("لينا", "Lina"),
)

#: Fathers' and grandfathers' names: the male names and a few more traditional ones.
ELDERS: tuple[tuple[str, str], ...] = (
    *MALE,
    ("الأمين", "Alamin"),
    ("بشير", "Bashir"),
    ("النور", "Alnour"),
    ("عوض", "Awad"),
    ("حامد", "Hamid"),
    ("سليمان", "Suliman"),
    ("الحسن", "Alhassan"),
    ("المك", "Almak"),
    ("دفع الله", "Dafalla"),
    ("عبدالقادر", "Abdelgadir"),
    ("الخضر", "Alkhidir"),
    ("فضل", "Fadul"),
    ("حمد", "Hamad"),
    ("البشير", "Albashir"),
    ("الشيخ", "Alsheikh"),
)

#: Family and clan names commonly carried as the last part.
FAMILIES: tuple[tuple[str, str], ...] = (
    ("المهدي", "Almahdi"),
    ("الميرغني", "Almirghani"),
    ("أبوبكر", "Abubakr"),
    ("الجعلي", "Aljaali"),
    ("الشايقي", "Alshaigi"),
    ("الدنقلاوي", "Aldongolawi"),
    ("الكباشي", "Alkabbashi"),
    ("العبادي", "Alabbadi"),
    ("الحلفاوي", "Alhalfawi"),
    ("المحسي", "Almahasi"),
    ("الرباطابي", "Alrubatabi"),
    ("الكردفاني", "Alkordofani"),
    ("الدارفوري", "Aldarfouri"),
    ("البطحاني", "Albathani"),
    ("الحسناوي", "Alhasnawi"),
    ("البديري", "Albadiri"),
    ("الكاهلي", "Alkahli"),
    ("الضو", "Aldaw"),
    ("أبوشنب", "Abushanab"),
    ("قرشي", "Gurashi"),
)

#: (Arabic, English) neighbourhoods and towns for addresses.
PLACES: tuple[tuple[str, str], ...] = (
    ("أم درمان - الثورة", "Omdurman, Althawra"),
    ("أم درمان - بيت المال", "Omdurman, Beit Almal"),
    ("بحري - الصافية", "Bahri, Alsafia"),
    ("بحري - شمبات", "Bahri, Shambat"),
    ("الخرطوم - الرياض", "Khartoum, Alriyadh"),
    ("الخرطوم - الصحافة", "Khartoum, Alsahafa"),
    ("الخرطوم - جبرة", "Khartoum, Jabra"),
    ("ود مدني - الدرجة", "Wad Madani, Aldaraja"),
    ("كسلا - الختمية", "Kassala, Alkhatmiya"),
    ("بورتسودان - ديم المدينة", "Port Sudan, Deim Almadina"),
    ("عطبرة - الداخلة", "Atbara, Aldakhla"),
    ("شندي - الكبوشية", "Shendi, Alkabushiya"),
    ("القضارف - السوق", "Gedaref, Alsouq"),
    ("سنار - المدينة", "Sennar, Almadina"),
)

MOBILE_PREFIXES: tuple[str, ...] = ("090", "091", "092", "096", "099", "011", "012")


@dataclass(frozen=True, slots=True)
class Person:
    sex: str
    full_name_ar: str
    full_name_en: str
    date_of_birth: date
    phone: str
    address: str


def _age_days(rng: random.Random) -> int:
    """Ages skewed young, like an outpatient population: many children, few over 70."""
    band = rng.random()
    if band < 0.22:
        years = rng.uniform(0.2, 12)
    elif band < 0.35:
        years = rng.uniform(12, 18)
    elif band < 0.80:
        years = rng.uniform(18, 50)
    elif band < 0.95:
        years = rng.uniform(50, 70)
    else:
        years = rng.uniform(70, 88)
    return int(years * 365.25)


def _name(rng: random.Random, sex: str) -> tuple[str, str]:
    given = rng.choice(FEMALE if sex == "female" else MALE)
    father = rng.choice(ELDERS)
    grandfather = rng.choice(ELDERS)
    parts = [given, father, grandfather]
    if rng.random() < 0.55:
        parts.append(rng.choice(FAMILIES))
    return " ".join(p[0] for p in parts), " ".join(p[1] for p in parts)


def make_people(rng: random.Random, count: int, *, today: date) -> list[Person]:
    """``count`` distinct people (no two share a full name or a phone)."""
    people: list[Person] = []
    names: set[str] = set()
    phones: set[str] = set()
    while len(people) < count:
        sex = "female" if rng.random() < 0.54 else "male"
        name_ar, name_en = _name(rng, sex)
        if name_ar in names:
            continue
        phone = rng.choice(MOBILE_PREFIXES) + f"{rng.randrange(10**7):07d}"
        if phone in phones:
            continue
        names.add(name_ar)
        phones.add(phone)
        place = rng.choice(PLACES)
        people.append(
            Person(
                sex=sex,
                full_name_ar=name_ar,
                full_name_en=name_en,
                date_of_birth=today - timedelta(days=_age_days(rng)),
                phone=phone,
                address=place[0],
            )
        )
    return people
