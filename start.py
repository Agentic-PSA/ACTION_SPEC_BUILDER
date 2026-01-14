from dotenv import load_dotenv
load_dotenv()
import uvicorn
from starlette.applications import Starlette
from src.routes import routes
import os



app = Starlette(
        debug=True,
        routes=routes,
    )

def run():


    # # Create Starlette application
    # app = Starlette(
    #     debug=True,
    #     routes=routes,
    # )


    # Load environment variables from .env file
    """Start the Starlette server"""
    uvicorn.run(app, host="0.0.0.0", port=7001)


if __name__ == "__main__":
    run()