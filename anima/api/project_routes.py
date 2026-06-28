"""Project CRUD routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import anima.db as db
from anima.api.deps import current_user
from anima.config import settings
from anima.models import Project, User

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name:        str
    description: str = ""


class ProjectResponse(BaseModel):
    id:          str
    name:        str
    description: str
    workdir:     str
    created_at:  int
    updated_at:  int


def _make_workdir(user_id: str, project_id: str) -> str:
    path = Path(settings.workspaces_root) / user_id / project_id
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _to_response(p: Project) -> ProjectResponse:
    return ProjectResponse(
        id=p.id, name=p.name, description=p.description,
        workdir=p.workdir, created_at=p.created_at, updated_at=p.updated_at,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(body: CreateProjectRequest, user: User = Depends(current_user)):
    try:
        project = Project(user_id=user.id, name=body.name, description=body.description)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    project.workdir = _make_workdir(user.id, project.id)
    db.create_project(project)
    return _to_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(user: User = Depends(current_user)):
    return [_to_response(p) for p in db.get_projects(user.id)]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, user: User = Depends(current_user)):
    project = db.get_project(user.id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return _to_response(project)
