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

"""
Tag
===

Contained within this module are an API handling functions which can
manage or query tags using JSON.
"""

try:
    from httplib import NOT_FOUND, NO_CONTENT, OK, CREATED, BAD_REQUEST
except ImportError: # pragma: no cover
    from http.client import NOT_FOUND, NO_CONTENT, OK, CREATED, BAD_REQUEST

from flask import Response, request, url_for
from flask.views import MethodView

from pyfarm.core.logger import getLogger
from pyfarm.core.enums import STRING_TYPES, APIError
from pyfarm.models.agent import Agent, AgentTagAssociation
from pyfarm.models.job import Job, JobTagAssociation
from pyfarm.models.tag import Tag
from pyfarm.master.application import db
from pyfarm.master.utility import json_from_request, jsonify, get_column_sets

ALL_TAG_COLUMNS, REQUIRED_TAG_COLUMNS = get_column_sets(Tag)

logger = getLogger("api.tags")


def schema():
    """
    Returns the basic schema of :class:`.Tag`

    .. http:get:: /api/v1/tags/schema HTTP/1.1

        **Request**

        .. sourcecode:: http

            GET /api/v1/tags/schema HTTP/1.1
            Accept: application/json

        **Response**

        .. sourcecode:: http

            HTTP/1.1 200 OK
            Content-Type: application/json

            {
                "id": "INTEGER",
                "tag": "VARCHAR(64)"
            }

    :statuscode 200: no error
    """
    return jsonify(Tag.to_schema())


class TagIndexAPI(MethodView):
    def post(self):
        """
        A ``POST`` to this endpoint will do one of two things:

            * create a new tag and return the row
            * return the row for an existing tag

        Tags only have one column, the tag name. Two tags are automatically
        considered equal if the tag names are equal.

        .. http:post:: /api/v1/tags HTTP/1.1

            **Request**

            .. sourcecode:: http

                POST /api/v1/tags HTTP/1.1
                Accept: application/json

                {
                    "tag": "interesting"
                }

            **Response (new tag create)**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                {
                    "id": 1,
                    "tag": "interesting"
                }

            **Request**

            .. sourcecode:: http

                POST /api/v1/tags HTTP/1.1
                Accept: application/json

                {
                    "tag": "interesting"
                }

            **Response (existing tag returned)**

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json

                {
                    "id": 1,
                    "tag": "interesting"
                }

        :statuscode 200: an existing tag was found and returned
        :statuscode 201: a new tag was created
        :statuscode 400: there was something wrong with the request (such as
                            invalid columns being included)
        """
        data = json_from_request(request,
                                 all_keys=ALL_TAG_COLUMNS,
                                 required_keys=REQUIRED_TAG_COLUMNS,
                                 disallowed_keys=set(["id"]))
        # json_from_request returns a Response, Returncode tuple on error
        if isinstance(data, tuple):
            return data

        existing_tag = Tag.query.filter_by(tag=data["tag"]).first()

        if existing_tag:
            # No update needed, because Tag only has that one column
            return jsonify(existing_tag.to_dict()), OK

        else:
            new_tag = Tag(**data)
            db.session.add(new_tag)
            db.session.commit()
            tag_data = new_tag.to_dict()
            logger.info("created tag %s: %s" %
                        (new_tag.id,
                         tag_data))
            return jsonify(tag_data), CREATED

    def get(self):
        """
        A ``GET`` to this endpoint will return a list of known tags, with id.
        Associated agents and jobs can be included for every tag, however that
        feature may become a performance problem if used too much.
        Only use it if you need that information anyway and the alternative would
        be separate API calls for every tag returned here.

        .. http:get:: /api/v1/tags HTTP/1.1

            **Request**

            .. sourcecode:: http

                GET /api/v1/tags HTTP/1.1
                Accept: application/json

            **Response**

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json

                [
                    {
                        "id": 1,
                        "tag": "interesting"
                    },
                    {
                        "id": 2,
                        "tag": "boring"
                    }
                ]

            **Request**

            .. sourcecode:: http

                GET /api/v1/tags HTTP/1.1
                Accept: application/json

            **Response**

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json

                [
                    {
                        "agents": [
                            1
                        ],
                        "jobs": [],
                        "id": 1,
                        "tag": "interesting"
                    },
                    {
                        "agents": [],
                        "jobs": [],
                        "id": 2,
                        "tag": "boring"
                    }
                ]

        :statuscode 200: no error
        """
        out = []

        for tag in Tag.query.all():
            out.append(tag.to_dict())

        return jsonify(out), OK


