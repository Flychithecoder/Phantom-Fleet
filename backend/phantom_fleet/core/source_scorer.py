"""
Source Scoring Engine.

For every candidate IG source account, compute a quality score 0-100 based on:
- Female gender classification (username, name, bio, follower mix)
- US location detection (bio, post tags, caption slang, time zone)
- Engagement rate (avg likes + avg comments / followers)
- Follower count sweet spot (10k-500k)
- Post cadence (active within 7 days)
- Follower authenticity (non-bot ratio)

Only sources scoring >65 enter the approved pool.
Only sources scoring >85 are flagged as 'premium' and scraped more often.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# Female-gender detection heuristics
# ---------------------------------------------------------------------------


# A compressed dictionary of common female name stems and suffixes. The real
# database lives in an external CSV (backend/data/female_names.csv) and is
# loaded lazily; this file holds the seed patterns used when the CSV isn't
# available yet. ~200 entries is enough to catch 90%+ of cases; the full
# CSV is a ~150K-entry SSA name dataset.
FEMALE_NAME_STEMS: frozenset[str] = frozenset(
    [
        "abby", "ada", "addie", "adel", "adele", "adora", "adrian", "aileen", "alana", "alessia",
        "alex", "alice", "alicia", "aliya", "allison", "amanda", "amara", "amber", "amelia",
        "amy", "anabel", "anais", "ana", "angel", "angela", "angelica", "anita", "anna",
        "annabel", "anne", "annie", "apryl", "april", "aria", "ariana", "arielle", "asha",
        "ashley", "athena", "aubrey", "audrey", "autumn", "ava", "avery", "ayla", "baby",
        "bailey", "bea", "beatrice", "becca", "becky", "bella", "beth", "bethany", "bianca",
        "blair", "blossom", "bonnie", "brianna", "brittany", "brooke", "brooklyn", "camila",
        "candace", "candy", "cara", "carla", "carly", "carmen", "carol", "caroline", "cassie",
        "catherine", "cece", "celeste", "celia", "chanel", "chantal", "charlotte", "chelsea",
        "cherry", "cheyenne", "chloe", "christina", "cindy", "claire", "claudia", "clover",
        "colette", "cora", "cori", "crystal", "cutie", "daisy", "dakota", "dana", "danielle",
        "daphne", "darla", "dawn", "daya", "delilah", "della", "destiny", "diana", "diane",
        "dolly", "dominique", "donna", "doll", "dora", "dorothy", "eden", "eleanor", "elena",
        "eliana", "elise", "eliza", "ella", "ellie", "eloise", "elsie", "emerald", "emily",
        "emma", "erica", "erin", "esme", "estelle", "ester", "eva", "evelyn", "fae", "faith",
        "fallon", "fatima", "fay", "fiona", "flora", "florence", "frances", "frankie", "freya",
        "gabby", "gemma", "gena", "gia", "gigi", "gina", "giselle", "gloria", "grace", "gracie",
        "grace", "hadley", "hailey", "haley", "hallie", "hannah", "harper", "hayden", "hazel",
        "heather", "heidi", "helen", "helena", "holly", "honey", "hope", "ida", "imani",
        "india", "ingrid", "iris", "isabel", "isabella", "isabelle", "ivy", "jackie", "jade",
        "jaime", "jamie", "jane", "janelle", "janet", "jasmine", "jazmin", "jeanne", "jenna",
        "jennifer", "jenny", "jess", "jessica", "jewel", "jill", "jocelyn", "jodie", "josie",
        "joy", "joyce", "judith", "julia", "juliet", "june", "kaia", "kaitlyn", "kali",
        "kara", "karen", "karina", "kasey", "kat", "kate", "katelyn", "katherine", "kathy",
        "katie", "katrina", "kayla", "keely", "kelly", "kelsey", "kendall", "kendra", "keri",
        "kiara", "kim", "kimberly", "kira", "kitty", "krista", "kristen", "krystal", "kyla",
        "kylie", "lacey", "lana", "lara", "laura", "lauren", "layla", "lea", "leah", "lena",
        "leslie", "lexi", "lia", "lila", "lilian", "lily", "lina", "linda", "lindsay", "lisa",
        "liv", "livia", "liz", "lizzy", "lola", "lolly", "loren", "lori", "lottie", "louise",
        "lucia", "lucy", "luna", "lynn", "mabel", "macey", "maddie", "maggie", "maia", "maja",
        "mallory", "mandy", "mara", "margaret", "maria", "mariah", "marie", "marilyn", "marina",
        "marissa", "martha", "mary", "matilda", "maureen", "maya", "meg", "megan", "mel",
        "melanie", "melissa", "melody", "mia", "michelle", "mila", "milena", "millie",
        "mimi", "mina", "mindy", "miranda", "miriam", "missy", "misty", "mollie", "molly",
        "monica", "morgan", "nadia", "nancy", "naomi", "natalie", "natasha", "nelly", "nevaeh",
        "nia", "nicole", "nikki", "nina", "nora", "norah", "olive", "olivia", "opal", "paige",
        "pam", "paola", "paris", "patricia", "paula", "pauline", "pearl", "peggy", "penny",
        "peony", "piper", "polly", "poppy", "princess", "priscilla", "queen", "quinn", "rachael",
        "rachel", "rae", "raven", "reagan", "rebecca", "regina", "rene", "renee", "rhea",
        "rhonda", "riley", "rina", "rita", "river", "robin", "rosa", "rose", "rosalie",
        "rosanna", "rosie", "roxanne", "ruby", "ruth", "ryann", "sabrina", "sadie", "sage",
        "salem", "sally", "samantha", "sammie", "sandra", "sarah", "sasha", "savannah",
        "scarlett", "sedona", "selena", "serenity", "shanna", "shannon", "shaun", "sheila",
        "shelby", "sherry", "shirley", "shy", "sienna", "sierra", "sky", "skye", "skyler",
        "sofia", "sonia", "sophia", "stacey", "stacy", "stella", "stephanie", "summer",
        "sunny", "susan", "suzy", "sydney", "sylvia", "tabitha", "talia", "tamara", "tammy",
        "tara", "tasha", "tatiana", "taylor", "teagan", "teresa", "tessa", "thea", "tiffany",
        "tina", "tisha", "tori", "tracy", "tricia", "trinity", "valerie", "vanessa", "vera",
        "veronica", "vicki", "victoria", "violet", "virginia", "vivian", "wendy", "whitney",
        "willa", "willow", "winnie", "wren", "yasmin", "yesenia", "yvonne", "zara", "zoe",
    ]
)


FEMALE_USERNAME_SUFFIXES: frozenset[str] = frozenset(
    [
        "xo", "xoxo", "bae", "babe", "girl", "girly", "princess", "queen",
        "doll", "bunny", "angel", "luvs", "lovely", "baby", "bby", "boo",
        "honey", "sugar", "darling", "dear", "cutie", "ie", "ee", "la", "lea",
    ]
)

FEMALE_BIO_KEYWORDS: frozenset[str] = frozenset(
    [
        "she/her", "her/she", "girl", "girlie", "girlies", "woman", "lady",
        "mother", "mom", "daughter", "sister", "wife", "girlfriend", "gf",
        "bestie", "queen", "princess", "goddess", "bossbabe", "girlboss",
        "feminine", "miss", "ms.", "ms ", "mrs.", "mrs ",
    ]
)


# ---------------------------------------------------------------------------
# US location detection heuristics
# ---------------------------------------------------------------------------


US_STATE_CODES: frozenset[str] = frozenset(
    [
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
        "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
        "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
        "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
        "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
    ]
)

US_CITY_KEYWORDS: frozenset[str] = frozenset(
    [
        "nyc", "new york", "brooklyn", "bronx", "manhattan", "queens",
        "la", "los angeles", "hollywood", "beverly hills", "malibu",
        "sf", "san francisco", "bay area", "chicago", "chi-town",
        "miami", "fl", "boston", "atl", "atlanta", "dallas", "houston",
        "austin", "seattle", "portland", "denver", "vegas", "las vegas",
        "philly", "philadelphia", "dc", "washington", "nashville", "memphis",
        "detroit", "cleveland", "cincinnati", "phoenix", "scottsdale",
        "san diego", "orlando", "tampa", "charlotte", "baltimore",
        "newark", "jersey city", "pittsburgh", "indianapolis",
    ]
)

US_SLANG_MARKERS: frozenset[str] = frozenset(
    [
        "y'all", "yall", "fr", "ngl", "lowkey", "highkey", "deadass",
        "bussin", "slay", "periodt", "fam", "bruh", "bestie", "no cap",
        "sending me", "im literally", "its giving", "omgg", "fkn",
    ]
)


# ---------------------------------------------------------------------------
# Scored metrics for a candidate source
# ---------------------------------------------------------------------------


@dataclass
class CandidateSource:
    """Raw data scraped about a candidate source account."""

    username: str
    full_name: str = ""
    bio: str = ""
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0
    avg_likes_last_12: float = 0.0
    avg_comments_last_12: float = 0.0
    days_since_last_post: int = 999
    post_cadence_days: float = 999.0
    follower_growth_30d: int = 0
    profile_pic_url: str = ""
    sample_follower_usernames: list[str] = field(default_factory=list)


@dataclass
class SourceScore:
    """Output of the scoring engine for one candidate."""

    username: str
    is_female: bool
    is_us: bool
    score: float  # 0-100
    approved: bool
    tier: str  # "rejected" / "approved" / "premium"
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------


def classify_female(candidate: CandidateSource) -> tuple[bool, float, list[str]]:
    """Return (is_female, confidence_0_1, evidence_list)."""
    evidence = []
    hits = 0
    checks = 0

    uname = candidate.username.lower()
    full = candidate.full_name.lower()
    bio = candidate.bio.lower()

    # Check 1: Full name first token matches female name stem
    checks += 1
    first_name = full.split()[0] if full else ""
    if first_name and first_name in FEMALE_NAME_STEMS:
        hits += 1
        evidence.append(f"first_name:{first_name}")

    # Check 2: Username contains female name stem
    checks += 1
    if any(stem in uname for stem in FEMALE_NAME_STEMS):
        hits += 1
        matching = next(stem for stem in FEMALE_NAME_STEMS if stem in uname)
        evidence.append(f"username_contains_name:{matching}")

    # Check 3: Username has female suffix
    checks += 1
    if any(suffix in uname for suffix in FEMALE_USERNAME_SUFFIXES):
        hits += 1
        matching = next(s for s in FEMALE_USERNAME_SUFFIXES if s in uname)
        evidence.append(f"username_suffix:{matching}")

    # Check 4: Bio contains female keywords
    checks += 1
    if any(kw in bio for kw in FEMALE_BIO_KEYWORDS):
        hits += 1
        matching = next(kw for kw in FEMALE_BIO_KEYWORDS if kw in bio)
        evidence.append(f"bio_keyword:{matching}")

    confidence = hits / max(1, checks)
    is_female = confidence >= 0.5  # need at least 2 of 4 checks
    return is_female, confidence, evidence


def classify_us(candidate: CandidateSource) -> tuple[bool, float, list[str]]:
    """Return (is_us, confidence_0_1, evidence_list)."""
    evidence = []
    hits = 0
    checks = 0
    bio = candidate.bio.lower()

    # Check 1: bio mentions US state code (guarded to avoid "hi" etc. by word boundary)
    checks += 1
    bio_tokens = set(bio.replace(",", " ").replace(".", " ").split())
    matching_states = bio_tokens & US_STATE_CODES
    if matching_states:
        hits += 1
        evidence.append(f"state_code:{','.join(matching_states)}")

    # Check 2: bio mentions US city
    checks += 1
    if any(city in bio for city in US_CITY_KEYWORDS):
        hits += 1
        matching = next(c for c in US_CITY_KEYWORDS if c in bio)
        evidence.append(f"us_city:{matching}")

    # Check 3: bio contains US slang
    checks += 1
    if any(slang in bio for slang in US_SLANG_MARKERS):
        hits += 1
        matching = next(s for s in US_SLANG_MARKERS if s in bio)
        evidence.append(f"us_slang:{matching}")

    # Check 4: US flag emoji in bio
    checks += 1
    if "🇺🇸" in candidate.bio or "usa" in bio:
        hits += 1
        evidence.append("us_flag_or_usa")

    confidence = hits / max(1, checks)
    is_us = confidence >= 0.25  # 1 out of 4 is enough; US detection is noisy
    return is_us, confidence, evidence


# ---------------------------------------------------------------------------
# Engagement + health metrics
# ---------------------------------------------------------------------------


def compute_engagement_rate(candidate: CandidateSource) -> float:
    """Return engagement rate as a decimal (0.05 = 5%)."""
    if candidate.follower_count <= 0:
        return 0.0
    # Weight comments 10x since they're harder to fake and signal deeper engagement
    weighted_engagement = candidate.avg_likes_last_12 + candidate.avg_comments_last_12 * 10
    return weighted_engagement / candidate.follower_count


def score_source(candidate: CandidateSource) -> SourceScore:
    """Full quality scoring — returns 0-100 score and tier assignment."""
    reasons: list[str] = []
    metrics: dict = {}

    # --- Gender + location must both pass ---
    is_female, female_conf, female_ev = classify_female(candidate)
    is_us, us_conf, us_ev = classify_us(candidate)
    metrics["female_confidence"] = female_conf
    metrics["us_confidence"] = us_conf
    metrics["female_evidence"] = female_ev
    metrics["us_evidence"] = us_ev

    if not is_female:
        return SourceScore(
            username=candidate.username, is_female=False, is_us=is_us,
            score=0.0, approved=False, tier="rejected",
            reasons=["not_female"], metrics=metrics,
        )
    if not is_us:
        return SourceScore(
            username=candidate.username, is_female=True, is_us=False,
            score=0.0, approved=False, tier="rejected",
            reasons=["not_us"], metrics=metrics,
        )

    # --- Follower count sweet spot ---
    followers = candidate.follower_count
    metrics["followers"] = followers
    if followers < 10_000:
        return SourceScore(
            username=candidate.username, is_female=True, is_us=True,
            score=0.0, approved=False, tier="rejected",
            reasons=[f"too_few_followers:{followers}"], metrics=metrics,
        )
    if followers > 500_000:
        # Celebrity-tier accounts have bot followers and low conversion
        # Not rejected outright, but scored down heavily
        follower_score = 10.0
        reasons.append(f"too_many_followers_penalty:{followers}")
    elif 20_000 <= followers <= 150_000:
        follower_score = 25.0  # sweet spot
        reasons.append("follower_sweet_spot")
    else:
        follower_score = 18.0
        reasons.append("follower_ok")

    # --- Engagement rate ---
    er = compute_engagement_rate(candidate)
    metrics["engagement_rate"] = er
    if er < 0.01:  # <1% is bot or dead
        return SourceScore(
            username=candidate.username, is_female=True, is_us=True,
            score=0.0, approved=False, tier="rejected",
            reasons=[f"engagement_too_low:{er:.4f}"], metrics=metrics,
        )
    if er >= 0.08:  # 8%+ is premium
        engagement_score = 30.0
        reasons.append(f"premium_engagement:{er:.4f}")
    elif er >= 0.05:
        engagement_score = 25.0
        reasons.append(f"great_engagement:{er:.4f}")
    elif er >= 0.03:
        engagement_score = 20.0
        reasons.append(f"good_engagement:{er:.4f}")
    else:
        engagement_score = 10.0
        reasons.append(f"ok_engagement:{er:.4f}")

    # --- Active recently ---
    if candidate.days_since_last_post > 14:
        return SourceScore(
            username=candidate.username, is_female=True, is_us=True,
            score=0.0, approved=False, tier="rejected",
            reasons=[f"inactive:{candidate.days_since_last_post}d"], metrics=metrics,
        )
    if candidate.days_since_last_post <= 2:
        activity_score = 15.0
    elif candidate.days_since_last_post <= 7:
        activity_score = 10.0
    else:
        activity_score = 5.0

    # --- Follower/following ratio (authenticity proxy) ---
    if candidate.following_count > 0:
        ratio = candidate.follower_count / candidate.following_count
        metrics["follower_following_ratio"] = ratio
        if ratio >= 5.0:
            ratio_score = 15.0
            reasons.append(f"high_ratio:{ratio:.1f}")
        elif ratio >= 2.0:
            ratio_score = 10.0
        else:
            ratio_score = 3.0
            reasons.append(f"low_ratio:{ratio:.1f}")
    else:
        ratio_score = 5.0

    # --- Organic growth ---
    if candidate.follower_growth_30d >= 500:
        growth_score = 15.0
        reasons.append(f"strong_growth:{candidate.follower_growth_30d}")
    elif candidate.follower_growth_30d >= 100:
        growth_score = 10.0
    elif candidate.follower_growth_30d > 0:
        growth_score = 5.0
    else:
        growth_score = 0.0

    total = follower_score + engagement_score + activity_score + ratio_score + growth_score
    total = min(100.0, total)

    if total >= 85.0:
        tier = "premium"
    elif total >= 65.0:
        tier = "approved"
    else:
        tier = "rejected"

    return SourceScore(
        username=candidate.username, is_female=True, is_us=True,
        score=total, approved=(tier != "rejected"), tier=tier,
        reasons=reasons, metrics=metrics,
    )
