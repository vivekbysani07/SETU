"""
Seed region data for all five BRICS countries in this demo.

In production, this table is replaced by a scheduled ingestion job pulling
from real census, infrastructure-ministry, and public-investment-plan APIs
per country. Here it is static, illustrative data so the priority formula
has real numbers to combine with real citizen submissions.
"""
from database import SessionLocal
from models import Region

# India only for now. Other countries' data below is kept for later, but is not seeded.
COUNTRIES = {"IN": "India"}

REGIONS = {
    "IN": [
        # Andhra Pradesh (illustrative figures, like the rest of this table)
        ("Visakhapatnam, Andhra Pradesh", 0.31, 0.48, 0.40),
        ("Vijayawada, Andhra Pradesh",    0.27, 0.55, 0.50),
        ("Guntur, Andhra Pradesh",        0.33, 0.47, 0.38),
        ("Tirupati, Andhra Pradesh",      0.29, 0.52, 0.48),
        ("Rajahmundry, Andhra Pradesh",   0.30, 0.50, 0.42),
        ("Nellore, Andhra Pradesh",       0.34, 0.46, 0.36),
        ("Kurnool, Andhra Pradesh",       0.41, 0.38, 0.30),
        ("Kadapa, Andhra Pradesh",        0.40, 0.40, 0.32),
        ("Anantapur, Andhra Pradesh",     0.44, 0.35, 0.27),
        ("Srikakulam, Andhra Pradesh",    0.46, 0.34, 0.26),
        ("Guwahati, Assam",       0.42, 0.38, 0.30),
        ("Bhubaneswar, Odisha",   0.35, 0.50, 0.45),
        ("Nagpur, Maharashtra",   0.28, 0.55, 0.55),
        ("Rajkot, Gujarat",       0.22, 0.62, 0.60),
        ("Noida, Uttar Pradesh",  0.18, 0.70, 0.75),
    ],
    "BR": [
        ("São Paulo — Zona Leste", 0.30, 0.55, 0.50),
        ("Salvador — Subúrbio",    0.45, 0.35, 0.25),
        ("Manaus — Zona Norte",    0.50, 0.30, 0.20),
        ("Recife — Zona Oeste",    0.40, 0.40, 0.30),
    ],
    "RU": [
        ("Kazan",       0.20, 0.65, 0.55),
        ("Novosibirsk", 0.25, 0.55, 0.45),
        ("Vladivostok", 0.35, 0.40, 0.30),
        ("Krasnodar",   0.22, 0.60, 0.50),
    ],
    "CN": [
        ("Chengdu", 0.18, 0.70, 0.65),
        ("Xi'an",   0.22, 0.62, 0.55),
        ("Kunming", 0.30, 0.48, 0.35),
        ("Harbin",  0.28, 0.50, 0.40),
    ],
    "ZA": [
        ("Soweto",            0.48, 0.35, 0.25),
        ("Durban Townships",  0.50, 0.32, 0.22),
        ("Polokwane",         0.42, 0.38, 0.28),
        ("Bloemfontein",      0.38, 0.45, 0.35),
    ],
}

SECTORS = [
    "Water & sanitation", "Roads & transport", "Healthcare",
    "Electricity", "Education", "Public safety", "Other",
]


def seed():
    db = SessionLocal()
    try:
        existing = {(r.country_code, r.name) for r in db.query(Region).all()}
        for country_code, regions in REGIONS.items():
            if country_code not in COUNTRIES:
                continue
            for name, poverty, infra, investment in regions:
                if (country_code, name) in existing:
                    continue
                db.add(Region(
                    country_code=country_code, name=name,
                    poverty_index=poverty, infra_score=infra, investment_level=investment,
                ))
        db.commit()
        print("Seeded regions for:", ", ".join(COUNTRIES.values()))
    finally:
        db.close()


if __name__ == "__main__":
    from database import Base, engine
    Base.metadata.create_all(bind=engine)
    seed()