class SingleTagAPI(MethodView):
    def get(self, tagname=None):
        """
        A ``GET`` to this endpoint will return the referenced tag, either by
        name or id, including a list of agents and jobs associated with it.

        .. http:get:: /api/v1/tags/interesting HTTP/1.1

            **Request**

            .. sourcecode:: http

                GET /api/v1/tags/interesting HTTP/1.1
                Accept: application/json

            **Response**

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json

                {
                "agents": [
                    {
                    "hostname": "agent3", 
                    "href": "/api/v1/agents/1", 
                    "id": 1
                    }
                ], 
                "id": 1, 
                "jobs": [], 
                "tag": "interesting"
                }

        :statuscode 200: no error
        :statuscode 404: tag not found
        """
        if isinstance(tagname, STRING_TYPES):
            tag = Tag.query.filter_by(tag=tagname).first()
        else:
            tag = Tag.query.filter_by(id=tagname).first()
        if tag is None:
            return jsonify(message="Tag not found"), NOT_FOUND

        tag_dict = tag.to_dict()

        return jsonify(tag_dict), OK

    def put(self, tagname=None):
        """
        A ``PUT`` to this endpoint will create a new tag under the given URI.
        If a tag already exists under that URI, it will be deleted, then
        recreated.
        You can optionally specify a list of agents or jobs relations as
        integers in the request data.

        .. http:put:: /api/v1/tags HTTP/1.1

            **Request**

            .. sourcecode:: http

                PUT /api/v1/tags/interesting HTTP/1.1
                Accept: application/json

                {
                    "tag": "interesting"
                }

            **Response**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                {
                    "id": 1,
                    "tag": "interesting"
                }

            **Request**

            .. sourcecode:: http

                PUT /api/v1/tags/interesting HTTP/1.1
                Accept: application/json

                {
                    "tag": "interesting",
                    "agents": [1]
                    "jobs": []
                }

            **Response**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                {
                    "id": 1,
                    "tag": "interesting"
                }

        :statuscode 201: a new tag was created
        :statuscode 400: there was something wrong with the request (such as
                            invalid columns being included)
        :statuscode 404: a referenced agent or job does not exist
        """
        if isinstance(tagname, STRING_TYPES):
            tag = Tag.query.filter_by(tag=tagname).first()
        else:
            tag = Tag.query.filter_by(id=tagname).first()
        if tag is not None:
            # If tag exists, delete it before recreating it
            db.session.delete(tag)
            logger.debug("Deleted tag %s as part of PUT operation" % tag.tag)
            db.session.flush()

        data = json_from_request(request)
        if isinstance(data, tuple):
            return data

        if (isinstance(tagname, STRING_TYPES) and
            data["tag"] != tagname):
                return jsonify(error="Name of tag must equal the name under "
                                     "which it is put"), BAD_REQUEST

        agents = []
        if "agents" in data:
            agent_ids = data["agents"]
            del data["agents"]
            if not isinstance(agent_ids, list):
                return jsonify(error="agents must be a list"), BAD_REQUEST
            for agent_id in agent_ids:
                if not isinstance(agent_id, int):
                    return jsonify(error="agent must be an int"), BAD_REQUEST
                agent = Agent.query.filter_by(id=agent_id).first()
                if agent is None:
                    return jsonify(error="agent not found"), NOT_FOUND
                agents.append(agent)

        jobs = []
        if "jobs" in data:
            job_ids = data["jobs"]
            del data["jobs"]
            if not isinstance(job_ids, list):
                return jsonify(error="jobs must be a list"), BAD_REQUEST
            for job_id in job_ids:
                if not isinstance(job_id, int):
                    return jsonify(error="job must be an int"), BAD_REQUEST
                job = Job.query.filter_by(id=agent_id).first()
                if job is None:
                    return jsonify(error="job not found"), NOT_FOUND
                jobs.append(job)

        new_tag = Tag(**data)
        new_tag.agents = agents
        new_tag.jobs = jobs
        db.session.add(new_tag)
        db.session.commit()
        tag_data = new_tag.to_dict()
        logger.info("created tag %s: %s" % (new_tag.id, tag_data))
        return jsonify(tag_data), CREATED

    def delete(self, tagname=None):
        """
        A ``DELETE`` to this endpoint will delete the tag under this URI,
        including all relations to tags or jobs.

        .. http:delete:: /api/v1/tags HTTP/1.1

            **Request**

            .. sourcecode:: http

                DELETE /api/v1/tags/interesting HTTP/1.1
                Accept: application/json

            **Response**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                {
                    "id": 1,
                    "tag": "interesting"
                }

        :statuscode 204: the tag was deleted or did not exist in the first place
        """
        if isinstance(tagname, STRING_TYPES):
            tag = Tag.query.filter_by(tag=tagname).first()
        else:
            tag = Tag.query.filter_by(id=tagname).first()
        if tag is None:
            return Response(), NO_CONTENT

        db.session.delete(tag)
        db.session.commit()

        logger.info("Deleted tag %s" % tag.tag)

        return Response(), NO_CONTENT


