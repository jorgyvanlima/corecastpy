import os

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


def estatico(caminho: str) -> str:
    """URL de /static com a data de modificacao, para o navegador nao servir CSS/JS antigo do cache."""
    try:
        versao = int(os.path.getmtime(os.path.join("app/static", caminho)))
    except OSError:
        versao = 0
    return f"/static/{caminho}?v={versao}"


templates.env.globals["estatico"] = estatico
