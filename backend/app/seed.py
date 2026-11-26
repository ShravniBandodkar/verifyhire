"""Idempotent demo seed: a governor, two employers (one legitimate, one shell), ~30 synthetic
candidates, references (including a fake reference ring), jobs — then lets the agents run."""
import logging
import random

from sqlalchemy.orm import Session

from .agents import kyb_underwriting, resume_architect, talent_matchmaker
from .core import vault
from .core.security import hash_password
from .models import CandidateProfile, Company, Job, Reference, User, now
from .services.embeddings import normalize_skill
from .services.gov import verhoeff_digit

log = logging.getLogger("seed")

FIRST = ["Rahul", "Ananya", "Arjun", "Priya", "Vikram", "Sneha", "Karthik", "Meera", "Rohan", "Divya", "Aditya", "Kavya",
         "Siddharth", "Pooja", "Nikhil", "Ishita", "Varun", "Neha", "Harsh", "Tanvi", "Manish", "Riya", "Akash", "Shruti",
         "Gaurav", "Lakshmi", "Yash", "Nandini"]
LAST = ["Kumar", "Iyer", "Mehta", "Reddy", "Sharma", "Nair", "Rao", "Gupta", "Patel", "Menon", "Joshi", "Singh", "Das", "Pillai"]
CITIES = ["Bengaluru", "Bengaluru", "Bengaluru", "Pune", "Hyderabad", "Mumbai", "Chennai", "Gurugram", "Noida", "Kochi"]
STACKS = [
    ("Full Stack Engineer", ["react", "typescript", "node", "postgresql", "amazon web services", "docker"]),
    ("Full Stack Developer", ["react", "javascript", "python", "django", "mysql", "redis"]),
    ("Backend Engineer", ["java", "spring boot", "kafka", "microservices", "postgresql", "kubernetes"]),
    ("Backend Engineer", ["go", "kubernetes", "grpc", "postgresql", "terraform", "google cloud"]),
    ("AI/ML Engineer", ["python", "pytorch", "langchain", "rag", "large language models", "fastapi"]),
    ("Data Engineer", ["python", "spark", "airflow", "sql", "amazon web services", "kafka"]),
    ("Frontend Engineer", ["react", "next.js", "typescript", "tailwind", "graphql", "playwright"]),
    ("DevOps Engineer", ["kubernetes", "terraform", "amazon web services", "ci/cd", "linux", "docker"]),
    ("Mobile Engineer", ["flutter", "react native", "kotlin", "swift", "rest", "git"]),
]
EMPLOYERS = ["Infosys Limited", "Tata Consultancy Services Limited", "Wipro Limited", "Freshworks Technologies Private Limited",
             "Zoho Corporation Private Limited", "Razorpay Software Private Limited", "Swiggy Limited", "Nimbus Cloudworks Private Limited"]
DEGREES = [("B.Tech Computer Science", "IIT Bombay"), ("B.E Computer Science", "Anna University"),
           ("B.Tech Information Technology", "VIT Vellore"), ("MCA", "University of Pune"), ("M.Tech Software Systems", "BITS Pilani")]


def _pan(i: int, last: str) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return f"{letters[i % 24]}{letters[(i * 7) % 24]}{letters[(i * 3) % 24]}P{last[0].upper()}{1000 + i * 37:04d}{letters[(i * 5) % 24]}"


