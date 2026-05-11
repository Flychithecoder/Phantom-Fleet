"""
Target Filter — classify scraped followers for the actual engagement audience.

The targeting funnel works like this:
    1. SourceDiscoveryAgent finds FEMALE US 18-30 creators with high engagement
    2. FreshTargetAgent scrapes FOLLOWERS of those female sources
    3. *** This file *** filters those followers to keep only MALE US users
    4. Phantom Fleet accounts (Tatiana, Melodie, etc.) engage with those males
    5. Males follow back + click OF funnel → conversion

We need a separate classifier for the target (male) vs the source (female)
because the heuristics are inverted (male name dictionary, male bio signals)
and the strictness is different (we want to keep *lots* of males, we can
tolerate some noise in the target filter — far better to miss a few than
engage with bots).

Uses the same approach as core.source_scorer for US detection.
"""
from __future__ import annotations

from dataclasses import dataclass

from .source_scorer import US_CITY_KEYWORDS, US_STATE_CODES, US_SLANG_MARKERS


# Common male name stems. Condensed SSA list; full dictionary lives in
# backend/data/male_names.csv and is loaded lazily at startup.
MALE_NAME_STEMS: frozenset[str] = frozenset(
    [
        "aaron", "abe", "adam", "adrian", "aidan", "al", "alan", "albert", "alex",
        "alfred", "alfonso", "alonzo", "andrew", "angelo", "anthony", "antonio",
        "arnold", "arthur", "austin", "axel", "ben", "benjamin", "bennett", "bert",
        "beto", "bill", "billy", "blake", "bob", "bobby", "brad", "bradley", "brady",
        "brandon", "brent", "brett", "brian", "bruce", "bryan", "bryce", "caleb",
        "cameron", "carl", "carlos", "carson", "casey", "cecil", "cesar", "chad",
        "charles", "charlie", "chase", "chris", "christian", "christopher", "clark",
        "claude", "clay", "clayton", "clifford", "clint", "cody", "colby", "cole",
        "colin", "colton", "connor", "conor", "cooper", "corey", "cory", "craig",
        "curtis", "cyrus", "dale", "dalton", "damian", "damien", "damon", "dan",
        "dana", "dane", "daniel", "danny", "dante", "darius", "darrell", "darryl",
        "dave", "david", "dawson", "dean", "deandre", "dennis", "derek", "derrick",
        "devin", "devon", "dewayne", "dexter", "diego", "dillon", "dion", "dirk",
        "dominic", "don", "donald", "donnie", "donovan", "doug", "douglas", "drake",
        "drew", "duane", "duncan", "dustin", "dwayne", "dwight", "dylan", "earl",
        "eddie", "edgar", "edmund", "edward", "edwin", "efren", "eli", "elias",
        "elijah", "elliot", "elliott", "ellis", "elmer", "emanuel", "emerson",
        "emilio", "emmett", "enrique", "eric", "erick", "erik", "ernest", "ernesto",
        "ervin", "ethan", "eugene", "evan", "everett", "ezra", "fabian", "felipe",
        "felix", "fernando", "finn", "floyd", "forrest", "frank", "franklin", "fred",
        "gabe", "gabriel", "gage", "gary", "gavin", "gene", "geoffrey", "george",
        "gerald", "gerardo", "gideon", "gil", "gilbert", "giovanni", "glenn",
        "gordon", "grady", "graham", "grant", "greg", "gregory", "griffin", "gus",
        "guy", "hank", "harold", "harris", "harrison", "harry", "harvey", "hayden",
        "heath", "hector", "henry", "herbert", "hiram", "holden", "hoyt", "hudson",
        "hugh", "hugo", "hunter", "ian", "ibrahim", "ignacio", "ira", "irving",
        "isaac", "isaiah", "ismael", "israel", "ivan", "jack", "jackson", "jacob",
        "jake", "jalen", "jamal", "james", "jameson", "jamie", "jared", "jason",
        "javier", "jaxon", "jay", "jaylen", "jayson", "jeff", "jefferson", "jeffery",
        "jeffrey", "jerald", "jeremiah", "jeremy", "jerome", "jerry", "jesse",
        "jessie", "jesus", "jim", "jimmy", "joaquin", "joe", "joel", "joey", "johan",
        "john", "johnathan", "johnnie", "johnny", "jon", "jonah", "jonas", "jonathan",
        "jordan", "jordi", "jorge", "jose", "joseph", "josh", "joshua", "josiah",
        "juan", "judah", "julian", "julio", "julius", "junior", "justice", "justin",
        "kaden", "kai", "kale", "karl", "keaton", "keith", "kelly", "ken", "kenny",
        "kent", "kenton", "kerry", "kevin", "khalid", "khalil", "kirk", "kobe",
        "kody", "kristopher", "kurt", "kyle", "kyler", "lamar", "lance", "landon",
        "lane", "larry", "lawrence", "layne", "lazarus", "lee", "leland", "leo",
        "leon", "leonard", "leonardo", "leroy", "leslie", "lester", "levi", "liam",
        "lincoln", "lionel", "logan", "lonnie", "lorenzo", "louis", "lowell", "lucas",
        "lucian", "ludwig", "luis", "luke", "luther", "lyle", "lynn", "mac", "mack",
        "maddox", "malcolm", "malik", "manuel", "marc", "marcel", "marco", "marcos",
        "marcus", "mario", "mark", "marlon", "marshall", "martin", "marty", "marvin",
        "mason", "mateo", "mathew", "matt", "matthew", "maurice", "max", "maxwell",
        "maynard", "melvin", "micah", "michael", "mickey", "miguel", "mike", "miles",
        "milo", "mitch", "mitchell", "mohamed", "mohammed", "monte", "morgan",
        "morris", "moses", "murray", "myles", "myron", "nash", "nate", "nathan",
        "nathaniel", "nehemiah", "neil", "nelson", "nestor", "nicholas", "nick",
        "nicolas", "nikolas", "noah", "noel", "nolan", "norman", "oliver", "omar",
        "omari", "oren", "orlando", "orson", "oscar", "owen", "pablo", "parker",
        "pat", "patrick", "paul", "paxton", "pedro", "percy", "perry", "pete",
        "peter", "peyton", "phil", "philip", "phillip", "pierce", "pierre", "porter",
        "preston", "quentin", "quincy", "quinn", "rafael", "rafe", "raheem", "rahim",
        "ralph", "ramon", "ramsey", "randall", "randy", "raphael", "raul", "ray",
        "raymond", "reed", "reese", "reggie", "reginald", "reid", "rene", "rex",
        "reyes", "rhett", "ricardo", "richard", "rick", "ricky", "riley", "rob",
        "robert", "roberto", "robin", "rocco", "rocky", "rodney", "rodolfo", "rodrigo",
        "roger", "rohan", "roland", "rolando", "roman", "ron", "ronald", "ronnie",
        "rory", "ross", "roy", "royce", "ruben", "rudolph", "rudy", "russ", "russell",
        "rusty", "ryan", "ryder", "ryker", "sal", "salvador", "salvatore", "sam",
        "sammy", "samuel", "santiago", "santos", "saul", "sawyer", "scott", "sean",
        "sebastian", "serge", "sergio", "seth", "shane", "shannon", "shaun", "shawn",
        "sheldon", "sherman", "sidney", "silas", "simeon", "simon", "sol", "solomon",
        "spencer", "stan", "stanley", "stefan", "stephen", "sterling", "steve",
        "steven", "stewart", "stuart", "sven", "sylvester", "tad", "tanner", "taylor",
        "ted", "terence", "terrance", "terrell", "terrence", "terry", "thaddeus",
        "thane", "theo", "theodore", "thomas", "tim", "timmy", "timothy", "tobias",
        "toby", "todd", "tom", "tommy", "tony", "torrance", "trace", "tracey",
        "tracy", "travis", "trent", "trenton", "trevor", "trey", "tristan", "troy",
        "tucker", "turner", "ty", "tyler", "tyrell", "tyrone", "tyson", "uriel",
        "van", "vance", "vern", "vernon", "vic", "victor", "vince", "vincent",
        "virgil", "wade", "walker", "wallace", "walt", "walter", "warren", "waylon",
        "wayne", "weldon", "wendell", "wes", "wesley", "weston", "whitney", "wilbur",
        "wilfred", "will", "willard", "william", "willie", "willis", "wilson",
        "winston", "wyatt", "xavier", "yancy", "yanni", "yusuf", "zachariah",
        "zachary", "zack", "zaid", "zane", "zayne", "zeke", "zion",
    ]
)


