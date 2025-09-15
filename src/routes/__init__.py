from starlette.routing import Route, Mount
from .etl2 import etl2_create_spec


# All routes list, including standard web routes and MCP routes
routes = [
    # MCP related routes
    Route("/etl2", endpoint=etl2_create_spec, methods=["POST"]),
]