def seed(db: Session):
    if db.query(User).filter_by(email="governor@verifyhire.example").first():
        return
    log.info("Seeding demo data…")
    rnd = random.Random(42)
    try:
        from .samples import generate
        generate()
    except Exception as e:
        log.warning("sample docs not generated: %s", e)

    db.add(User(email="governor@verifyhire.example", full_name="Platform Governor", role="admin",
                password_hash=hash_password("Governor@123")))

    nimbus = Company(name="Nimbus Cloudworks Private Limited", pan="AAACN4455F", cin="U72200KA2014PTC074512",
                     gstin="29AAACN4455F1ZG", domain="nimbuscloud.example", website="https://nimbuscloud.example",
                     revenue_bracket="100-500 Cr", headcount=1200, vertical="Cloud SaaS", incorporation_year=2014,
                     locations=["Bengaluru", "Pune"], signatory_name="Kavita Rao")
    quanta = Company(name="Quanta Retail Analytics Private Limited", pan="AAFCQ9921H", cin="U74999MH2019PTC321908",
                     gstin="27AAFCQ9921H1Z5", domain="quanta-retail.example", revenue_bracket="100-500 Cr", headcount=450,
                     vertical="Retail Analytics", incorporation_year=2021, locations=["Mumbai"], signatory_name="Dev Malhotra")
    db.add_all([nimbus, quanta]); db.flush()
    hr = User(email="hr@nimbuscloud.example", full_name="Kavita Rao", role="employer_admin", company_id=nimbus.id,
              password_hash=hash_password("Employer@123"))
    rec = User(email="recruiter@nimbuscloud.example", full_name="Imran Sheikh", role="recruiter", company_id=nimbus.id,
               password_hash=hash_password("Employer@123"))
    qa = User(email="quanta.hiring@gmail.com", full_name="Dev Malhotra", role="employer_admin", company_id=quanta.id,
              password_hash=hash_password("Employer@123"))
    db.add_all([hr, rec, qa]); db.commit()

    # Demo candidate — starts mostly unverified so the live demo shows the agents at work
    aisha = User(email="aisha@demo.example", full_name="Aisha Kapoor", role="candidate", password_hash=hash_password("Candidate@123"))
    db.add(aisha); db.flush()
    db.add(CandidateProfile(user_id=aisha.id, city="Bengaluru", phone="9876543210", headline="Full Stack Engineer",
                            summary="Full-stack engineer building cloud-native SaaS with React, Node.js and Python.",
                            years_experience=5, expected_ctc_lpa=26, dob="1997-03-14",
                            skills=["react", "typescript", "node", "python", "fastapi", "postgresql", "amazon web services"],
                            experience=[{"company": "Nimbus Cloudworks Private Limited", "title": "Software Engineer",
                                         "start": "2019-07", "end": "2024-06", "verified": False}],
                            education=[{"degree": "B.E Computer Science", "institution": "Anna University", "year": "2018", "verified": False}]))

    pw = hash_password("Candidate@123")
    users = []
    for i in range(28):
        fn, ln = FIRST[i], LAST[(i * 5) % len(LAST)]
        title, stack = STACKS[i % len(STACKS)]
        yrs = round(rnd.uniform(1.5, 11), 1)
        ctc = round(4 + yrs * rnd.uniform(2.2, 3.6), 1)
        level = rnd.random()
        jobs_n = max(1, min(3, int(yrs // 3) + 1))
        emps = rnd.sample(EMPLOYERS, jobs_n)
        deg, inst = DEGREES[i % len(DEGREES)]
        u = User(email=f"{fn.lower()}.{ln.lower()}{i}@mail.example", full_name=f"{fn} {ln}", role="candidate", password_hash=pw)
        db.add(u); db.flush()
        pan = _pan(i + 3, ln)
        aad = str(rnd.randint(2, 9)) + "".join(str(rnd.randint(0, 9)) for _ in range(10))
        aad += verhoeff_digit(aad)
        full = level > 0.25
        p = CandidateProfile(
            user_id=u.id, city=CITIES[i % len(CITIES)], phone=f"9{rnd.randint(100000000, 999999999)}",
            headline=f"{'Senior ' if yrs > 6 else ''}{title}", years_experience=yrs, current_ctc_lpa=ctc,
            expected_ctc_lpa=round(ctc * rnd.uniform(1.15, 1.4), 1),
            summary=f"{title} with {yrs} years building production systems using {', '.join(stack[:4])}.",
            skills=sorted({normalize_skill(s) for s in stack + rnd.sample(["git", "rest", "sql", "linux", "system design", "redis"], 2)}),
            experience=[{"company": e, "title": title, "start": f"{2024 - int(yrs) + k * 2}-01", "end": "present" if k == jobs_n - 1 else f"{2024 - int(yrs) + k * 2 + 2}-01",
                         "verified": full} for k, e in enumerate(emps)],
            education=[{"degree": deg, "institution": inst, "year": str(2024 - int(yrs) - 1), "verified": level > 0.4}],
            aadhaar_verified=full, aadhaar_masked=vault.mask_aadhaar(aad) if full else "", aadhaar_token=vault.tokenize(aad, "aadhaar") if full else "",
            pan_verified=level > 0.15, pan_masked=vault.mask_pan(pan) if level > 0.15 else "",
            pan_hash=vault.tokenize(pan, "pan") if level > 0.15 else "",
            pan_sealed=vault.seal_field(pan, u.id) if level > 0.15 else "",
            photo_verified=level > 0.35, degree_verified=level > 0.4, experience_verified=full, ctc_verified=level > 0.5)
        db.add(p)
        users.append(u)
    db.commit()

    # Showcase profiles that exactly satisfy the RFP's example query
    for k, (fn, ln, yrs, ctc, stack) in enumerate([
        ("Kiran", "Shetty", 4.5, 18.5, ["react", "node", "typescript", "postgresql", "amazon web services", "full stack"]),
        ("Deepa", "Krishnan", 5.2, 21.0, ["react", "python", "django", "postgresql", "docker", "full stack"]),
        ("Sameer", "Kulkarni", 5.8, 20.0, ["next.js", "node", "typescript", "mongodb", "kubernetes", "full stack"]),
    ]):
        u = User(email=f"{fn.lower()}.{ln.lower()}@mail.example", full_name=f"{fn} {ln}", role="candidate", password_hash=pw)
        db.add(u); db.flush()
        pan = _pan(40 + k, ln)
        aad = "8" + "".join(str(rnd.randint(0, 9)) for _ in range(10)); aad += verhoeff_digit(aad)
        db.add(CandidateProfile(
            user_id=u.id, city="Bengaluru", phone=f"98{rnd.randint(10000000, 99999999)}", headline="Full Stack Engineer",
            years_experience=yrs, current_ctc_lpa=ctc, expected_ctc_lpa=round(ctc * 1.25, 1), ctc_verified=True,
            summary=f"Full stack engineer, {yrs} years shipping {', '.join(stack[:4])} products.", skills=sorted(stack),
            experience=[{"company": EMPLOYERS[(k + 3) % len(EMPLOYERS)], "title": "Software Engineer", "start": "2019-07", "end": "2022-06", "verified": True},
                        {"company": EMPLOYERS[(k + 5) % len(EMPLOYERS)], "title": "Full Stack Engineer", "start": "2022-07", "end": "present", "verified": True}],
            education=[{"degree": "B.Tech Computer Science", "institution": ["IIT Bombay", "NIT Trichy", "IIIT Hyderabad"][k], "year": "2019", "verified": True}],
            aadhaar_verified=True, aadhaar_masked=vault.mask_aadhaar(aad), aadhaar_token=vault.tokenize(aad, "aadhaar"),
            pan_verified=True, pan_masked=vault.mask_pan(pan), pan_hash=vault.tokenize(pan, "pan"), pan_sealed=vault.seal_field(pan, u.id),
            photo_verified=True, degree_verified=True, experience_verified=True))
        db.flush()
        for r in range(2):
            db.add(Reference(candidate_id=u.id, name=f"{FIRST[(k * 3 + r) % len(FIRST)]} {LAST[(k + r + 4) % len(LAST)]}",
                             email=f"lead{k}{r}@corp.example", company=EMPLOYERS[(k + 3 + 2 * r) % len(EMPLOYERS)],
                             status="verified", rating=5, feedback="Outstanding engineer, strong ownership.", verified_at=now(),
                             analysis={"flags": [], "sentiment": {"sentiment": "positive"}}))
        users.append(u)
    db.commit()

    # Verified references for strong candidates, plus a fake reference ring (one "manager" vouching for 4 people)
    for i, u in enumerate(users):
        if i % 3 != 2:
            for k in range(1 + (i % 2)):
                db.add(Reference(candidate_id=u.id, name=f"{FIRST[(i + k + 7) % len(FIRST)]} {LAST[(i + k) % len(LAST)]}",
                                 email=f"manager{i}{k}@{'nimbuscloud.example' if k == 0 else 'corp.example'}",
                                 company=u.profile.experience[-1]["company"] if u.profile.experience else "",
                                 status="verified", rating=4 + (i % 2), feedback="Reliable, strong engineer. Would rehire.",
                                 verified_at=now(), analysis={"flags": [], "sentiment": {"sentiment": "positive"}}))
    ring_tokens = []
    for u in users[2:6]:
        import secrets
        from .core.security import sha256
        t = secrets.token_urlsafe(24)
        ring_tokens.append(t)
        db.add(Reference(candidate_id=u.id, name="Sunny Verma", email="sunny.verma.hr@gmail.com", company="Wipro Limited",
                         status="sent", relationship_="manager", token_hash=sha256(t)))
    db.commit()

    # Agents take over: KYB, profile architecture, matching
    kyb_underwriting.run(db, nimbus.id)
    kyb_underwriting.run(db, quanta.id)
    for u in [aisha] + users:
        resume_architect.run(db, u.id)
    jobs = [
        dict(title="Senior Full Stack Engineer", skills=["react", "typescript", "node", "postgresql", "amazon web services"],
             location="Bengaluru", min_exp=4, max_exp=8, ctc_min_lpa=18, ctc_max_lpa=32, min_trust=60, require_pan=True,
             description="Own customer-facing React/Node services on AWS for our multi-tenant SaaS platform."),
        dict(title="AI Platform Engineer", skills=["python", "langchain", "rag", "large language models", "fastapi", "kubernetes"],
             location="Bengaluru", min_exp=2, max_exp=7, ctc_min_lpa=20, ctc_max_lpa=40, min_trust=50, require_pan=True,
             description="Build our agentic AI platform: RAG pipelines, LLM orchestration and evaluation tooling."),
        dict(title="DevOps Engineer", skills=["kubernetes", "terraform", "amazon web services", "ci/cd", "docker"],
             location="Pune", min_exp=3, max_exp=10, ctc_max_lpa=30, min_trust=40,
             description="Run our Kubernetes fleet with Terraform, GitOps and strong observability."),
    ]
    from .services.embeddings import embed
    for j in jobs:
        job = Job(company_id=nimbus.id, created_by=hr.id, **j)
        job.embedding = embed(f"{job.title} {job.description} {' '.join(job.skills)}")
        db.add(job); db.commit()
        talent_matchmaker.match_job(db, job.id)
    # The fake referee responds to one link → Reference agent detects the ring and escalates
    from .agents import devsecops, reference_tenure
    reference_tenure.respond(db, ring_tokens[0], True, 5, "Great candidate, highly recommend.", "203.0.113.7")
    devsecops.patrol(db)
    log.info("Seed complete.")
