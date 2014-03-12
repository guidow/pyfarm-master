# No shebang line, this module is meant to be imported
#
# Copyright 2013 Oliver Palmer
# Copyright 2014 Ambient Entertainment GmbH & Co. KG
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


# test class must be loaded first
from pyfarm.master.testutil import BaseTestCase
BaseTestCase.build_environment()

from pyfarm.models.core.cfg import MAX_JOBTYPE_LENGTH
from pyfarm.master.application import get_api_blueprint
from pyfarm.master.entrypoints.main import load_api
from pyfarm.models.job import Job

jobtype_code = """from pyfarm.jobtypes.core.jobtype import JobType

class TestJobType(JobType):
    def get_command(self):
        return "/usr/bin/touch"
    def get_arguments(self):
        return [os.path.join(
            self.assignment_data["job"]["data"]["path"],
            "%04d" % self.assignment_data[\"tasks\"][0][\"frame\"])]
"""


class TestJobAPI(BaseTestCase):
    def setup_app(self):
        super(TestJobAPI, self).setup_app()
        self.api = get_api_blueprint()
        self.app.register_blueprint(self.api)
        load_api(self.app, self.api)

    def test_job_schema(self):
        response = self.client.get("/api/v1/jobs/schema")
        self.assert_ok(response)
        schema = Job.to_schema()
        schema["start"] = "NUMERIC(10,4)"
        schema["end"] = "NUMERIC(10,4)"
        del schema["jobtype_version_id"]
        schema["jobtype"] = "VARCHAR(%s)" % MAX_JOBTYPE_LENGTH
        schema["jobtype_version"] = "INTEGER"
        self.assertEqual(response.json, schema)

    def test_job_post(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/software/",
            content_type="application/json",
            data=dumps({
                        "software": "foo",
                        "versions": [
                                    {"version": "1.0"},
                                    {"version": "1.1"}
                            ]
                       }))
        self.assert_created(response2)
        software_id = response2.json['id']
        software_min_version_id = response2.json["versions"][0]["id"]
        software_max_version_id = response2.json["versions"][1]["id"]

        response3 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [
                            {
                                "software": "foo",
                                "min_version": "1.0",
                                "max_version": "1.1"}
                        ]
                    }))
        self.assert_created(response3)
        self.assertIn("time_submitted", response3.json)
        time_submitted = response3.json["time_submitted"]
        id = response3.json["id"]
        self.assertEqual(response3.json,
                        {
                            "id": id,
                            "time_finished": None,
                            "time_started": None,
                            "end": 2.0,
                            "time_submitted": time_submitted,
                            "jobtype_version": 1,
                            "jobtype": "TestJobType",
                            "start": 1.0,
                            "priority": 0,
                            "state": "queued",
                            "parents": [],
                            "hidden": False,
                            "project_id": None,
                            "ram_warning": None,
                            "title": "Test Job",
                            "tags": [],
                            "user": None,
                            "by": 1.0,
                            "data": {"foo": "bar"},
                            "ram_max": None,
                            "notes": "",
                            "batch": 1,
                            "environ": None,
                            "requeue": 3,
                            "software_requirements": [
                                {
                                    "min_version": "1.0",
                                    "max_version": "1.1",
                                    "max_version_id": software_max_version_id,
                                    "software_id": 1,
                                    "min_version_id": software_min_version_id,
                                    "software": "foo"
                                }
                            ],
                            "ram": 32,
                            "cpus": 1,
                            "children": []
                         })

    def test_job_post_bad_requirements(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/software/",
            content_type="application/json",
            data=dumps({
                        "software": "foo",
                        "versions": [
                                    {"version": "1.0"},
                                    {"version": "1.1"}
                            ]
                       }))
        self.assert_created(response2)

        response3 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": {
                                "software": "foo",
                                "min_version": "1.0",
                                "max_version": "1.1"}
                    }))
        self.assert_bad_request(response3)

        response4 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [1]
                    }))
        self.assert_bad_request(response4)

        response5 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [
                        {
                            "software": "foo",
                            "min_version": "1.0",
                            "max_version": "1.1",
                            "unknown_key": 1
                        }]
                    }))
        self.assert_bad_request(response5)

        response6 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [{}]
                    }))
        self.assert_bad_request(response6)

    def test_job_post_unknown_software_version(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/software/",
            content_type="application/json",
            data=dumps({
                        "software": "foo",
                        "versions": [
                                    {"version": "1.0"},
                                    {"version": "1.1"}
                            ]
                       }))
        self.assert_created(response2)

        response3 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [
                        {
                            "software": "unknown_software",
                            "min_version": "1.0",
                            "max_version": "1.1",
                        }]
                    }))
        self.assert_not_found(response3)

        response3 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [
                        {
                            "software": "foo",
                            "min_version": "unknown_version",
                            "max_version": "1.1",
                        }]
                    }))
        self.assert_not_found(response3)

        response4 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": [
                        {
                            "software": "foo",
                            "min_version": "1.0",
                            "max_version": "unknown_version",
                        }]
                    }))
        self.assert_not_found(response4)

    def test_job_post_no_type(self):
        response1 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "data": {"foo": "bar"}
                    }))
        self.assert_bad_request(response1)

    def test_job_post_bad_type(self):
        response1 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "jobtype": 1,
                    "title": "Test Job",
                    "data": {"foo": "bar"}
                    }))
        self.assert_bad_request(response1)

    def test_job_post_with_jobtype_version(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.put(
            "/api/v1/jobtypes/TestJobType",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing (updated)",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response2)

        response3 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "jobtype_version": 1,
                    "data": {"foo": "bar"},
                    }))
        self.assert_created(response3)
        time_submitted = response3.json["time_submitted"]
        id = response3.json["id"]
        self.assertEqual(response3.json,
                        {
                            "id": id,
                            "time_finished": None,
                            "time_started": None,
                            "end": 2.0,
                            "time_submitted": time_submitted,
                            "jobtype_version": 1,
                            "jobtype": "TestJobType",
                            "start": 1.0,
                            "priority": 0,
                            "state": "queued",
                            "parents": [],
                            "hidden": False,
                            "project_id": None,
                            "ram_warning": None,
                            "title": "Test Job",
                            "tags": [],
                            "user": None,
                            "by": 1.0,
                            "data": {"foo": "bar"},
                            "ram_max": None,
                            "notes": "",
                            "batch": 1,
                            "environ": None,
                            "requeue": 3,
                            "software_requirements": [],
                            "ram": 32,
                            "cpus": 1,
                            "children": []
                         })

    def test_job_post_unknown_type(self):
        response1 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "unknown jobtype",
                    "data": {"foo": "bar"}
                    }))
        self.assert_not_found(response1)

    def test_jobs_list(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]

        response3 = self.client.get("/api/v1/jobs/")
        self.assert_ok(response3)
        self.assertEqual(response3.json,
                         [
                            {
                                "title": "Test Job",
                                "state": "queued",
                                "id": id
                            },
                         ])

    def test_job_get(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.get("/api/v1/jobs/Test%20Job")
        self.assert_ok(response3)
        self.assertEqual(response3.json,
                         {
                            "ram_warning": None,
                            "title": "Test Job",
                            "state": "queued",
                            "jobtype_version": 1,
                            "jobtype": "TestJobType",
                            "environ": None,
                            "user": None,
                            "priority": 0,
                            "time_finished": None,
                            "start": 1.0,
                            "id": id,
                            "notes": "",
                            "ram": 32,
                            "tags": [],
                            "hidden": False,
                            "data": {"foo": "bar"},
                            "software_requirements": [],
                            "batch": 1,
                            "time_started": None,
                            "time_submitted": time_submitted,
                            "requeue": 3,
                            "end": 2.0,
                            "parents": [],
                            "cpus": 1,
                            "ram_max": None,
                            "children": [],
                            "by": 1.0,
                            "project_id": None
                        })

        response4 = self.client.get("/api/v1/jobs/%s" % id)
        self.assert_ok(response4)
        self.assertEqual(response4.json,
                         {
                            "ram_warning": None,
                            "title": "Test Job",
                            "state": "queued",
                            "jobtype_version": 1,
                            "jobtype": "TestJobType",
                            "environ": None,
                            "user": None,
                            "priority": 0,
                            "time_finished": None,
                            "start": 1.0,
                            "id": id,
                            "notes": "",
                            "ram": 32,
                            "tags": [],
                            "hidden": False,
                            "data": {"foo": "bar"},
                            "software_requirements": [],
                            "batch": 1,
                            "time_started": None,
                            "time_submitted": time_submitted,
                            "requeue": 3,
                            "end": 2.0,
                            "parents": [],
                            "cpus": 1,
                            "ram_max": None,
                            "children": [],
                            "by": 1.0,
                            "project_id": None
                        })

    def test_job_get_unknown(self):
        response1 = self.client.get("/api/v1/jobs/Unknown%20Job")
        self.assert_not_found(response1)

    def test_job_update(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "start": 2.0,
                    "end": 3.0,
                    "ram": 64
                    }))
        self.assert_ok(response3)
        self.assertEqual(response3.json,
                         {
                            "ram_warning": None,
                            "title": "Test Job",
                            "state": "queued",
                            "jobtype_version": 1,
                            "jobtype": "TestJobType",
                            "environ": None,
                            "user": None,
                            "priority": 0,
                            "time_finished": None,
                            "start": 2.0,
                            "id": id,
                            "notes": "",
                            "ram": 64,
                            "tags": [],
                            "hidden": False,
                            "data": {"foo": "bar"},
                            "software_requirements": [],
                            "batch": 1,
                            "time_started": None,
                            "time_submitted": time_submitted,
                            "requeue": 3,
                            "end": 3.0,
                            "parents": [],
                            "cpus": 1,
                            "ram_max": None,
                            "children": [],
                            "by": 1.0,
                            "project_id": None
                        })

        response4 = self.client.post(
            "/api/v1/jobs/%s" % id,
            content_type="application/json",
            data=dumps({
                    "start": 2.0,
                    "end": 4.0,
                    }))
        self.assert_ok(response4)

    def test_job_update_unknown(self):
        response1 = self.client.post(
            "/api/v1/jobs/Unknown%20Job",
            content_type="application/json",
            data=dumps({
                    "start": 2.0
                    }))
        self.assert_not_found(response1)

    def test_job_update_bad_start_end(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "start": 3.0,
                    "end": 2.0,
                    }))
        self.assert_bad_request(response3)

    def test_job_update_bad_disallowed_columns(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "time_started": "2014-03-06T15:40:58.335259"
                    }))
        self.assert_bad_request(response3)

        response4 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "time_finished": "2014-03-06T15:40:58.335259"
                    }))
        self.assert_bad_request(response4)

        response5 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "time_submitted": "2014-03-06T15:40:58.335259"
                    }))
        self.assert_bad_request(response5)

        response6 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "jobtype_version_id": 1
                    }))
        self.assert_bad_request(response6)

    def test_job_update_unknown_columns(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "unknown_column": 1
                    }))
        self.assert_bad_request(response3)

    def test_job_update_bad_requiremens(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.post(
            "/api/v1/jobs/Test%20Job",
            content_type="application/json",
            data=dumps({
                    "software_requirements": 1
                    }))
        self.assert_bad_request(response3)

    def test_job_get_tasks(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.get("/api/v1/jobs/Test%20Job/tasks/")
        self.assert_ok(response3)
        self.assertEqual(len(response3.json), 2)
        task1_id = response3.json[0]["id"]
        task1_submitted = response3.json[0]["time_submitted"]
        task2_id = response3.json[1]["id"]
        task2_submitted = response3.json[1]["time_submitted"]

        self.assertEqual(response3.json,
                         [
                             {
                                "hidden": False,
                                "id": task1_id,
                                "attempts": 0,
                                "priority": 0,
                                "time_started": None,
                                "time_submitted": task1_submitted,
                                "frame": 1.0,
                                "time_finished": None,
                                "job_id": id,
                                "project_id": None,
                                "state": "queued",
                                "agent_id": None
                             },
                             {
                                "hidden": False,
                                "id": task2_id,
                                "attempts": 0,
                                "priority": 0,
                                "time_started": None,
                                "time_submitted": task2_submitted,
                                "frame": 2.0,
                                "time_finished": None,
                                "job_id": id,
                                "project_id": None,
                                "state": "queued",
                                "agent_id": None
                             }
                         ])

    def test_job_get_tasks_by_id(self):
        response1 = self.client.post(
            "/api/v1/jobtypes/",
            content_type="application/json",
            data=dumps({
                    "name": "TestJobType",
                    "description": "Jobtype for testing inserts and queries",
                    "max_batch": 1,
                    "code": jobtype_code
                    }))
        self.assert_created(response1)
        jobtype_id = response1.json['id']

        response2 = self.client.post(
            "/api/v1/jobs/",
            content_type="application/json",
            data=dumps({
                    "start": 1.0,
                    "end": 2.0,
                    "title": "Test Job",
                    "jobtype": "TestJobType",
                    "data": {"foo": "bar"},
                    "software_requirements": []
                    }))
        self.assert_created(response2)
        id = response2.json["id"]
        time_submitted = response2.json["time_submitted"]

        response3 = self.client.get("/api/v1/jobs/%s/tasks/" % id)
        self.assert_ok(response3)
        self.assertEqual(len(response3.json), 2)
        task1_id = response3.json[0]["id"]
        task1_submitted = response3.json[0]["time_submitted"]
        task2_id = response3.json[1]["id"]
        task2_submitted = response3.json[1]["time_submitted"]

        self.assertEqual(response3.json,
                         [
                             {
                                "hidden": False,
                                "id": task1_id,
                                "attempts": 0,
                                "priority": 0,
                                "time_started": None,
                                "time_submitted": task1_submitted,
                                "frame": 1.0,
                                "time_finished": None,
                                "job_id": id,
                                "project_id": None,
                                "state": "queued",
                                "agent_id": None
                             },
                             {
                                "hidden": False,
                                "id": task2_id,
                                "attempts": 0,
                                "priority": 0,
                                "time_started": None,
                                "time_submitted": task2_submitted,
                                "frame": 2.0,
                                "time_finished": None,
                                "job_id": id,
                                "project_id": None,
                                "state": "queued",
                                "agent_id": None
                             }
                         ])

    def test_job_get_tasks_unknown_job(self):
        response1 = self.client.get("/api/v1/jobs/Unknown%20Job/tasks/")
        self.assert_not_found(response1)