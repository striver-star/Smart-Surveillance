"""In-console help: the role guides in app/help/*.md, readable without internet."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .auth import require

router = APIRouter(prefix="/help", tags=["help"])
DIR = Path(__file__).parent / "help"
GUIDES = {"operator": ("Operator guide", ("admin", "cso", "operator")), "cso": ("CSO guide", ("admin", "cso")),
          "admin": ("Administrator guide", ("admin",)), "management": ("Management guide", ("admin", "cso", "management"))}


@router.get("")
def list_guides(user: dict = Depends(require())) -> list[dict]:
    return [{"id": k, "title": t, "mine": k == user["role"]} for k, (t, roles) in GUIDES.items() if user["role"] in roles]


@router.get("/{gid}")
def guide(gid: str, user: dict = Depends(require())) -> dict:
    if gid not in GUIDES or user["role"] not in GUIDES[gid][1]:
        raise HTTPException(status_code=404, detail="no such guide")
    return {"id": gid, "title": GUIDES[gid][0], "text": (DIR / f"{gid}.md").read_text(encoding="utf-8")}
