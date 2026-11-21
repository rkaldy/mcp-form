from workers import asgi

from form.app import app

Default = asgi.entrypoint(app)
