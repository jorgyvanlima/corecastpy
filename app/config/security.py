from fastapi import Request, HTTPException, status
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return pwd_context.verify(senha, senha_hash)


def usuario_logado(request: Request) -> dict | None:
    return request.session.get("usuario")


def exigir_login(request: Request) -> dict:
    usuario = usuario_logado(request)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return usuario


def exigir_admin(request: Request) -> dict:
    usuario = exigir_login(request)
    if usuario.get("perfil") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a administradores")
    return usuario
