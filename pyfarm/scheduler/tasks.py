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

import tempfile
from datetime import timedelta, datetime
from logging import DEBUG
from json import dumps
from smtplib import SMTP
from email.mime.text import MIMEText
from time import time, sleep
from sys import maxsize
from os.path import join, isfile, join
from os import remove, listdir
from errno import ENOENT

from sqlalchemy import or_, and_, func, distinct, desc, asc

import requests
from requests.exceptions import ConnectionError, RequestException
# Workaround for https://github.com/kennethreitz/requests/issues/2204
from requests.packages.urllib3.exceptions import ProtocolError

from lockfile import LockFile, AlreadyLocked

from pyfarm.core.logger import getLogger
from pyfarm.core.enums import AgentState, WorkState, _WorkState, UseAgentAddress
from pyfarm.core.config import read_env, read_env_int
from pyfarm.models.project import Project
from pyfarm.models.software import (
    Software, SoftwareVersion, JobSoftwareRequirement,
    JobTypeSoftwareRequirement)
from pyfarm.models.tag import Tag
from pyfarm.models.task import Task, TaskDependencies
from pyfarm.models.tasklog import TaskLog
from pyfarm.models.job import Job, JobDependencies
from pyfarm.models.jobqueue import JobQueue
from pyfarm.models.jobtype import JobType, JobTypeVersion
from pyfarm.models.agent import Agent, AgentTagAssociation
from pyfarm.models.user import User, Role
from pyfarm.master.application import db
from pyfarm.master.utility import default_json_encoder

from pyfarm.scheduler.celery_app import celery_app


try:
    range_ = xrange  # pylint: disable=undefined-variable
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
SCHEDULER_LOCKFILE_BASE = read_env(
    "PYFARM_SCHEDULER_LOCKFILE_BASE", "/tmp/pyfarm_scheduler_lock")
LOGFILES_DIR = read_env(
    "PYFARM_LOGFILES_DIR", join(tempfile.gettempdir(), "task_logs"))

