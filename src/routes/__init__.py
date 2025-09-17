from starlette.routing import Route, Mount
from .etl2 import etl2_create_spec
from .group_types import group_types


# All routes list, including standard web routes and MCP routes
routes = [
    # MCP related routes
    Route("/etl2", endpoint=etl2_create_spec, methods=["POST"]),
    Route("/group_types", endpoint=group_types, methods=["POST"]),
]