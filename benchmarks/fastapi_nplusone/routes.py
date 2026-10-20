import time
import requests
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .models import User, Profile

router = APIRouter()

# Dependency to get DB session
def get_db():
    pass

@router.get("/users/profiles")
def list_user_profiles(db: Session = Depends(get_db)):
    """
    ANTIPATTERN 1: N+1 Database Query Explosion.
    Queries all users, then runs an individual query for each user's profile inside a loop.
    """
    users = db.query(User).all()
    results = []
    
    # N+1 query trigger
    for user in users:
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        results.append({
            "username": user.username,
            "bio": profile.bio if profile else None,
        })
    return results


@router.get("/reports/generate")
async def generate_report_endpoint():
    """
    ANTIPATTERN 2: Blocking synchronous calls inside async event loop.
    Calling time.sleep() and synchronous requests.get() freezes all concurrent async requests!
    """
    # Blocking call in async def
    time.sleep(2)
    response = requests.get("https://httpbin.org/json")
    return {"status": "generated", "data": response.json()}