@celery_app.task(ignore_result=True, bind=True)
def send_tasks_to_agent(self, agent_id):
    db.session.commit()
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
                                     "frame": task.frame,
                                     "attempt": task.attempts})

        logger.info("Sending a batch of %s tasks for job %s (%s) to agent %s",
                    len(tasks), job.title, job.id, agent.hostname)
        try:
            response = requests.post(agent.api_url() + "/assign",
                                     data=dumps(message,
                                                default=default_json_encoder),
                                     headers={
                                         "Content-Type": "application/json",
                                         "User-Agent": USERAGENT})

            logger.debug("Return code after sending batch to agent: %s",
                         response.status_code)
            if response.status_code == requests.codes.service_unavailable:
                logger.error("Agent %s, (id %s), answered SERVICE_UNAVAILABLE, "
                             "marking it as offline", agent.hostname, agent.id)
                agent.state = AgentState.OFFLINE
                db.session.add(agent)
                for task in tasks:
                    task.agent = None
                    task.attempts -= 1
                    db.session.add(task)
                db.session.commit()
            elif response.status_code not in [requests.codes.accepted,
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


@celery_app.task(ignore_result=True)
def assign_tasks():
    db.session.commit()
    idle_agents = Agent.query.filter(Agent.state == AgentState.ONLINE,
                                     ~Agent.tasks.any(
                                        or_(
                                        Task.state == None,
                                        ~Task.state.in_(
                                            [WorkState.DONE,
                                             WorkState.FAILED]))))

    for agent in idle_agents:
        assign_tasks_to_agent.delay(agent.id)


@celery_app.task(ignore_result=True)
def assign_tasks_to_agent(agent_id):
    lockfile_name = SCHEDULER_LOCKFILE_BASE + "-" + str(agent_id)
    lock = LockFile(lockfile_name)

    try:
        lock.acquire(timeout=-1)
        with lock:
            with open(lockfile_name, "w") as lockfile:
                lockfile.write(str(time()))

            db.session.commit()

            agent = Agent.query.filter_by(id=agent_id).first()
            if not agent:
                raise ValueError("No agent with id %s" % agent_id)

            task_count = Task.query.filter(Task.agent == agent,
                                        or_(Task.state == None,
                                            Task.state == WorkState.RUNNING)).\
                                                order_by(Task.job_id,
                                                         Task.frame).\
                                                    count()
            if task_count > 0:
                logger.debug("Agent %s already has %s tasks assigned, not "
                             "assigning any more", agent.hostname, task_count)
                return

            queue = JobQueue()
            job = queue.get_job_for_agent(agent)
            if job:
                batch = job.get_batch()
                for task in batch:
                    task.agent = agent
                    logger.info("Assigned agent %s (id %s) to task %s "
                                "(frame %s) from job %s (id %s)", agent.hostname,
                                agent.id, task.id, task.frame, job.title, job.id)
                    db.session.add(task)

                if job.state != _WorkState.RUNNING:
                    job.state = WorkState.RUNNING
                    db.session.add(job)
                db.session.commit()

                send_tasks_to_agent.delay(agent.id)
            else:
                logger.debug("Did not find a job for agent %s", agent.hostname)

    except AlreadyLocked:
        logger.debug("The scheduler lockfile is locked, the scheduler seems to "
                     "already be running for agent %s", agent_id)
        try:
            with open(lockfile_name, "r") as lockfile:
                locktime = float(lockfile.read())
                if locktime < time() - 60:
                    logger.error("The old lock was held for more than 60 "
                                 "seconds. Breaking the lock.")
                    lock.break_lock()
        except (IOError, OSError, ValueError) as e:
            # It is possible that we tried to read the file in the narrow window
            # between lock acquisition and actually writing the time
            logger.warning("Could not read a time value from the scheduler "
                           "lockfile. Waiting 1 second before trying again. "
                           "Error: %s", e)
            sleep(1)
        try:
            with open(lockfile_name, "r") as lockfile:
                locktime = float(lockfile.read())
                if locktime < time() - 60:
                    logger.error("The old lock was held for more than 60 "
                                 "seconds. Breaking the lock.")
                    lock.break_lock()
        except(IOError, OSError, ValueError):
            # If we still cannot read a time value from the file after 1s,
            # there was something wrong with the process holding the lock
            logger.error("Could not read a time value from the scheduler "
                         "lockfile even after waiting 1s. Breaking the lock")
            lock.break_lock()


@celery_app.task(ignore_results=True, bind=True)
def poll_agent(self, agent_id):
    db.session.commit()
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
    # Catching ProtocolError here is a work around for
    # https://github.com/kennethreitz/requests/issues/2204
    except (ConnectionError, ProtocolError) as e:
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
    db.session.commit()
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


@celery_app.task(ignore_results=True)
def send_job_completion_mail(job_id, successful=True):
    db.session.commit()
    job = Job.query.filter_by(id=job_id).one()
    message_text = ("Job %s (id %s) has completed %s on %s.\n\n" %
                    (job.title, job.id,
                     "successfully" if successful else "unsuccessfully",
                     job.time_finished))
    if job.output_link:
        message_text += "See:\n"
        message_text += job.output_link + "\n\n"
    message_text += "Sincerely,\n\tThe PyFarm render manager"

    message = MIMEText(message_text)
    message["Subject"] = ("Job %s completed %ssuccessfully" %
                            (job.title, "" if successful else "un"))
    message["From"] = read_env("PYFARM_FROM_ADDRESS", "pyfarm@localhost")

    to = [x.email for x in job.notified_users if x.email]

    if to:
        smtp = SMTP(read_env("PYFARM_MAIL_SERVER", "localhost"))
        smtp.sendmail(read_env("PYFARM_FROM_ADDRESS",
                               "pyfarm@localhost"), to, message.as_string())
        smtp.quit()

        logger.info("Job completion mail for job %s (id %s) sent to %s",
                    job.title, job.id, to)

@celery_app.task(ignore_results=True, bind=True)
def update_agent(self, agent_id):
    db.session.commit()
    agent = Agent.query.filter_by(id=agent_id).one()
    if agent.version == agent.upgrade_to:
        return True

    try:
        response = requests.post(agent.api_url() + "/update",
                                 dumps({"version": agent.upgrade_to}),
                                 headers={"User-Agent": USERAGENT})

        logger.debug("Return code after sending update request for %s "
                     "to agent: %s", agent.upgrade_to, response.status_code)
        if response.status_code not in [requests.codes.accepted,
                                        requests.codes.ok]:
            raise ValueError("Unexpected return code on sending update request "
                             "for %s to agent %s: %s", agent.upgrade_to,
                             agent.hostname, response.status_code)
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

@celery_app.task(ignore_results=True, bind=True)
def delete_task(self, task_id):
    db.session.commit()
    task = Task.query.filter_by(id=task_id).one()
    job = task.job

    if task.agent is None or task.state in [WorkState.DONE, WorkState.FAILED]:
        logger.info("Deleting task %s (job %s - \"%s\")",
                    task.id, job.id, job.title)
        db.session.delete(task)
        db.session.flush()
    else:
        agent = task.agent
        try:
            response = requests.delete("%s/tasks/%s" %
                                            (agent.api_url(), task.id),
                                       headers={"User-Agent": USERAGENT})

            logger.info("Deleting task %s (job %s - \"%s\") from agent %s (id %s)",
                        task.id, job.id, job.title, agent.hostname, agent.id)
            if response.status_code not in [requests.codes.accepted,
                                            requests.codes.ok,
                                            requests.codes.no_content,
                                            requests.codes.not_found]:
                raise ValueError("Unexpected return code on deleting task %s on "
                                 "agent %s: %s",
                                 task.id, agent.id, response.status_code)
            else:
                db.session.delete(task)
                db.session.flush()
        # Catching ProtocolError here is a work around for
        # https://github.com/kennethreitz/requests/issues/2204
        except (ConnectionError, ProtocolError) as e:
            if self.request.retries < self.max_retries:
                logger.warning("Caught ConnectionError trying to delete task %s "
                               "from agent %s (id %s), retry %s of %s: %s",
                               task.id,
                               agent.hostname,
                               agent.id,
                               self.request.retries,
                               self.max_retries,
                               e)
                self.retry(exc=e)
            else:
                logger.error("Could not contact agent %s, (id %s), for stopping "
                             "task %s, just deleting it locally",
                             agent.hostname, agent.id, task.id)
                db.session.delete(task)
                db.session.flush()

    if job.to_be_deleted:
        num_remaining_tasks = Task.query.filter_by(job=job).count()
        if num_remaining_tasks == 0:
            logger.info("Job %s (%s) is marked for deletion and has no tasks "
                        "left, deleting it from the database now.",
                        job.id, job.title)
            db.session.delete(job)
        else:
            # Another workaround for unsufficient transaction isolation
            check_to_be_deleted_job.apply_async(args=[job.id], countdown=0.1)

    db.session.commit()


@celery_app.task(ignore_results=True)
def check_to_be_deleted_job(job_id):
    db.session.commit()

    job = Job.query.filter_by(id=job_id).first()
    if not job:
        return

    if not job.to_be_deleted:
        raise ValueError("Job %s (id %s) is not marked for deletion" %
                         (job.title, job_id))

    num_remaining_tasks = Task.query.filter_by(job=job).count()
    if num_remaining_tasks == 0:
        logger.info("Job %s (%s) is marked for deletion and has no tasks "
                    "left, deleting it from the database now.",
                    job.id, job.title)
        db.session.delete(job)

    db.session.commit()


@celery_app.task(ignore_results=True, bind=True)
def stop_task(self, task_id):
    db.session.commit()
    task = Task.query.filter_by(id=task_id).one()
    job = task.job

    if (task.agent is not None and
        task.state not in [WorkState.DONE, WorkState.FAILED]):
        agent = task.agent
        try:
            response = requests.delete("%s/tasks/%s" %
                                            (agent.api_url(), task.id),
                                       headers={"User-Agent": USERAGENT})

            logger.info("Stopping task %s (job %s - \"%s\") on agent %s (id %s)",
                        task.id, job.id, job.title, agent.hostname, agent.id)
            if response.status_code not in [requests.codes.accepted,
                                            requests.codes.ok,
                                            requests.codes.no_content,
                                            requests.codes.not_found]:
                raise ValueError("Unexpected return code on stopping task %s on "
                                 "agent %s: %s",
                                 task.id, agent.id, response.status_code)
            else:
                task.agent = None
                task.state = None
                db.session.add(task)
        # Catching ProtocolError here is a work around for
        # https://github.com/kennethreitz/requests/issues/2204
        except (ConnectionError, ProtocolError) as e:
            if self.request.retries < self.max_retries:
                logger.warning("Caught ConnectionError trying to delete task %s "
                               "from agent %s (id %s), retry %s of %s: %s",
                               task.id,
                               agent.hostname,
                               agent.id,
                               self.request.retries,
                               self.max_retries,
                               e)
                self.retry(exc=e)

    db.session.commit()


@celery_app.task(ignore_results=True)
def delete_job(job_id):
    db.session.commit()
    job = Job.query.filter_by(id=job_id).one()
    if not job.to_be_deleted:
        logger.warning("Not deleting job %s, it is not marked for deletion.",
                       job.id)
        return

    tasks_query = Task.query.filter_by(job=job)
    for task in tasks_query:
        delete_task.delay(task.id)


@celery_app.task(ignore_results=True)
def clean_up_orphaned_task_logs():
    db.session.commit()

    orphaned_task_logs = TaskLog.query.filter(
        ~TaskLog.task_associations.any()).all()
    for log in orphaned_task_logs:
        logger.info("Removing orphaned task log %s" % log.identifier)
        db.session.delete(log)
    db.session.commit()

    try:
        tasklog_files = [f for f in listdir(LOGFILES_DIR)\
                         if isfile(join(LOGFILES_DIR, f))]

        for filepath in tasklog_files:
            referencing_count = TaskLog.query.filter_by(identifier=filepath)
            if not referencing_count:
                logger.info("Deleting log file %s", join(LOGFILES_DIR, filepath))
                try:
                    remove(join(LOGFILES_DIR, filepath))
                except OSError as e:
                    if e.errno != ENOENT:
                        raise
    except OSError as e:
        if e.errno != ENOENT:
            raise
        logger.warning("Log directory %r does not exist", LOGFILES_DIR)
