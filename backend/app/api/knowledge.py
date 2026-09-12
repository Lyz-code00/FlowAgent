from dataclasses import asdict

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.core.security import require_admin
from app.rag.parser import DocumentParseError

router = APIRouter(
    prefix="/api/v1/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_admin)],
)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    tenant_key: str = Query(default="default", min_length=1, max_length=128),
    title: str | None = Query(default=None, max_length=512),
) -> dict:
    service = request.app.state.knowledge_service
    data = await file.read(service.max_file_bytes + 1)
    try:
        document = await service.ingest(
            tenant_key=tenant_key,
            filename=file.filename or "document.txt",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            title=title,
        )
    except DocumentParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"indexing failed: {exc}") from exc
    return asdict(document)


@router.get("/documents")
async def list_documents(
    request: Request,
    tenant_key: str = Query(default="default", min_length=1, max_length=128),
) -> list[dict]:
    documents = await request.app.state.knowledge_service.list_documents(
        tenant_key=tenant_key
    )
    return [asdict(item) for item in documents]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    request: Request,
    tenant_key: str = Query(default="default", min_length=1, max_length=128),
) -> None:
    deleted = await request.app.state.knowledge_service.delete_document(
        tenant_key=tenant_key, document_id=document_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
