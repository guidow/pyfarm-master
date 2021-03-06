# No shebang line, this module is meant to be imported
#
# Copyright 2014 Ambient Entertainment GmbH & Co. KG
# Copyright 2015 Oliver Palmer
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
Job Queue Model
===============

Model for job queues
"""

from sys import maxsize
from functools import reduce
from logging import DEBUG

from sqlalchemy import event, distinct, or_, and_
from sqlalchemy.schema import UniqueConstraint

from pyfarm.core.logger import getLogger
from pyfarm.core.enums import WorkState, _WorkState, AgentState
from pyfarm.master.application import db
from pyfarm.master.config import config
from pyfarm.models.core.mixins import UtilityMixins, ReprMixin
from pyfarm.models.core.types import id_column, IDTypeWork
from pyfarm.models.agent import Agent

PREFER_RUNNING_JOBS = config.get("queue_prefer_running_jobs")
USE_TOTAL_RAM = config.get("use_total_ram_for_scheduling")
logger = getLogger("pf.models.jobqueue")

if config.get("debug_queue"):
    logger.setLevel(DEBUG)


class JobQueue(db.Model, UtilityMixins, ReprMixin):
    """
    Stores information about a job queue. Used for flexible, configurable
    distribution of computing capacity to jobs.
    """
    __tablename__ = config.get("table_job_queue")
    __table_args__ = (UniqueConstraint("parent_jobqueue_id", "name"),)

    REPR_COLUMNS = ("id", "name")

    id = id_column(IDTypeWork)

    parent_jobqueue_id = db.Column(
        IDTypeWork,
        db.ForeignKey("%s.id" % config.get("table_job_queue")),
        nullable=True,
        doc="The parent queue of this queue. If NULL, this is a top "
            "level queue.")

    name = db.Column(
        db.String(config.get("max_queue_name_length")),
        nullable=False,
        doc="The name of the job queue")

    minimum_agents = db.Column(
        db.Integer,
        nullable=True,
        doc="The scheduler will try to assign at least this number of "
            "agents to jobs in or below this queue as long as it "
            "can use them, before any other considerations.")

    maximum_agents = db.Column(
        db.Integer,
        nullable=True,
        doc="The scheduler will never assign more than this number of "
            "agents to jobs in or below this queue.")

    priority = db.Column(
        db.Integer,
        nullable=False,
        default=config.get("queue_default_priority"),
        doc="The priority of this job queue. The scheduler will not "
            "assign any nodes to other job queues or jobs with the "
            "same parent and a lower priority as long as this one "
            "can still use nodes. The minimum_agents column takes "
            "precedence over this.")

    weight = db.Column(
        db.Integer,
        nullable=False,
        default=config.get("queue_default_weight"),
        doc="The weight of this job queue. The scheduler will "
            "distribute available agents between jobs and job "
            "queues in the same queue in proportion to their "
            "weights.")

    fullpath = db.Column(
        db.String(config.get("max_queue_path_length")),
        doc="The path of this jobqueue.  This column is a "
            "database denormalization.  It is technically "
            "redundant, but faster to access than recursively "
            "querying all parent queues.  If set to NULL, the "
            "path must be computed by recursively querying "
            "the parent queues.")

    #
    # Relationship
    #
    parent = db.relationship(
        "JobQueue",
        remote_side=[id],
        backref=db.backref("children", lazy="dynamic"),
        doc="Relationship between this queue its parent")

    def path(self):
        # Import here instead of at the top to break circular dependency
        from pyfarm.scheduler.tasks import cache_jobqueue_path

        if self.fullpath:
            return self.fullpath
        else:
            cache_jobqueue_path.delay(self.id)
            path = "/%s" % (self.name or "")
            if self.parent:
                return self.parent.path() + path
            else:
                return path

    def child_queues_sorted(self):
        """
        Return child queues sorted by number of currently assigned agents with
        priority as a secondary sort key.
        """
        queues = [x for x in self.children]
        return sorted(queues, key=lambda x: x.num_assigned_agents(),
                      reverse=True)

    def child_jobs(self, filters):
        # Import down here instead of at the top to avoid circular import
        from pyfarm.models.job import Job

        jobs_query = Job.query

        if self.id:
            jobs_query = jobs_query.filter_by(queue=self)

        wanted_states = []
        if filters["state_paused"]:
            wanted_states.append(WorkState.PAUSED)
        if filters["state_running"]:
            wanted_states.append(WorkState.RUNNING)
        if filters["state_done"]:
            wanted_states.append(WorkState.DONE)
        if filters["state_failed"]:
            wanted_states.append(WorkState.FAILED)
        if filters["state_queued"]:
            jobs_query = jobs_query.filter(or_(
                Job.state == None,
                Job.state.in_(wanted_states)))
        else:
            jobs_query = jobs_query.filter(
                Job.state.in_(wanted_states))

        return sorted(jobs_query.all(), key=lambda x: x.num_assigned_agents(),
                      reverse=True)

    def num_assigned_agents(self):
        try:
            return self.assigned_agents_count
        except AttributeError:
            # Import down here instead of at the top to avoid circular import
            from pyfarm.models.task import Task
            from pyfarm.models.job import Job

            self.assigned_agents_count = 0
            for queue in self.children:
                self.assigned_agents_count += queue.num_assigned_agents()
            self.assigned_agents_count +=\
                db.session.query(distinct(Task.agent_id)).\
                    filter(Task.job.has(Job.queue == self),
                           Task.agent_id != None,
                           Task.agent.has(
                               and_(Agent.state != AgentState.OFFLINE,
                                    Agent.state != AgentState.DISABLED)),
                           or_(Task.state == None,
                               Task.state == WorkState.RUNNING)).count()

            return self.assigned_agents_count

    def clear_assigned_counts(self):
        try:
            del self.assigned_agents_count
        except AttributeError:
            pass
        if self.parent:
            self.parent.clear_assigned_counts()

    def get_job_for_agent(self, agent, unwanted_job_ids=None):
        # Import down here instead of at the top to avoid circular import
        from pyfarm.models.job import Job

        supported_types = agent.get_supported_types()
        if not supported_types:
            return None

        available_ram = agent.ram if USE_TOTAL_RAM else agent.free_ram
        child_jobs = Job.query.filter(or_(Job.state == WorkState.RUNNING,
                                          Job.state == None),
                                      Job.job_queue_id == self.id,
                                      ~Job.parents.any(or_(
                                          Job.state == None,
                                          Job.state != WorkState.DONE)),
                                      Job.jobtype_version_id.in_(
                                            supported_types),
                                      Job.ram <= available_ram).all()
        child_jobs = [x for x in child_jobs if
                      (agent.satisfies_job_requirements(x) and
                       x.id not in unwanted_job_ids)]
        if unwanted_job_ids:
            child_jobs = [x for x in child_jobs if x.id not in unwanted_job_ids]
        child_queues = JobQueue.query.filter(
            JobQueue.parent_jobqueue_id == self.id).all()

        # Before anything else, enforce minimums
        for job in child_jobs:
            if job.state == _WorkState.RUNNING:
                if (job.num_assigned_agents() < (job.minimum_agents or 0) and
                    job.num_assigned_agents() <
                        (job.maximum_agents or maxsize) and
                    job.can_use_more_agents()):
                    return job
            elif job.minimum_agents and job.minimum_agents > 0:
                return job

        for queue in child_queues:
            if (queue.num_assigned_agents() < (queue.minimum_agents or 0) and
                queue.num_assigned_agents() <
                    (queue.maximum_agents or maxsize)):
                job = queue.get_job_for_agent(agent, unwanted_job_ids)
                if job:
                    return job

        objects_by_priority = {}

        for queue in child_queues:
            if queue.priority in objects_by_priority:
                objects_by_priority[queue.priority] += [queue]
            else:
                objects_by_priority[queue.priority] = [queue]

        for job in child_jobs:
            if job.priority in objects_by_priority:
                objects_by_priority[job.priority] += [job]
            else:
                objects_by_priority[job.priority] = [job]

        available_priorities = sorted(objects_by_priority.keys(), reverse=True)

        # Work through the priorities in descending order
        for priority in available_priorities:
            objects = objects_by_priority[priority]
            active_objects = [x for x in objects if
                              (type(x) != Job or x.state == _WorkState.RUNNING)]
            weight_sum = reduce(lambda a, b: a + b.weight, active_objects, 0)
            total_assigned = reduce(lambda a, b: a + b.num_assigned_agents(),
                                    objects, 0)
            objects.sort(key=(lambda x:
                                ((float(x.num_assigned_agents()) / total_assigned)
                                    if total_assigned else 0) /
                                ((float(x.weight) / weight_sum)
                                    if weight_sum and x.weight else 1)))

            selected_job = None
            for item in objects:
                if isinstance(item, Job):
                    if item.state == _WorkState.RUNNING:
                        if (item.can_use_more_agents() and
                            item.num_assigned_agents() <
                                (item.maximum_agents or maxsize)):
                            if PREFER_RUNNING_JOBS:
                                return item
                            elif (selected_job is None or
                                  selected_job.time_submitted >
                                    item.time_submitted):
                                selected_job = item
                    elif (selected_job is None or
                          selected_job.time_submitted > item.time_submitted):
                        # If this job is not running yet, remember it, but keep
                        # looking for already running or queued but older jobs
                        selected_job = item
                if isinstance(item, JobQueue):
                    if (item.num_assigned_agents() <
                            (item.maximum_agents or maxsize)):
                        job = item.get_job_for_agent(agent, unwanted_job_ids)
                        if job:
                            return job
            if selected_job:
                return selected_job

        return None

    @staticmethod
    def top_level_unique_check(mapper, connection, target):
        if target.parent_jobqueue_id is None:
            count = JobQueue.query.filter_by(parent_jobqueue_id=None,
                                             name=target.name).count()
            if count > 0:
                raise ValueError("Cannot have two jobqueues named %r at the "
                                 "top level" % target.name)

event.listen(JobQueue, "before_insert", JobQueue.top_level_unique_check)
