from starlette.routing import Route, Mount
from .etl2 import etl2_create_spec, etl2_create_spec_aka


# All routes list, including standard web routes and MCP routes
routes = [
    # MCP related routes
    Route("/etl2", endpoint=etl2_create_spec, methods=["POST"]),
    Route("/etlaka", endpoint=etl2_create_spec_aka, methods=["GET"]),
]