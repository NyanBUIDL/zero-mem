#!/usr/bin/env python3
"""Deterministic SYNTHETIC dataset in the LongMemEval JSON format (for offline benchmarking only).

The real LongMemEval files (longmemeval_s_cleaned.json, ...) are hosted on HuggingFace; when that host is not reachable this
generator produces a file with the same schema so the whole pipeline (ingest -> recall -> session-level hit/recall) can be
exercised and ranking changes can be compared.  **Numbers measured on this file are NOT LongMemEval numbers.**  The text is
template based (no LLM), the questions paraphrase the needle on purpose (inflection / synonym gaps, hard negatives that share
words but not the fact) and every file is a pure function of ``--seed``.

  python benchmarks/synth_longmemeval.py --seed 7 --questions 120 --sessions 40 --out /tmp/synth_lme.json

Schema per item (as LongMemEval): question_id, question_type, question, answer, question_date, haystack_session_ids,
haystack_dates, haystack_sessions (list of sessions = list of {role, content[, has_answer]}), answer_session_ids.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

NAMES = ("Alice Ben Carla Dmitri Elena Farid Grace Hugo Ines Jamal Keiko Liam Mona Nikhil Olga Pedro Quinn Rosa Sven Tara "
         "Uma Viktor Wanda Xavier Yara Zane").split()
PETS = "Biscuit Mochi Pepper Waffles Nugget Juniper Pickles Olive Ziggy Maple Bruno Cosmo Dumpling Fable Gizmo".split()
ANIMALS = "dog cat rabbit parrot hamster tortoise ferret".split()
CITIES = ("Lisbon Kyoto Denver Cairo Oslo Lima Hanoi Perth Dublin Seoul Austin Prague Quito Tallinn Porto Bergen Leeds "
          "Hobart Malmo Tunis").split()
INSTRUMENTS = "violin cello guitar piano saxophone trumpet flute ukulele".split()
JOBS = "nurse carpenter accountant translator pharmacist architect electrician paramedic librarian".split()
COMPANIES = "Northwind Brightline Kestrel Larkspur Meridian Quarry Tidewater Alder Cobalt Fernhill".split()
FOODS = "peanuts shellfish sesame walnuts mustard kiwi lactose gluten".split()
CARS = "Corolla Civic Mazda3 Outback Golf Fiesta Octavia Prius".split()
COLORS = "red blue silver green black white orange".split()
BOOKS = ("Dune|Middlemarch|Neuromancer|Persuasion|Hyperion|Beloved|Kokoro|Ficciones|Gilead|Solaris|Ubik|Emma").split("|")
AUTHORS = "Herbert Eliot Gibson Austen Simmons Morrison Soseki Borges Robinson Lem Dick".split()
ACTIVITIES = "hiking climbing kayaking cycling swimming fishing bowling skating".split()
RESTAURANTS = "Luna Basil Sakura Olivia Tandoor Marisol Ember Saffron Juniper Mistral".split()
STREETS = "Maple Harbor Willow Station Lantern Orchard Foundry Canal".split()
DISHES = "risotto ramen paella pho gnocchi tagine dumplings ceviche".split()
LANGUAGES = "Spanish Japanese Italian Korean Portuguese German Arabic Swahili".split()
EVENTS = "marathon triathlon half-marathon cycling-race obstacle-course charity-run".split()
MONTHS = "January February March April May June July August September October November December".split()
LISTEN = "jazz classical techno folk ambient reggae".split()

TOPICS = {
    "cooking": ("recipe oven simmer garlic butter sauce dough pantry whisk skillet broth marinade herbs".split(),
                "How do I get a good crust on homemade {a}?|Any tips for a {a} that does not turn soggy?"),
    "travel": ("itinerary passport hostel flight visa luggage museum train ticket hotel landmark map".split(),
               "What should I pack for a week of {a} travel?|Is the {a} route worth the extra day?"),
    "fitness": ("workout stretching cardio protein squat recovery treadmill rowing kettlebell warmup".split(),
                "Could you outline a beginner {a} routine?|How often should I rest between {a} sessions?"),
    "coding": ("python function database cache refactor compile branch thread deploy pipeline bug".split(),
               "Why does my {a} script keep timing out?|What is a clean way to structure a {a} module?"),
    "gardening": ("compost seedling pruning soil mulch tomato greenhouse trellis fertilizer perennial".split(),
                  "When should I plant {a} in a cold climate?|Why are my {a} leaves turning yellow?"),
    "finance": ("budget savings interest mortgage invoice pension dividend index deduction ledger".split(),
                "How should I split my {a} between saving and investing?|Is a {a} account worth the fee?"),
    "music": ("melody chord rhythm tempo scale rehearsal lyrics harmony recital sheet".split(),
              "What is a good way to practise {a} scales?|Can you explain {a} chord progressions?"),
    "health": ("sleep hydration posture checkup vitamin symptom therapy stretching routine diet".split(),
               "What helps with {a} fatigue in the afternoon?|How can I improve my {a} habits?"),
    "movies": ("director sequel soundtrack plot casting subtitle trilogy festival script cinematography".split(),
               "Which {a} films should I watch first?|Is the {a} sequel as good as the original?"),
    "history": ("empire treaty dynasty archive revolution scholar chronicle monument expedition era".split(),
                "Why did the {a} period end so abruptly?|Who were the key figures in {a} history?"),
    "photography": ("aperture shutter lens tripod exposure portrait panorama filter sunrise gallery".split(),
                    "How do I shoot {a} in low light?|Which lens suits {a} best?"),
    "pets": ("leash vet grooming kibble litter collar training shelter treats fetch".split(),
             "How do I stop my {a} from chewing furniture?|What should a {a} eat every day?"),
}
SENTENCES = (
    "A good starting point is to focus on {a} and {b} before moving on to {c}.|"
    "Many people find that {a} works better when combined with {b}.|"
    "It also helps to keep track of {c}, since small changes in {a} add up over time.|"
    "If {a} feels difficult, try simplifying {b} first and revisit {c} afterwards.|"
    "Another option is to read about {a}; it usually explains {b} in plain language.|"
    "Be patient: {a} and {c} tend to improve gradually rather than all at once.|"
    "A common mistake is ignoring {b}, which then makes {a} harder than it needs to be.|"
    "For a first week, set a small goal around {a} and review {c} at the end of each day."
).split("|")

Session = list  # list of {"role", "content"[, "has_answer"]}
TYPE_WEIGHTS = (("single-session-user", 14), ("single-session-assistant", 10), ("single-session-preference", 6),
                ("multi-session", 26), ("knowledge-update", 14), ("temporal-reasoning", 30))


def _pick(rng: random.Random, pool) -> str:
    return pool[rng.randrange(len(pool))]


def _ago(rng: random.Random) -> str:
    return _pick(rng, ["last week", "a few weeks ago", "last month", "in the spring", "two months back"])


# --------------------------------------------------------------------------------------- needle families
# Each returns (question, answer, [evidence turns per answer session], [hard-negative user sentences]).
def _pet(rng):
    animal, pet, other = _pick(rng, ANIMALS), _pick(rng, PETS), _pick(rng, PETS)
    place = _pick(rng, CITIES)
    ev = f"By the way, I adopted a {animal} named {pet} from the {place} shelter {_ago(rng)}."
    q = _pick(rng, [f"What is the name of the {animal} I adopted?", f"What did I call the {animal} I got from a shelter?"])
    neg = [f"My neighbour has a {animal} called {other} and it barks all night.",
           f"I have been thinking about adopting something small, maybe a hamster."]
    return q, pet, [[("user", ev)]], neg


def _teacher(rng):
    inst, person = _pick(rng, INSTRUMENTS), _pick(rng, NAMES)
    ev = f"I've been learning the {inst} for {rng.randint(2, 9)} months now and my teacher {person} says I'm improving."
    q = _pick(rng, [f"Who is teaching me to play the {inst}?", f"Which teacher helps me with the {inst}?"])
    neg = [f"My cousin plays the {_pick(rng, INSTRUMENTS)} in a band and charges a lot for lessons.",
           "I should really find a teacher for something creative this year."]
    return q, person, [[("user", ev)]], neg


def _job(rng):
    job, company = _pick(rng, JOBS), _pick(rng, COMPANIES)
    ev = f"Quick update: I started working as a {job} at {company} in {_pick(rng, MONTHS)}, the commute is lovely."
    q = _pick(rng, [f"Where do I work as a {job}?", f"Which company hired me as a {job}?"])
    neg = [f"A friend of mine works as a {_pick(rng, JOBS)} at {_pick(rng, COMPANIES)} and hates the commute.",
           f"I read an article about how a {job} spends a typical day."]
    return q, company, [[("user", ev)]], neg


def _allergy(rng):
    food = _pick(rng, FOODS)
    ev = f"I'm allergic to {food}, so I always check the label before buying anything."
    q = _pick(rng, ["Which food do I need to avoid because of my allergy?", "What am I allergic to?"])
    neg = [f"My brother loves {_pick(rng, FOODS)} and cooks with it constantly.",
           "I read that food allergies are becoming more common in cities."]
    return q, food, [[("user", ev)]], neg


def _car(rng):
    color, car, year = _pick(rng, COLORS), _pick(rng, CARS), rng.randint(2009, 2023)
    ev = f"I drive a {color} {car} that I bought in {year}; it has been reliable so far."
    q = _pick(rng, ["What kind of car do I drive?", "Which car did I buy and in what year?"])
    neg = [f"Rental agencies near the airport had a {_pick(rng, COLORS)} {_pick(rng, CARS)} available for cheap.",
           "I have been comparing electric cars for a possible purchase next year."]
    return q, f"a {color} {car}", [[("user", ev)]], neg


def _language(rng):
    lang = _pick(rng, LANGUAGES)
    ev = f"I'm studying {lang} in the evenings because my partner's family speaks it at dinner."
    q = _pick(rng, ["Which language am I studying?", "Why am I learning a new language, and which one?"])
    neg = [f"A podcast about {_pick(rng, LANGUAGES)} grammar was recommended to me by a colleague.",
           "Learning languages as an adult takes a lot of repetition, I have heard."]
    return q, lang, [[("user", ev)]], neg


def _birthday(rng):
    person, month = _pick(rng, NAMES), _pick(rng, MONTHS)
    day = rng.randint(1, 28)
    ev = f"My sister {person}'s birthday is on {month} {day} and I'm planning a surprise party."
    q = _pick(rng, [f"When is {person}'s birthday?", f"On what date should I expect {person}'s birthday party?"])
    neg = [f"My colleague {_pick(rng, NAMES)} celebrated a birthday in {_pick(rng, MONTHS)} with a big cake.",
           "Surprise parties are tricky to organise without anyone noticing."]
    return q, f"{month} {day}", [[("user", ev)]], neg


def _restaurant(rng):
    name, street, dish = _pick(rng, RESTAURANTS), _pick(rng, STREETS), _pick(rng, DISHES)
    ev = f"I'd recommend {name} on {street} Street; their {dish} is excellent and the staff are friendly."
    q = _pick(rng, [f"What was the name of the restaurant you recommended on {street} Street?",
                    f"Which place did you suggest for {dish}?"])
    neg = [f"Another restaurant on {_pick(rng, STREETS)} Street gets crowded at lunch, so book ahead.",
           f"Homemade {_pick(rng, DISHES)} is easier than most people think."]
    return q, name, [[("assistant", ev)]], neg


def _book(rng):
    book, author = _pick(rng, BOOKS), _pick(rng, AUTHORS)
    ev = f"I just finished reading '{book}' by {author} and I loved the ending."
    q = _pick(rng, ["Which novel did I recently finish reading?", f"What book by {author} did I finish?"])
    neg = [f"My book club is reading something by {_pick(rng, AUTHORS)} next month.",
           "Finishing a long novel gives me a strange feeling of loss."]
    return q, book, [[("user", ev)]], neg


def _preference(rng):
    kind = _pick(rng, LISTEN)
    other = _pick(rng, [x for x in LISTEN if x != kind])
    ev = f"I really prefer {kind} over {other} when I'm focusing; anything with lyrics distracts me."
    q = _pick(rng, ["Can you suggest some music for my study session?", "What should I put on while I concentrate?"])
    neg = [f"A friend keeps sending me {_pick(rng, LISTEN)} playlists I never open.",
           "Some people concentrate better in a quiet room."]
    return q, f"{kind} music without lyrics", [[("user", ev)]], neg


def _trips(rng):  # multi-session: two sessions, one amount each
    c1, c2 = rng.sample(CITIES, 2)
    a1, a2 = rng.randint(300, 900), rng.randint(300, 900)
    e1 = f"My trip to {c1} cost me ${a1} in total, mostly the hotel."
    e2 = f"The {c2} trip ended up costing ${a2}, which was more than I planned."
    q = f"How much did I spend in total on my trips to {c1} and {c2}?"
    neg = [f"I'm saving up for a trip to {_pick(rng, CITIES)} but prices keep rising.",
           f"Flights to {_pick(rng, CITIES)} were cheap last winter."]
    return q, f"${a1 + a2}", [[("user", e1)], [("user", e2)]], neg


def _hobbies(rng):  # multi-session: two activities with different people
    act1, act2 = rng.sample(ACTIVITIES, 2)
    p1, p2 = rng.sample(NAMES, 2)
    e1 = f"On weekends I go {act1} with my friend {p1}; we always bring snacks."
    e2 = f"I also started {act2} with {p2} on Thursdays, which is surprisingly tiring."
    q = f"Which two activities do I do with {p1} and {p2}, and when?"
    neg = [f"My gym offers {_pick(rng, ACTIVITIES)} classes on weekends but they are always full.",
           f"I watched a documentary about {_pick(rng, ACTIVITIES)} last night."]
    return q, f"{act1} and {act2}", [[("user", e1)], [("user", e2)]], neg


def _moved(rng):  # knowledge update: the later session wins
    c1, c2 = rng.sample(CITIES, 2)
    e1 = f"I'm still living in {c1} but I am looking at apartments elsewhere."
    e2 = f"I moved to {c2} last week and unpacked the last box yesterday."
    q = "Which city do I live in now?"
    neg = [f"I visited {_pick(rng, CITIES)} for a conference and the weather was perfect.",
           "Moving house is stressful, especially the paperwork."]
    return q, c2, [[("user", e1)], [("user", e2)]], neg


def _running(rng):  # knowledge update: weekly distance changed
    event = _pick(rng, EVENTS)
    m1, m2 = rng.randint(5, 15), rng.randint(16, 30)
    e1 = f"I'm training for a {event} and run {m1} miles every week."
    e2 = f"Training for the {event} is going well; I now run {m2} miles per week."
    q = f"How many miles do I run each week while training for the {event}?"
    neg = [f"A neighbour signed up for a {_pick(rng, EVENTS)} and keeps talking about it.",
           "Running shoes wear out faster than most people expect."]
    return q, str(m2), [[("user", e1)], [("user", e2)]], neg


def _started(rng):  # temporal reasoning: date arithmetic needs the dated statement
    job, month, day = _pick(rng, JOBS), _pick(rng, MONTHS), rng.randint(1, 28)
    ev = f"I started my new job as a {job} on {month} {day}, and the first week was a blur."
    q = f"How many weeks ago did I start my new job as a {job}?"
    neg = [f"My cousin changed careers and became a {_pick(rng, JOBS)} recently.",
           "The first week at any job is mostly paperwork and introductions."]
    return q, f"{month} {day}", [[("user", ev)]], neg


def _event(rng):  # temporal reasoning
    person, month, day = _pick(rng, NAMES), _pick(rng, MONTHS), rng.randint(1, 28)
    event = _pick(rng, EVENTS)
    ev = f"I registered for the {event} on {month} {day}; {person} is joining me as my training partner."
    q = f"How long before the {event} did I register, and who is my training partner?"
    neg = [f"Registration for a different {_pick(rng, EVENTS)} opens next week.",
           f"{_pick(rng, NAMES)} is thinking about doing a {_pick(rng, EVENTS)} next year."]
    return q, f"{person}, {month} {day}", [[("user", ev)]], neg


FAMILIES: dict[str, list[Callable]] = {
    "single-session-user": [_pet, _teacher, _job, _allergy, _car, _language, _birthday, _book],
    "single-session-assistant": [_restaurant],
    "single-session-preference": [_preference],
    "multi-session": [_trips, _hobbies],
    "knowledge-update": [_moved, _running],
    "temporal-reasoning": [_started, _event],
}


# --------------------------------------------------------------------------------------- sessions
def _topic_session(rng: random.Random, topic: str, extra_user: Optional[str] = None, turns: int = 0) -> Session:
    words, questions = TOPICS[topic]
    openers = questions.split("|")
    turns = turns or rng.randint(4, 8)
    session: Session = []
    for index in range(turns):
        a, b, c = rng.sample(words, 3)
        if index == 0:
            user = _pick(rng, openers).format(a=a)
        elif extra_user and index == 1:
            user = extra_user
        else:
            user = f"Thanks. What about {a} and {b}? Is {c} important too?"
        session.append({"role": "user", "content": user})
        answer = " ".join(_pick(rng, SENTENCES).format(a=rng.choice(words), b=rng.choice(words), c=rng.choice(words))
                          for _ in range(rng.randint(3, 6)))
        session.append({"role": "assistant", "content": answer})
    return session


def _evidence_session(rng: random.Random, topic: str, role: str, statement: str) -> Session:
    """An ordinary topic session where one turn of ``role`` carries the fact (marked ``has_answer``)."""
    session = _topic_session(rng, topic, turns=rng.randint(3, 6))
    slots = [i for i, turn in enumerate(session) if turn["role"] == role]
    turn = session[rng.choice(slots)]
    turn["content"] = f"{statement} {turn['content']}"
    turn["has_answer"] = True
    return session


def generate(seed: int = 7, questions: int = 120, sessions: int = 40) -> list[dict]:
    """The dataset as a list of LongMemEval items; a pure function of ``(seed, questions, sessions)``."""
    rng = random.Random(seed)
    types = [t for t, w in TYPE_WEIGHTS for _ in range(w)]
    rng.shuffle(types)  # interleaved, so any prefix keeps roughly the TYPE_WEIGHTS proportions
    topics = sorted(TOPICS)
    start = datetime(2026, 1, 1)
    out: list[dict] = []
    for index in range(questions):
        qtype = types[index % len(types)]  # every type appears in the proportion of TYPE_WEIGHTS
        question, answer, evidence, negatives = rng.choice(FAMILIES[qtype])(rng)
        qid = f"synth_{seed}_{index:04d}"
        pool: list[tuple[str, Session]] = []
        for position, statements in enumerate(evidence):
            role, text = statements[0]
            pool.append((f"answer{position}", _evidence_session(rng, rng.choice(topics), role, text)))
        for sentence in negatives:
            pool.append(("neg", _topic_session(rng, rng.choice(topics), extra_user=sentence)))
        while len(pool) < sessions:
            pool.append(("fill", _topic_session(rng, rng.choice(topics))))
        order = list(range(len(pool)))
        rng.shuffle(order)
        if qtype == "knowledge-update":  # the update (evidence 1) must come after the original statement (evidence 0)
            first, second = order.index(0), order.index(1)
            if first > second:
                order[first], order[second] = order[second], order[first]
        ids, dates, haystack, answers = [], [], [], []
        for slot, p in enumerate(order):
            kind, session = pool[p]
            sid = f"sess_{qid}_{slot:02d}"
            ids.append(sid)
            dates.append((start + timedelta(days=3 * slot)).strftime("%Y/%m/%d (%a) 10:00"))
            haystack.append(session)
            if kind.startswith("answer"):
                answers.append(sid)
        out.append({
            "question_id": qid, "question_type": qtype, "question": question, "answer": answer,
            "question_date": (start + timedelta(days=3 * len(pool) + 1)).strftime("%Y/%m/%d (%a) 09:00"),
            "haystack_session_ids": ids, "haystack_dates": dates, "haystack_sessions": haystack,
            "answer_session_ids": answers,
        })
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--questions", type=int, default=120)
    ap.add_argument("--sessions", type=int, default=40, help="haystack sessions per question")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.questions < 1 or args.sessions < 8:
        ap.error("--questions >= 1 and --sessions >= 8")
    data = generate(args.seed, args.questions, args.sessions)
    args.out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(data)} questions x {args.sessions} sessions to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
