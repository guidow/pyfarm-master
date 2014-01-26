# No shebang line, this module is meant to be imported
#
# Copyright 2013 Oliver Palmer
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from flask import abort

# test class must be loaded first
from pyfarm.master.testutil import BaseTestCase
BaseTestCase.build_environment()

from pyfarm.master.entrypoints.main import load_error_handlers
from pyfarm.master.application import get_admin


class TestErrors(BaseTestCase):
    def setup_app(self):
        super(TestErrors, self).setup_app()
        get_admin(app=self.app)  # adds admin.static
        load_error_handlers(self.app)

    def test_400(self):
        self.app.add_url_rule("/test_error_400", view_func=lambda: abort(400))
        response = self.client.get(
            "/test_error_400",
            method="GET",
            headers=[("Content-Type", "application/json")])
        self.assert_bad_request(response)
        response = self.client.get("/test_error_400")
        self.assert_bad_request(response)
        self.assertIn("<title>PyFarm - Bad Request</title>",
                      response.data.decode("utf-8"))

    def test_401(self):
        self.app.add_url_rule("/test_error_401", view_func=lambda: abort(401))
        response = self.client.get(
            "/test_error_401",
            method="GET",
            headers=[("Content-Type", "application/json")])
        self.assert_unauthorized(response)
        response = self.client.get("/test_error_401")
        self.assert_unauthorized(response)
        self.assertIn("<title>PyFarm - Access Denied</title>",
                      response.data.decode("utf-8"))

    def test_404(self):
        self.app.add_url_rule("/test_error_404", view_func=lambda: abort(404))
        response = self.client.get(
            "/test_error_404",
            method="GET",
            headers=[("Content-Type", "application/json")])
        self.assert_not_found(response)
        response = self.client.get("/test_error_404")
        self.assert_not_found(response)
        self.assertIn("<title>PyFarm - Not Found</title>",
                      response.data.decode("utf-8"))

    def test_500(self):
        self.app.add_url_rule("/test_error_500", view_func=lambda: abort(500))
        response = self.client.get(
            "/test_error_500",
            method="GET",
            headers=[("Content-Type", "application/json")])
        self.assert_internal_server_error(response)
        response = self.client.get("/test_error_500")
        self.assert_internal_server_error(response)
        self.assertIn("<title>PyFarm - Internal Server Error</title>",
                      response.data.decode("utf-8"))
