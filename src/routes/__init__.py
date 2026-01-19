from starlette.routing import Route, Mount
from .etl2 import etl2_create_spec_aka, etl2_create_spec_aka_single
from .group_types import group_types
from .map_values import map_values
from .fill_graph import fill_graph, fill_graph_single
from .pim import pim
from .build_names import build_names
from .create_description import create_description


# All routes list, including standard web routes and MCP routes
routes = [
    # MCP related routes
    Route("/etlaka", endpoint=etl2_create_spec_aka, methods=["POST"]),
    Route("/etlaka_single", endpoint=etl2_create_spec_aka_single, methods=["POST"]),
    Route("/group_types", endpoint=group_types, methods=["POST"]),
    Route("/map_values", endpoint=map_values, methods=["POST"]),
    Route("/fill_graph", endpoint=fill_graph, methods=["POST"]),
    Route("/fill_graph_single", endpoint=fill_graph_single, methods=["POST"]),
    Route("/pim", endpoint=pim, methods=["POST"]),
    Route("/build_names", endpoint=build_names, methods=["POST"]),
    # RabbitMQ / description route
    Route("/create_description", endpoint=create_description, methods=["POST"])
]