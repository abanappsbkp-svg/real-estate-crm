"""
Demo data (admin only)
Fills the organization with realistic sample records, and removes them again.
Every demo record is marked (custom_fields.demo = true, or call notes = "[demo]")
so removal never touches real data.
"""

import random
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from db import get_db
from middleware_auth import require_role
from models import (
    User, UserRole, Property, Client, ClientInteraction, Deal, DealStageHistory, CallLog,
)

router = APIRouter(prefix="/admin/demo-data", tags=["Demo data"])

DEMO_TAG = {"demo": True}
CALL_NOTE = "[demo]"

CITIES = [
    ("Yerevan", "Yerevan", "Armenia", ["Abovyan St", "Tumanyan St", "Mashtots Ave", "Baghramyan Ave", "Sayat-Nova Ave", "Komitas Ave", "Arabkir 12th St", "Northern Ave"]),
    ("Gyumri", "Shirak", "Armenia", ["Rizhkov St", "Abovyan St", "Vardanants Sq"]),
    ("Tehran", "Tehran", "Iran", ["Valiasr St", "Shariati St", "Enghelab St", "Niavaran Ave", "Pasdaran St", "Mirdamad Blvd"]),
    ("Isfahan", "Isfahan", "Iran", ["Chahar Bagh St", "Nazar St", "Hakim Nezami St"]),
]
FIRST = ["Ani", "Aram", "Narek", "Lilit", "Davit", "Mariam", "Tigran", "Gayane", "Reza", "Sara", "Ali", "Maryam",
         "Dariush", "Neda", "Arash", "Shirin", "Ivan", "Olga", "Sergey", "Elena", "Karen", "Hasmik", "Armen", "Parisa"]
LAST = ["Petrosyan", "Hovhannisyan", "Sargsyan", "Grigoryan", "Karapetyan", "Mkrtchyan", "Ahmadi", "Hosseini",
        "Karimi", "Rezaei", "Moradi", "Ivanov", "Smirnova", "Kuznetsov", "Avetisyan", "Harutyunyan"]
FEATURES = ["parking", "balcony", "elevator", "storage", "garden", "pool", "renovated", "furnished", "view", "heating"]
TYPES = ["apartment"] * 5 + ["house"] * 2 + ["villa", "office", "commercial", "land", "townhouse"]
STAGES = ["lead", "offer", "negotiation", "inspection", "appraisal", "closed"]
INTERACTIONS = ["call", "email", "meeting", "showing", "offer"]
NOTES = [
    "Looking for a quiet area near a school.", "Needs to move within 3 months.", "Prefers a high floor with a view.",
    "Cash buyer, flexible on timing.", "Wants a property to rent out.", "Relocating from abroad.",
]


def _ago(days_max, days_min=0):
    return datetime.utcnow() - timedelta(days=random.randint(days_min, days_max), hours=random.randint(0, 23))


