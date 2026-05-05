"""
Inbound webhook — implemented in Phase 5.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
