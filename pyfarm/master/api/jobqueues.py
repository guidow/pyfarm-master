# No shebang line, this module is meant to be imported
#
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

"""
Job Queues
----------

This module defines an API for managing and querying job queues
"""
try:
    from httplib import OK, CREATED, CONFLICT
except ImportError:  # pragma: no cover
    from http.client import OK, CREATED, CONFLICT

from flask import g
from flask.views import MethodView

from pyfarm.core.logger import getLogger
from pyfarm.models.jobqueue import JobQueue
from pyfarm.master.application import db
from pyfarm.master.utility import jsonify, validate_with_model


logger = getLogger("api.jobqueues")


def schema():
    """
    Returns the basic schema of :class:`.JobQueue`

    .. http:get:: /api/v1/jobqueues/schema HTTP/1.1

        **Request**

        .. sourcecode:: http

            GET /api/v1/jobqueues/schema HTTP/1.1
            Accept: application/json

        **Response**

        .. sourcecode:: http

            HTTP/1.1 200 OK
            Content-Type: application/json

            {
                "id": "INTEGER",
                "name": VARCHAR(255)",
                "minimum_agents": "INTEGER",
                "maximum_agents": "INTEGER",
                "priority": "INTEGER",
                "weight": "INTEGER",
                "parent_jobqueue_id": "INTEGER"
            }

    :statuscode 200: no error
    """
    return jsonify(JobQueue.to_schema()), OK


class JobQueueIndexAPI(MethodView):
    @validate_with_model(JobQueue)
    def post(self):
        """
        A ``POST`` to this endpoint will create a new job queue.

        .. http:post:: /api/v1/jobqueues/ HTTP/1.1

            **Request**

            .. sourcecode:: http

                POST /api/v1/jobqueues/ HTTP/1.1
                Accept: application/json

                {
                    "name": "Test Queue"
                }


            **Response**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                {
                    "weight": 10,
                    "jobs": [],
                    "minimum_agents": null,
                    "priority": 5,
                    "name": "Test Queue",
                    "maximum_agents": null,
                    "id": 1,
                    "parent": [],
                    "parent_jobqueue_id": null
                }

        :statuscode 201: a new job queue was created
        :statuscode 400: there was something wrong with the request (such as
                            invalid columns being included)
        :statuscode 409: a job queue with that name already exists
        """
        jobqueue = JobQueue.query.filter_by(name=g.json["name"]).first()
        if jobqueue:
            return (jsonify(error="Job queue %s already exixts" %
                            g.json["name"]), CONFLICT)

        jobqueue = JobQueue(**g.json)
        db.session.add(jobqueue)
        db.session.commit()

        jobqueue_data = jobqueue.to_dict()
        logger.info("created job queue %s: %r", jobqueue.id, jobqueue_data)

        return jsonify(jobqueue_data), CREATED

    def get(self):
        """
        A ``GET`` to this endpoint will return a list of known job queues.

        .. http:get:: /api/v1/jobqueues/ HTTP/1.1

            **Request**

            .. sourcecode:: http

                GET /api/v1/jobqueues/ HTTP/1.1
                Accept: application/json

            **Response**

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json

                [
                    {
                        "priority": 5,
                        "weight": 10,
                        "parent_jobqueue_id": null,
                        "name": "Test Queue",
                        "minimum_agents": null,
                        "id": 1,
                        "maximum_agents": null
                    },
                    {
                        "priority": 5,
                        "weight": 10,
                        "parent_jobqueue_id": null,
                        "name": "Test Queue 2",
                        "minimum_agents": null,
                        "id": 2,
                        "maximum_agents": null
                    }
                ]

        :statuscode 200: no error
        """
        out = []
        for jobqueue in JobQueue.query:
            out.append(jobqueue.to_dict(unpack_relationships=False))

        return jsonify(out), OK