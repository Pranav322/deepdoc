import falcon

from controllers.auth import LoginResource, LogoutResource


app = falcon.App(middleware=[AuthMiddleware(), TraceMiddleware()])
app.add_route("/api/v2/login", LoginResource())
app.add_route("/api/v2/logout", LogoutResource())
