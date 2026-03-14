"""backend.routers.jobs — Job status and log retrieval."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.db import Job, get_session

router = APIRouter()


@router.get("")
def list_jobs(config_id: Optional[int] = None, session: Session = Depends(get_session)):
    stmt = select(Job).order_by(Job.started_at.desc()).limit(50)
    if config_id is not None:
        stmt = stmt.where(Job.config_id == config_id)
    jobs = session.exec(stmt).all()
    return [j.model_dump() for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.model_dump()
