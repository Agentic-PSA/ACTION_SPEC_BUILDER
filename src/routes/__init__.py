from starlette.routing import Route, Mount
from .etl2 import etl2_create_spec
from .group_types import group_types
from .map_values import map_values
from .fill_graph import fill_graph


# All routes list, including standard web routes and MCP routes
routes = [
    # MCP related routes
    Route("/etl2", endpoint=etl2_create_spec, methods=["POST"]),
    Route("/group_types", endpoint=group_types, methods=["POST"]),
    Route("/map_values", endpoint=map_values, methods=["POST"]),
    Route("/fill_graph", endpoint=fill_graph, methods=["POST"]),
]