@router.post("")
async def create_demo_data(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Add about 100 sample records (30 properties, 30 clients, 20 deals, 20 calls, plus interactions)."""
    org_id = current_user.organization_id
    agent_id = current_user.id
    agents = [u.id for u in db.query(User).filter(User.organization_id == org_id, User.role.in_(["agent", "admin"])).all()] or [agent_id]

    # ---- Properties
    properties = []
    for i in range(30):
        city, state, country, streets = random.choice(CITIES)
        ptype = random.choice(TYPES)
        beds = 0 if ptype in ("land", "office", "commercial") else random.randint(1, 5)
        area = random.randint(450, 2400) if ptype != "land" else random.randint(3000, 15000)
        per_sqft = random.uniform(8, 25) if ptype == "land" else random.uniform(70, 190)
        price = round(area * per_sqft / 1000) * 1000
        created = _ago(120, 5)
        p = Property(
            organization_id=org_id, listing_agent_id=random.choice(agents), type=ptype,
            status=random.choices(["available", "pending", "reserved", "sold", "rented"], [60, 12, 8, 14, 6])[0],
            address={"street": f"{random.randint(1, 120)} {random.choice(streets)}", "city": city, "state": state,
                     "zip_code": str(random.randint(1000, 99999)), "country": country},
            square_feet=area, bedrooms=beds, bathrooms=max(1, beds - random.randint(0, 2)) if beds else None,
            year_built=random.randint(1965, 2024) if ptype != "land" else None,
            list_price=price, features=random.sample(FEATURES, random.randint(1, 4)),
            description=f"Demo listing: {ptype} in {city}.", custom_fields=dict(DEMO_TAG), tags=["demo"],
            price_history=[{"price": float(price), "reason": "initial_listing", "changed_at": created.isoformat(), "changed_by": None}],
            created_at=created, updated_at=created,
        )
        db.add(p)
        properties.append(p)

    # ---- Clients
    clients = []
    used_emails = set()
    for i in range(30):
        fn, ln = random.choice(FIRST), random.choice(LAST)
        email = f"{fn}.{ln}{i}@demo-example.com".lower()
        used_emails.add(email)
        city, _, country, _ = random.choice(CITIES)
        low = random.randint(6, 30) * 10000
        created = _ago(100, 1)
        c = Client(
            organization_id=org_id, created_by_id=random.choice(agents), assigned_agent_id=random.choice(agents),
            first_name=fn, last_name=ln, email=email,
            phone=("+374 9" if country == "Armenia" else "+98 91") + f"{random.randint(1000000, 9999999)}",
            type=random.choices(["buyer", "seller", "both"], [70, 20, 10])[0],
            status=random.choices(["active", "inactive"], [85, 15])[0],
            source=random.choice(["website", "referral", "cold_call", "social_media", "walk_in"]),
            budget_min=low, budget_max=low + random.randint(5, 25) * 10000,
            property_type_preferences=random.sample(["apartment", "house", "villa", "townhouse"], random.randint(1, 2)),
            bedroom_preferences=random.randint(1, 4), location_preferences={"cities": [city]},
            notes=random.choice(NOTES), custom_fields=dict(DEMO_TAG), interaction_count=0,
            created_at=created, updated_at=created,
        )
        db.add(c)
        clients.append(c)
    db.flush()

    # ---- Interactions (about 45)
    interactions = 0
    for c in clients:
        for _ in range(random.randint(0, 3)):
            when = _ago(60)
            follow = datetime.utcnow() + timedelta(days=random.randint(-5, 14)) if random.random() < 0.3 else None
            db.add(ClientInteraction(
                client_id=c.id, organization_id=org_id, agent_id=random.choice(agents),
                interaction_type=random.choice(INTERACTIONS), description=random.choice(NOTES),
                duration_minutes=random.choice([5, 10, 15, 30, 45, 60]),
                property_id=random.choice(properties).id if random.random() < 0.5 else None,
                follow_up_date=follow, created_at=when, updated_at=when,
            ))
            c.interaction_count = (c.interaction_count or 0) + 1
            c.last_interaction_at = max(c.last_interaction_at or when, when)
            interactions += 1

    # ---- Deals
    deals = 0
    for _ in range(20):
        c, p = random.choice(clients), random.choice(properties)
        stage_idx = random.randint(0, 5)
        stage = STAGES[stage_idx]
        status = "won" if stage == "closed" else random.choices(["active", "lost"], [85, 15])[0]
        asking = float(p.list_price)
        offer = round(asking * random.uniform(0.9, 1.0) / 1000) * 1000 if stage_idx >= 1 else None
        created = _ago(90, 10)
        d = Deal(
            organization_id=org_id, client_id=c.id, property_id=p.id, agent_id=random.choice(agents),
            deal_type="sale", stage=stage, status=status,
            proposed_price=asking, offer_price=offer,
            earnest_money=round(asking * 0.02, -2) if stage_idx >= 2 else None,
            expected_closing_date=datetime.utcnow() + timedelta(days=random.randint(10, 90)),
            closed_at=_ago(9) if status in ("won", "lost") else None,
            is_active=status == "active", notes="Demo deal", custom_fields=dict(DEMO_TAG),
            created_at=created, updated_at=created,
        )
        db.add(d)
        db.flush()
        prev, t = None, created
        for s in STAGES[: stage_idx + 1]:
            db.add(DealStageHistory(deal_id=d.id, from_stage=prev, to_stage=s, changed_by=d.agent_id,
                                    reason="Deal created" if prev is None else None, created_at=t))
            prev, t = s, t + timedelta(days=random.randint(2, 12))
        deals += 1

    # ---- Calls
    for _ in range(20):
        c = random.choice(clients)
        summary = random.random() < 0.6
        db.add(CallLog(
            organization_id=org_id, agent_id=random.choice(agents), client_id=c.id,
            property_id=random.choice(properties).id if random.random() < 0.5 else None,
            call_type=random.choice(["inbound", "outbound", "callback"]), phone_number=c.phone_primary,
            duration_seconds=random.randint(40, 1500), notes=CALL_NOTE,
            ai_summary="Client interested; asked for more options." if summary else None,
            sentiment_label=random.choice(["positive", "neutral", "negative"]) if summary else None,
            call_quality=random.choice(["excellent", "good", "fair"]) if summary else None,
            action_items=["Send more listings"] if summary else [],
            created_at=_ago(30),
        ))

    db.commit()
    return {
        "status": "success",
        "message": "Demo data added",
        "data": {"properties": 30, "clients": 30, "deals": deals, "calls": 20, "interactions": interactions},
    }


@router.delete("")
async def delete_demo_data(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Remove every demo record created by POST /admin/demo-data. Real data is not touched."""
    org = {"org": str(current_user.organization_id)}
    demo = "custom_fields ->> 'demo' = 'true'"
    try:
        counts = {}
        counts["calls"] = db.execute(text("DELETE FROM call_logs WHERE organization_id = :org AND notes = '[demo]'"), org).rowcount
        demo_clients = f"SELECT id FROM clients WHERE organization_id = :org AND {demo}"
        demo_props = f"SELECT id FROM properties WHERE organization_id = :org AND {demo}"
        demo_deals = f"SELECT id FROM deals WHERE organization_id = :org AND ({demo} OR client_id IN ({demo_clients}) OR property_id IN ({demo_props}))"
        db.execute(text(f"DELETE FROM deal_stage_history WHERE deal_id IN ({demo_deals})"), org)
        db.execute(text(f"UPDATE documents SET deal_id = NULL WHERE deal_id IN ({demo_deals})"), org)
        counts["deals"] = db.execute(text(
            f"DELETE FROM deals WHERE organization_id = :org AND ({demo} OR client_id IN ({demo_clients}) OR property_id IN ({demo_props}))"), org).rowcount
        db.execute(text(f"DELETE FROM client_interactions WHERE client_id IN ({demo_clients})"), org)
        db.execute(text(f"DELETE FROM property_matches WHERE client_id IN ({demo_clients}) OR property_id IN ({demo_props})"), org)
        db.execute(text(f"UPDATE client_interactions SET property_id = NULL WHERE property_id IN ({demo_props})"), org)
        db.execute(text(f"UPDATE call_logs SET property_id = NULL WHERE property_id IN ({demo_props})"), org)
        db.execute(text(f"UPDATE call_logs SET client_id = NULL WHERE client_id IN ({demo_clients})"), org)
        for table in ("documents",):
            db.execute(text(f"UPDATE {table} SET client_id = NULL WHERE client_id IN ({demo_clients})"), org)
            db.execute(text(f"UPDATE {table} SET property_id = NULL WHERE property_id IN ({demo_props})"), org)
        db.execute(text(f"DELETE FROM showings WHERE client_id IN ({demo_clients}) OR property_id IN ({demo_props})"), org)
        db.execute(text(f"DELETE FROM property_history WHERE property_id IN ({demo_props})"), org)
        counts["clients"] = db.execute(text(f"DELETE FROM clients WHERE organization_id = :org AND {demo}"), org).rowcount
        counts["properties"] = db.execute(text(f"DELETE FROM properties WHERE organization_id = :org AND {demo}"), org).rowcount
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Could not remove demo data: {e}")
    return {"status": "success", "message": "Demo data removed", "data": counts}