MALE_USERNAME_SUFFIXES: frozenset[str] = frozenset(
    [
        "bro", "guy", "dude", "man", "mr", "sir", "king", "boss", "beast",
        "wolf", "lion", "boy", "dawg", "dog", "champ", "alpha",
    ]
)


MALE_BIO_KEYWORDS: frozenset[str] = frozenset(
    [
        "he/him", "him/he", "guy", "dude", "man", "father", "dad", "son", "brother",
        "husband", "boyfriend", "bf", "king", "gentleman", "mr.", "mr ", "sir",
        "bachelor", "bro", "bruh", "boss", "dawg", "beast",
    ]
)


@dataclass
class TargetCandidate:
    """Follower scraped from a female source — candidate for engagement."""
    username: str
    full_name: str = ""
    bio: str = ""
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0
    is_private: bool = False
    is_verified: bool = False
    is_business: bool = False


@dataclass
class TargetFilterResult:
    username: str
    passes: bool
    is_male: bool
    is_us: bool
    reasons: list[str]


def classify_male(candidate: TargetCandidate) -> tuple[bool, list[str]]:
    """Return (is_male, evidence) — looser than female classifier because
    we're filtering in a huge pool and can tolerate 5-10% noise.
    """
    evidence: list[str] = []
    hits = 0
    uname = candidate.username.lower()
    full = candidate.full_name.lower()
    bio = candidate.bio.lower()

    first_name = full.split()[0] if full else ""
    if first_name and first_name in MALE_NAME_STEMS:
        hits += 2
        evidence.append(f"first_name:{first_name}")
    elif any(stem in uname for stem in MALE_NAME_STEMS):
        hits += 1
        stem = next(s for s in MALE_NAME_STEMS if s in uname)
        evidence.append(f"username_contains_name:{stem}")

    if any(suffix in uname for suffix in MALE_USERNAME_SUFFIXES):
        hits += 1
        suffix = next(s for s in MALE_USERNAME_SUFFIXES if s in uname)
        evidence.append(f"suffix:{suffix}")

    if any(kw in bio for kw in MALE_BIO_KEYWORDS):
        hits += 1
        kw = next(k for k in MALE_BIO_KEYWORDS if k in bio)
        evidence.append(f"bio_keyword:{kw}")

    return hits >= 2, evidence


