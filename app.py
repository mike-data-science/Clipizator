"""Azure Web App entrypoint.

Azure App Service (Oryx) automatically looks for a file named `app.py` 
or `application.py` in the root folder to boot a Python server.
By creating this file and importing our FastAPI app as `app`, Azure will 
automatically find it and start the server using Uvicorn!
"""

from backend.server import app
