"""Comunidades iniciales de Colibrí; se pueden añadir UUID públicos desde la interfaz."""
FING = "8de5ffef-1c73-4c9b-a83f-b75c953201ba"
INCO = "36bd9ee5-261b-4db6-8dd6-e96cafcb1fd4"
COMMUNITIES = {FING: "Facultad de Ingeniería (incluye InCo)", INCO: "Instituto de Computación"}


def effective_scopes(scopes):
    # DSpace busca recursivamente: consultar Fing y su descendiente InCo duplica tráfico.
    return [scope for scope in scopes if not (scope == INCO and FING in scopes)]
