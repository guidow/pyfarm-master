# No shebang line, this module is meant to be imported
#
# Copyright 2014 Ambient Entertainment GmbH & Co. KG
# Copyright 2014 Oliver Palmer
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
Tasks
-----

This module is responsible for finding and allocating tasks on agents.
"""

from datetime import timedelta, datetime
from logging import DEBUG
from json import dumps

from sqlalchemy import or_, and_, func

import requests
from requests.exceptions import ConnectionError

from pyfarm.core.logger import getLogger
from pyfarm.core.enums import AgentState, WorkState, UseAgentAddress
from pyfarm.core.config import read_env, read_env_int
from pyfarm.models.project import Project
from pyfarm.models.software import (
    Software, SoftwareVersion, JobSoftwareRequirement,
    JobTypeSoftwareRequirement)
from pyfarm.models.tag import Tag
from pyfarm.models.task import Task, TaskDependencies
from pyfarm.models.job import Job, JobDependencies
from pyfarm.models.jobqueue import JobQueue
from pyfarm.models.jobtype import JobType
from pyfarm.models.agent import Agent, AgentTagAssociation
from pyfarm.models.user import User, Role
from pyfarm.master.application import db
from pyfarm.master.utility import default_json_encoder

from pyfarm.scheduler.celery_app import celery_app


try:
    range_ = xrange
except NameError:  # pragma: no cover
    range_ = range

logger = getLogger("pf.scheduler.tasks")
# TODO Get logger configuration from pyfarm config
logger.setLevel(DEBUG)

USERAGENT = "PyFarm/1.0 (master)"
POLL_BUSY_AGENTS_INTERVAL = read_env_int(
    "PYFARM_POLL_BUSY_AGENTS_INTERVAL", 600)
POLL_IDLE_AGENTS_INTERVAL = read_env_int(
    "PYFARM_POLL_IDLE_AGENTS_INTERVAL", 3600)


@celery_app.task(ignore_result=True, bind=True)
def send_tasks_to_agent(self, agent_id):
    agent = Agent.query.filter(Agent.id == agent_id).first()
    if not agent:
        raise KeyError("agent not found")

    logger.debug("Sending assigned batches to agent %s (id %s)", agent.hostname,
                 agent_id)
    if agent.state in ["offline", "disabled"]:
        raise ValueError("agent not available")

    if agent.use_address == UseAgentAddress.PASSIVE:
        logger.debug(
            "Agent's use address mode is PASSIVE, not sending anything")
        return

    tasks_query = Task.query.filter(
        Task.agent == agent, or_(
            Task.state == None,
            ~Task.state.in_(
                [WorkState.DONE, WorkState.FAILED]))).order_by("frame asc")

    tasks_in_jobs = {}
    for task in tasks_query:
        job_tasks = tasks_in_jobs.setdefault(task.job_id, [])
        job_tasks.append(task)

    if not tasks_in_jobs:
        logger.debug("No tasks for agent %s (id %s)", agent.hostname,
                     agent.id)
        return

    for job_id, tasks in tasks_in_jobs.items():
        job = Job.query.filter_by(id=job_id).first()
        message = {"job": {"id": job.id,
                           "title": job.title,
                           "data": job.data if job.data else {},
                           "environ": job.environ if job.environ else {},
                           "by": job.by},
                   "jobtype": {"name": job.jobtype_version.jobtype.name,
                               "version": job.jobtype_version.version},
                   "tasks": []}

        for task in tasks:
            message["tasks"].append({"id": task.id,
                                     "frame": task.frame})

        logger.info("Sending a batch of %s tasks for job %s (%s) to agent %s",
                    len(tasks), job.title, job.id, agent.hostname)
        try:
            response = requests.post(agent.api_url() + "/assign",
                                     data=dumps(message,
                                                default=default_json_encoder),
                                     headers={
                                         "Content-Type": "application/json",
                                         "User-Agent": USERAGENT})

            if response.status_code not in [requests.codes.accepted,
                                            requests.codes.ok,
                                            requests.codes.created]:
                raise ValueError("Unexpected return code on sending batch to "
                                 "agent: %s", response.status_code)

        except ConnectionError as e:
            if self.request.retries < self.max_retries:
                logger.warning("Caught ConnectionError trying to contact agent "
                               "%s (id %s), retry %s of %s: %s",
                               agent.hostname,
                               agent.id,
                               self.request.retries,
                               self.max_retries,
                               e)
                self.retry(exc=e)
            else:
                logger.error("Could not contact agent %s, (id %s), marking as "
                             "offline", agent.hostname, agent.id)
                agent.state = AgentState.OFFLINE
                db.session.add(agent)
                db.session.commit()
                raise


def agents_with_tasks_at_prio(priority):
    query = Agent.query.filter(~Agent.state.in_([AgentState.OFFLINE,
                                                 AgentState.DISABLED]))
    query = query.filter(Agent.tasks.any(Task.priority == priority))
    return query.count()


def satisfies_requirements(agent, job):
    logger.debug("Checking whether agent %s satisfies the requirements for "
                 "job %s", agent.hostname, job.title)
    requirements_to_satisfy = (list(job.software_requirements) +
                               list(job.jobtype_version.software_requirements))

    satisfied_requirements = []
    for software_version in agent.software_versions:
        for requirement in requirements_to_satisfy:
            if (software_version.software == requirement.software and
                (requirement.min_version == None or
                 requirement.min_version.rank <= software_version.rank) and
                (requirement.max_version == None or
                 requirement.max_version.rank >= software_version.rank)):
                logger.debug("Software version %r satisfies requirement %r",
                             software_version, requirement)
                satisfied_requirements.append(requirement)
            else:
                logger.debug("Software version %r does not satisfy "
                             "requirement %r", software_version, requirement)

    return len(requirements_to_satisfy) <= len(satisfied_requirements)


def get_batch_agent_pair(priority, except_job_ids=None):
    """
    Get a batch of tasks with priority :attr:`priority` and a suitable agent to
    assign the to.
    Returns None if no waiting tasks with exactly priority :attr:`priority` can
    be found or no suitable agents can be found for any waiting tasks at
    :attr:`priority`.

    :returns: A tuple of a list of tasks and an agent or None

    :param int priority:
        The priority the assigned tasks must have

    :param list except_job_ids:
        A list of job ids we should not try to assign
    """
    # Try to get an already started job first
    logger.info("Trying to assign one batch of tasks, except jobs %s",
                   except_job_ids)
    job_query = Job.query.filter(or_(Job.state == None,
                                     ~Job.state.in_(
                                         [WorkState.PAUSED,
                                          WorkState.DONE,
                                          WorkState.FAILED])))
    if except_job_ids:
        job_query = job_query.filter(~Job.id.in_(except_job_ids))
    job_query = job_query.filter(Job.tasks.any(Task.state.in_(
        [WorkState.RUNNING, WorkState.DONE, WorkState.FAILED])))
    job_query = job_query.filter(Job.tasks.any(and_(
        or_(Task.state == None,
            ~Task.state.in_([WorkState.DONE, WorkState.FAILED])),
        Task.agent == None,
        Task.priority == priority)))
    job = job_query.first()
    if job:
        logger.info("Trying to assign agents to started job %s", job.title)

    # Only if that didn't produce anything, try to start a queued one
    if not job:
        job_query = Job.query.filter(or_(Job.state == None,
                                         ~Job.state.in_(
                                             [WorkState.PAUSED,
                                              WorkState.DONE,
                                              WorkState.FAILED])))
        # Make sure we don't start jobs with unfulfilled dependencies
        job_query.filter(~Job.parents.any(or_(Job.state == None,
                                              Job.state != WorkState.DONE)))
        if except_job_ids:
            job_query = job_query.filter(~Job.id.in_(except_job_ids))
        job_query = job_query.filter(
            Job.tasks.any(
                and_(or_(Task.state == None,
                         ~Task.state.in_([WorkState.DONE, WorkState.FAILED])),
                     Task.agent == None,
                     Task.priority == priority)))
        job = job_query.order_by("time_submitted asc").first()
        if job:
            logger.debug("Starting job %r (id %s) now", job.title, job.id)
        else:
            logger.debug("Did not find a job with unassigned tasks at "
                         "priority %s", priority)
            return None

    tasks_query = Task.query.filter(Task.job == job,
                                    or_(Task.state == None,
                                        ~Task.state.in_([WorkState.DONE,
                                                         WorkState.FAILED])),
                                    or_(Task.agent == None,
                                        Task.agent.has(Agent.state.in_(
                                            [AgentState.OFFLINE,
                                             AgentState.DISABLED]))),
                                    Task.priority == priority).order_by(
                                        "frame asc")
    batch = []
    for task in tasks_query:
        if (len(batch) < job.batch and
            (not job.jobtype_version.batch_contiguous or
             (len(batch) == 0 or
              batch[-1].frame + job.by == task.frame))):
                 batch.append(task)

    logger.debug("Looking for an agent for a batch of %s tasks from job %s",
                 len(batch), job.title)

    # First look for an agent that has already successfully worked on tasks from
    # the same job in the past
    query = db.session.query(Agent, func.count(
        SoftwareVersion.id).label("num_versions"))
    query = query.filter(Agent.state.in_([AgentState.ONLINE,
                                          AgentState.RUNNING]))
    query = query.filter(Agent.free_ram >= job.ram)
    query = query.filter(~Agent.tasks.any(or_(Task.state == None,
                                      and_(Task.state != WorkState.DONE,
                                           Task.state != WorkState.FAILED))))
    query = query.filter(Agent.tasks.any(and_(Task.state == WorkState.DONE,
                                      Task.job == job)))
    # Order by num_versions so we select agents with the fewest supported
    # software versions first
    query = query.group_by(Agent).order_by("num_versions asc")

    selected_agent = None
    for agent, num_versions in query:
        if not selected_agent and satisfies_requirements(agent, job):
            selected_agent = agent

    if not selected_agent:
        query = db.session.query(Agent, func.count(
            SoftwareVersion.id).label("num_versions"))
        query = query.filter(Agent.state.in_([AgentState.ONLINE,
                                              AgentState.RUNNING]))
        query = query.filter(Agent.free_ram >= job.ram)
        query = query.filter(~Agent.tasks.any(or_(Task.state == None,
                                          and_(
                                              Task.state != WorkState.DONE,
                                              Task.state != WorkState.FAILED))))
        query = query.group_by(Agent).order_by("num_versions asc")
        for agent, num_versions in query:
            if not selected_agent and satisfies_requirements(agent, job):
                selected_agent = agent

    if not selected_agent:
        # We did not find any suitable agents for this job, see if we can find
        # some for some other job
        logger.debug("Did not find a suitable agent for job %s, trying to find "
                     "another job", job.title)
        if except_job_ids:
            return get_batch_agent_pair(priority, except_job_ids + [job.id])
        else:
            return get_batch_agent_pair(priority, [job.id])

    return batch, selected_agent


def read_queue_tree(queue):
    # Agents already assigned to this queue before the weight scheduler runs
    queue.preassigned_agents = 0
    queue.can_use_more_agents = True
    queue.total_assigned_agents = 0

    child_queues_query = JobQueue.query.filter_by(parent_jobqueue_id=queue.id)

    queue.branches = []
    for child_queue in child_queues_query:
        child_queue = read_queue_tree(child_queue)
        queue.total_assigned_agents += child_queue.total_assigned_agents
        queue.branches.append(child_queue)

    child_jobs_query = Job.query.filter(Job.job_queue_id == queue.id,
                                        or_(Job.state == WorkState.RUNNING,
                                            Job.state == NULL))
    for job in child_jobs_query:
        # TODO Get this number as part of the above query, so we don't do one
        # query per job
        num_assigned_agents = Agent.query.filter(
            Agent.tasks.any(and_(
                or_(Task.state == WorkState.RUNNING, Task.state == None),
                Task.job == job))).count()
        job.total_assigned_agents = num_assigned_agents
        job.can_use_more_agents = True
        queue.total_assigned_agents += num_assigned_agents
        queue.branches.append(job)

    return queue


def assign_agents_by_weight(objects, max_agents):
    max_weight = 1
    min_weight = 1
    objects_at_weights = {}
    for i in objects:
        i.preassigned_agents = i.total_assigned_agents
        max_weight = max(max_weight, i.weight)
        min_weight = min(min_weight, i.weight)
        objects_at_weights[i.weight] = i

    assigned_agents = []
    agents_needed = True
    while max_agents > 0 and agents_needed:
        assigned_this_round = 0
        for floor in range_(max_weight, min_weight-1, -1):
            for current_weight in range_(max_weight, floor-1, -1):
                if current_weight in objects_at_weights:
                    for i in objects_at_weights[current_weight]:
                        if max_agents > 0 and i.can_use_more_agents:
                            assigned = []
                            if i.preassigned_agents > 0:
                                i.preassigned_agents -= 1
                                assigned_this_round += 1
                            elif (isinstance(i, Job) and
                                  (not i.maximum_agents or
                                       i.maximum_agents >
                                           i.total_assigned_agents)):
                                assigned = assign_agents_to_job(i, 1)
                                if len(assigned) > 0:
                                    i.state = WorkState.RUNNING
                            elif (not i.maximum_agents or
                                      i.maximum_agents >
                                          i.total_assigned_agents):
                                assigned = assign_agents_to_queue(i, 1)
                            assigned_this_round += len(assigned)
                            max_agents -= len(assigned)
                            assigned_agents += assigned
                            i.total_assigned_agents += len(assigned)
        if assigned_this_round == 0:
            agents_needed = False

    return assigned_agents


# TODO Make this a method of JobQueue and Job called assign_agents
def assign_agents_to_queue(queue, max_agents):
    """
    Distribute up to max_agents among the jobs and subqueues of queue.
    Returns the list of agents that have been assigned new tasks.
    """
    assigned_agents = []

    # Before anything else, make sure minima are satisfied
    minima_satisfied = False
    while max_agents > 0 and not minima_satisfied:
        unsatisfied_minima = 0
        for branch in queue.branches:
            if (branch.minimum_agents and
                branch.minimum_agents > branch.total_assigned_agents and
                branch.can_use_more_agents):
                if isinstance(branch, Job):
                    assigned = assign_agents_to_job(branch, 1)
                    if len(assigned) > 0:
                        branch.state = WorkState.RUNNING
                else:
                    assigned = assign_agents_to_queue(branch, 1)
                max_agents -= len(assigned)
                assigned_agents += assigned
                queue.total_assigned_agents += len(assigned)
                if (branch.minimum_agents > branch.total_assigned_agents and
                    branch.can_use_more_agents):
                    unsatisfied_minima += 1
        minima_satisfied = unsatisfied_minima == 0

    # Early return if we have used up the available agents at this point
    if max_agents <= 0:
        return assigned_agents

    objects_by_priority = {}
    for branch in queue.branches:
        if branch.priority not in objects_by_priority:
            objects_by_priority[branch.priority] = [branch]
        else:
            objects_by_priority[branch.priority] += [branch]
    available_priorities = sorted(objects_by_priority.keys(), reverse=True)

    for priority in available_priorities:
        objects = objects_by_priority[priority]
        agents_needed = True
        while max_agents > 0 and agents_needed:
            # Not started jobs don't get anything as long running ones or
            # subqueues still need agents
            running_jobs = [x for x in objects if isinstance(x, Job) and
                            x.state == WorkState.RUNNING]
            subqueues = [x for x in objects if isinstance(x, JobQueue) and
                         x.can_use_more_agents]
            assigned = assign_agents_by_weight(running_jobs + subqueues,
                                               max_agents)
            max_agents -= len(assigned)
            assigned_agents += assigned
            assigned_this_round = assigned
            queue.total_assigned_agents += len(assigned)

            if max_agents > 0:
                # TODO When starting jobs, start the oldest one first
                assigned = assign_agents_by_weight(objects, max_agents)
                max_agents -= len(assigned)
                assigned_agents += assigned
                assigned_this_round += assigned
                queue.total_assigned_agents += len(assigned)

            if assigned_this_round == 0:
                agents_needed = False

    if len(assigned_agents) == 0:
        queue.can_use_more_agents = False

    return assigned_agents


@celery_app.task(ignore_result=True,
                 rate_limit=read_env("PYFARM_SCHEDULER_RATE_LIMIT", "1/s"))
def assign_tasks():
    """
    Descends the tree of job queues recursively to assign agents to the jobs
    registered with those queues
    """
    logger.info("Assigning tasks to agents")
    tasks_query = Task.query.filter(
        or_(Task.state == None, ~Task.state.in_([WorkState.DONE,
                                                 WorkState.FAILED])))
    tasks_query = tasks_query.filter(
        or_(Task.agent == None,
            Task.agent.has(Agent.state.in_([AgentState.OFFLINE,
                                            AgentState.DISABLED]))))
    unassigned_tasks = tasks_query.count()
    logger.debug("Got %s unassigned tasks" % unassigned_tasks)
    if not unassigned_tasks:
        logger.info("No unassigned tasks, not assigning anything")
        return

    idle_agents = Agent.query.filter(Agent.state == AgentState.ONLINE,
                                     ~Agent.tasks.any(
                                         ~Task.state.in_([WorkState.DONE,
                                                          WorkState.FAILED]))).\
                                                              count()
    if not idle_agents:
        logger.info("No idle agents, not assigning anything")
        return

    tree_root = read_queue_tree(JobQueue())
    agents_with_new_tasks = assign_agents_to_queue(tree_root, idle_agents)

    for agent in agents_with_new_tasks:
        db.session.add(agent)
    db.session.commit()

    for agent in agents_with_new_tasks:
        logger.debug("Registering asynchronous task pusher for agent %s",
                     agent.id)
        send_tasks_to_agent.delay(agent.id)


@celery_app.task(ignore_results=True, bind=True)
def poll_agent(self, agent_id):
    agent = Agent.query.filter(Agent.id == agent_id).first()

    running_tasks_count = Task.query.filter(
        Task.agent == agent,
        or_(Task.state == None,
            Task.state == WorkState.RUNNING)).count()

    if (running_tasks_count > 0 and
        agent.last_heard_from is not None and
        agent.last_heard_from + timedelta(seconds=POLL_BUSY_AGENTS_INTERVAL) >
            datetime.utcnow()):
        return
    elif (running_tasks_count == 0 and
          agent.last_heard_from is not None and
          agent.last_heard_from + timedelta(seconds=POLL_IDLE_AGENTS_INTERVAL) >
            datetime.utcnow()):
        return

    try:
        response = requests.get(
            agent.api_url() + "/tasks/",
            headers={"User-Agent": USERAGENT})

        if response.status_code != requests.codes.ok:
            raise ValueError(
                "Unexpected return code on checking tasks in agent "
                "%s (id %s): %s" % (
                    agent.hostname, agent.id, response.status_code))
        json_data = response.json()
    except ConnectionError as e:
        if self.request.retries < self.max_retries:
            logger.warning("Caught ConnectionError trying to contact agent "
                           "%s (id %s), retry %s of %s: %s",
                           agent.hostname,
                           agent.id,
                           self.request.retries,
                           self.max_retries,
                           e)
            self.retry(exc=e)
        else:
            logger.error("Could not contact agent %s, (id %s), marking as "
                         "offline", agent.hostname, agent.id)
            agent.state = AgentState.OFFLINE
            db.session.add(agent)
            db.session.commit()
            raise

    else:
        present_task_ids = [x["id"] for x in json_data]
        assigned_task_ids = db.session.query(Task.id).filter(
            Task.agent == agent,
            or_(Task.state == None,
                Task.state == WorkState.RUNNING))

        if set(present_task_ids) - set(assigned_task_ids):
            send_tasks_to_agent.delay(agent_id)

        agent.last_heard_from = datetime.utcnow()
        db.session.add(agent)
        db.session.commit()


@celery_app.task(ignore_results=True)
def poll_agents():
    idle_agents_to_poll_query = Agent.query.filter(
        or_(Agent.last_heard_from == None,
            Agent.last_heard_from +
                timedelta(
                    seconds=POLL_IDLE_AGENTS_INTERVAL) < datetime.utcnow()),
        ~Agent.tasks.any(or_(Task.state == None,
                             Task.state == WorkState.RUNNING)),
        Agent.use_address != UseAgentAddress.PASSIVE)

    for agent in idle_agents_to_poll_query:
        poll_agent.delay(agent.id)

    busy_agents_to_poll_query = Agent.query.filter(
        or_(Agent.last_heard_from == None,
            Agent.last_heard_from +
                timedelta(
                    seconds=POLL_BUSY_AGENTS_INTERVAL) < datetime.utcnow()),
        Agent.tasks.any(or_(Task.state == None,
                            Task.state == WorkState.RUNNING)),
        Agent.use_address != UseAgentAddress.PASSIVE)

    for agent in busy_agents_to_poll_query:
        poll_agent.delay(agent.id)