class AgentsInTagIndexAPI(MethodView):
    def post(self, tagname=None):
        """
        A ``POST`` will add an agent to the list of agents tagged with this tag
        The tag can be given as a string or as an integer (its id).

        .. http:post:: /api/v1/tags/interesting/agents HTTP/1.1

            **Request**

            .. sourcecode:: http

                POST /api/v1/tags/interesting/agents HTTP/1.1
                Accept: application/json

                {
                    "agent_id": 1
                }

            **Response (agent newly tagged)**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                {
                    "href": "/api/v1/agents/1",
                    "id": 1
                }

            **Request**

            .. sourcecode:: http

                POST /api/v1/tags/interesting/agents HTTP/1.1
                Accept: application/json

                {
                    "agent_id": 1
                }

            **Response (agent already had that tag)**

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json

                {
                    "href": "/api/v1/agents/1",
                    "id": 1
                }

        :statuscode 200: an existing tag was found and returned
        :statuscode 201: a new tag was created
        :statuscode 400: there was something wrong with the request (such as
                            invalid columns being included)
        :statuscode 404: either the tag or the referenced agent does not exist
        """
        if isinstance(tagname, STRING_TYPES):
            tag = Tag.query.filter_by(tag=tagname).first()
        else:
            tag = Tag.query.filter_by(id=tagname).first()
        if tag is None:
            return jsonify(error="Tag not found"), NOT_FOUND

        data = json_from_request(request)
        # json_from_request returns a Response, Returncode tuple on error
        if isinstance(data, tuple):
            return data

        if len(data) > 1:
            return jsonify(error="Unknown fields in JSON data"), BAD_REQUEST

        if "agent_id" not in data:
            return jsonify(error="Field agent_id missing"), BAD_REQUEST

        agent = Agent.query.filter_by(id=data["agent_id"]).first()
        if agent is None:
            return jsonify(error="Specified agent does not exist"), NOT_FOUND

        if agent not in tag.agents:
            tag.agents.append(agent)
            db.session.commit()
            logger.info("Added agent %s (%s) to tag %s" % (
                agent.id, agent.hostname, tag.tag))
            return jsonify({"id": agent.id,
                            "href": url_for(".single_agent_api", 
                                              agent_id=agent.id)}), CREATED
        else:
            return jsonify({"id": agent.id,
                            "href": url_for(".single_agent_api", 
                                              agent_id=agent.id)}), OK

    def get(self, tagname=None):
        """
        A ``GET`` to this endpoint will list all agents associated with this tag.

        .. http:get:: /api/v1/tags/interesting/agents HTTP/1.1

            **Request**

            .. sourcecode:: http

                GET /api/v1/tags/interesting/agents HTTP/1.1
                Accept: application/json

            **Response**

            .. sourcecode:: http

                HTTP/1.1 201 CREATED
                Content-Type: application/json

                [
                    {
                        "hostname": "agent3",
                        "id": 1,
                        "href": "/api/v1/agents/1
                    }
                ]

        :statuscode 200: the list of agents associated with this tag is returned
        :statuscode 404: the tag specified does not exist
        """
        if isinstance(tagname, STRING_TYPES):
            tag = Tag.query.filter_by(tag=tagname).first()
        else:
            tag = Tag.query.filter_by(id=tagname).first()
        if tag is None:
            return jsonify(error="Tag not found"), NOT_FOUND

        out = []
        for agent in tag.agents:
            out.append({"id": agent.id,
                        "hostname": agent.hostname,
                        "href": url_for(".single_agent_api", agent_id=agent.id)})

        return jsonify(out), OK