def classify_us_target(candidate: TargetCandidate) -> tuple[bool, list[str]]:
    """Return (is_us, evidence). Same heuristics as the source scorer."""
    evidence: list[str] = []
    bio = candidate.bio.lower()
    hits = 0

    bio_tokens = set(bio.replace(",", " ").replace(".", " ").split())
    matching_states = bio_tokens & US_STATE_CODES
    if matching_states:
        hits += 1
        evidence.append(f"state:{','.join(matching_states)}")

    if any(city in bio for city in US_CITY_KEYWORDS):
        hits += 1
        city = next(c for c in US_CITY_KEYWORDS if c in bio)
        evidence.append(f"city:{city}")

    if "🇺🇸" in candidate.bio or "usa" in bio:
        hits += 1
        evidence.append("flag_or_usa")

    if any(slang in bio for slang in US_SLANG_MARKERS):
        hits += 1
        evidence.append("us_slang")

    return hits >= 1, evidence


def filter_target(candidate: TargetCandidate) -> TargetFilterResult:
    """Run a single candidate through male + US + health filters.

    Phase 0 rules:
    - Must be classified male
    - Must be US-located (with loose 1-of-4 threshold)
    - Must not be private (we can't DM or engage fully)
    - Must not be verified (too high-profile; low conversion)
    - Must not be business (low conversion for OF funnel)
    - Must have between 30 and 5,000 followers (real users, not influencers)
    """
    reasons: list[str] = []
    is_male, male_ev = classify_male(candidate)
    is_us, us_ev = classify_us_target(candidate)
    reasons.extend(male_ev)
    reasons.extend(us_ev)

    if not is_male:
        return TargetFilterResult(candidate.username, False, is_male, is_us,
                                  reasons + ["reject:not_male"])
    if not is_us:
        return TargetFilterResult(candidate.username, False, is_male, is_us,
                                  reasons + ["reject:not_us"])
    if candidate.is_private:
        return TargetFilterResult(candidate.username, False, True, True,
                                  reasons + ["reject:private"])
    if candidate.is_verified:
        return TargetFilterResult(candidate.username, False, True, True,
                                  reasons + ["reject:verified"])
    if candidate.is_business:
        return TargetFilterResult(candidate.username, False, True, True,
                                  reasons + ["reject:business"])
    if candidate.follower_count < 30 or candidate.follower_count > 5000:
        return TargetFilterResult(candidate.username, False, True, True,
                                  reasons + [f"reject:followers={candidate.follower_count}"])

    return TargetFilterResult(candidate.username, True, True, True, reasons)


def filter_targets(candidates: list[TargetCandidate]) -> list[TargetCandidate]:
    """Apply filter_target across a batch, keeping only passing candidates."""
    return [c for c in candidates if filter_target(c).passes]
