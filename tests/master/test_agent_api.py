# No shebang line, this module is meant to be imported
#
# Copyright 2013 Oliver Palmer
# Copyright 2013 Ambient Entertainment GmbH & Co. KG
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

from json import dumps

try:
    from httplib import CREATED, NO_CONTENT
except ImportError:
    from http.client import CREATED, NO_CONTENT

# test class must be loaded first
from pyfarm.master.testutil import BaseTestCase
BaseTestCase.build_environment()

from pyfarm.master.application import get_api_blueprint
from pyfarm.master.entrypoints.main import load_api
from pyfarm.models.agent import Agent


class TestAgentAPI(BaseTestCase):
    def setup_app(self):
        super(TestAgentAPI, self).setup_app()
        self.api = get_api_blueprint()
        self.app.register_blueprint(self.api)
        load_api(self.app, self.api)

    def test_agents_schema(self):
        response = self.client.get("/api/v1/agents/schema")
        self.assert_ok(response)
        self.assertEqual(response.json, Agent().to_schema())

    def test_agent_read_write(self):
        response1 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 16,
                "free_ram": 133,
                "hostname": "testagent1",
                "ip": "10.0.200.1",
                "port": 64994,
                "ram": 2048,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(response1)
        id = response1.json['id']

        response2 = self.client.get("/api/v1/agents/%d" % id)
        self.assert_ok(response2)
        self.assertEqual(
            response2.json, {
                "ram": 2048,
                "cpu_allocation": 1.0,
                "use_address": "remote",
                "ip": "10.0.200.1",
                "hostname": "testagent1",
                "cpus": 16,
                "ram_allocation": 0.8,
                "port": 64994,
                "time_offset": 0,
                "state": "running",
                "free_ram": 133,
                "id": id,
                "remote_ip": None})

    # There are two ways to update an agent, with a POST to /api/v1/agents
    # or with a POST to /api/v1/agents/<id>
    # Those are two different endpoints, and we have to test them both
    def test_agent_posts_by_id(self):
        response1 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 16,
                "free_ram": 133,
                "hostname": "testagent2",
                "ip": "10.0.200.2",
                "port": 64994,
                "ram": 2048,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(response1)
        id = response1.json['id']

        # When doing POST to /api/v1/agents with an already existing
        # hostname+port combination, the existing agent should be updated
        response2 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.1,
                "cpus": 32,
                "free_ram": 128,
                "hostname": "testagent2",
                "ip": "10.0.200.2",
                "port": 64994,
                "ram": 4096,
                "ram_allocation": 0.7,
                "state": "running"}))
        self.assert_ok(response2)

        # See if we get the updated data back
        response3 = self.client.get("/api/v1/agents/%d" % id)
        self.assert_ok(response3)
        self.assertEqual(response3.json, {
            "ram": 4096,
            "cpu_allocation": 1.1,
            "use_address": "remote",
            "ip": "10.0.200.2",
            "hostname": "testagent2",
            "cpus": 32,
            "ram_allocation": 0.7,
            "port": 64994,
            "time_offset": 0,
            "state": "running",
            "free_ram": 128,
            "id": id,
            "remote_ip": None})

    def test_post_agents(self):
        response1 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 16,
                "free_ram": 133,
                "hostname": "testagent3",
                "ip": "10.0.200.3",
                "port": 64994,
                "ram": 2048,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(response1)
        id = response1.json['id']

        # Using this endpoint, we should be able to change everything about an
        # agent except its id
        response2 = self.client.post(
            "/api/v1/agents/%d" % id,
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.2,
                "ram": 8192,
                "use_address": "hostname",
                "ip": "10.0.200.4",
                "hostname": "testagent3-1",
                "cpus": 64,
                "ram_allocation": 0.2,
                "port": 64995,
                "time_offset": 5,
                "state": "running",
                "free_ram": 4096,
                "id": id}))
        self.assert_ok(response2)

        # See if we get the updated data back
        response3 = self.client.get("/api/v1/agents/%d" % id)
        self.assert_ok(response3)
        self.assertEqual(response3.json, {
            "ram": 8192,
            "cpu_allocation": 1.2,
            "use_address": "hostname",
            "ip": "10.0.200.4",
            "hostname": "testagent3-1",
            "cpus": 64,
            "ram_allocation": 0.2,
            "port": 64995,
            "time_offset": 5,
            "state": "running",
            "free_ram": 4096,
            "id": id,
            "remote_ip": None})

    def test_agent_delete(self):
        response1 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 16,
                "free_ram": 133,
                "hostname": "testagent4",
                "ip": "10.0.200.5",
                "port": 64994,
                "ram": 2048,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(response1)
        id = response1.json['id']

        response2 = self.client.delete("/api/v1/agents/%d" % id)
        self.assert_ok(response2)
        response3 = self.client.delete("/api/v1/agents/%d" % id)
        self.assert_no_content(response3)
        response4 = self.client.get("/api/v1/agents/%d" % id)
        self.assert_not_found(response4)

    def test_agent_filter(self):
        create_response1 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 8,
                "free_ram": 133,
                "hostname": "lowcpu-lowram",
                "ip": "10.0.200.6",
                "port": 64994,
                "ram": 1024,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(create_response1)
        low_cpu_low_ram_id = create_response1.json['id']

        create_response2 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 8,
                "free_ram": 133,
                "hostname": "lowcpu-highram",
                "ip": "10.0.200.7",
                "port": 64994,
                "ram": 4096,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(create_response2)
        low_cpu_high_ram_id = create_response2.json['id']

        create_response3 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 16,
                "free_ram": 133,
                "hostname": "highcpu-lowram",
                "ip": "10.0.200.8",
                "port": 64994,
                "ram": 1024,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(create_response3)
        high_cpu_low_ram_id = create_response3.json['id']

        create_response4 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 16,
                "free_ram": 133,
                "hostname": "highcpu-highram",
                "ip": "10.0.200.9",
                "port": 64994,
                "ram": 4096,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(create_response4)
        high_cpu_high_ram_id = create_response4.json['id']

        create_response5 = self.client.post(
            "/api/v1/agents",
            content_type="application/json",
            data=dumps({
                "cpu_allocation": 1.0,
                "cpus": 12,
                "free_ram": 133,
                "hostname":
                    "middlecpu-middleram",
                "ip": "10.0.200.10",
                "port": 64994,
                "ram": 2048,
                "ram_allocation": 0.8,
                "state": "running"}))
        self.assert_created(create_response5)
        middle_cpu_middle_ram_id = create_response5.json['id']

        get_response1 = self.client.get("/api/v1/agents?min_cpus=9")
        self.assert_ok(get_response1)
        self.assertNotIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response1.json)
        self.assertNotIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response1.json)
        self.assertIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response1.json)
        self.assertIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response1.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response1.json)

        get_response2 = self.client.get("/api/v1/agents?min_cpus=8")
        self.assert_ok(get_response2)
        self.assertIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response2.json)
        self.assertIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response2.json)
        self.assertIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response2.json)
        self.assertIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response2.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response2.json)

        get_response3 = self.client.get("/api/v1/agents?max_cpus=12")
        self.assert_ok(get_response3)
        self.assertIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response3.json)
        self.assertIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response3.json)
        self.assertNotIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response3.json)
        self.assertNotIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response3.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response3.json)

        get_response4 = self.client.get(
            "/api/v1/agents?min_cpus=10&max_cpus=14")
        self.assert_ok(get_response4)
        self.assertNotIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response4.json)
        self.assertNotIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response4.json)
        self.assertNotIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response4.json)
        self.assertNotIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response4.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response3.json)

        get_response5 = self.client.get("/api/v1/agents?min_ram=1024")
        self.assert_ok(get_response5)
        self.assertIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response5.json)
        self.assertIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response5.json)
        self.assertIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response5.json)
        self.assertIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response5.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response5.json)

        get_response6 = self.client.get("/api/v1/agents?min_ram=2048")
        self.assert_ok(get_response6)
        self.assertNotIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response6.json)
        self.assertIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response6.json)
        self.assertNotIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response6.json)
        self.assertIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response6.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response6.json)

        get_response7 = self.client.get("/api/v1/agents?max_ram=2048")
        self.assert_ok(get_response7)
        self.assertIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response7.json)
        self.assertNotIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response7.json)
        self.assertIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response7.json)
        self.assertNotIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response7.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response7.json)

        get_response8 = self.client.get(
            "/api/v1/agents?min_ram=1025&max_ram=2049")
        self.assert_ok(get_response8)
        self.assertNotIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response8.json)
        self.assertNotIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response8.json)
        self.assertNotIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response8.json)
        self.assertNotIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response8.json)
        self.assertIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response8.json)

        get_response9 = self.client.get(
            "/api/v1/agents?min_ram=2048&min_cpus=16")
        self.assert_ok(get_response9)
        self.assertNotIn(
            {"hostname": "lowcpu-lowram", "id": low_cpu_low_ram_id},
            get_response9.json)
        self.assertNotIn(
            {"hostname": "lowcpu-highram", "id": low_cpu_high_ram_id},
            get_response9.json)
        self.assertNotIn(
            {"hostname": "highcpu-lowram", "id": high_cpu_low_ram_id},
            get_response9.json)
        self.assertIn(
            {"hostname": "highcpu-highram", "id": high_cpu_high_ram_id},
            get_response9.json)
        self.assertNotIn(
            {"hostname": "middlecpu-middleram", "id": middle_cpu_middle_ram_id},
            get_response9.json)