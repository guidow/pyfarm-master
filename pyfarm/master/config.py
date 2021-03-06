# No shebang line, this module is meant to be imported
#
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
Configuration
=============

A small wrapper around :class:`pyfarm.core.config.Configuration`
that loads in the configuration files and provides backwards
compatibility for some environment variables.
"""

import os
from functools import partial

from pyfarm.core.config import (
    Configuration as _Configuration, read_env_int, read_env, read_env_bool)

try:
    WindowsError
except NameError:  # pragma: no cover
    WindowsError = OSError

read_env_no_log = partial(read_env, log_result=False)
env_bool_false = partial(read_env_bool, default=False)

class Configuration(_Configuration):
    """
    The main configuration object for the master, models and
    scheduler.  This will load in the configuration files and
    also handle any overrides present in the environment.

    :var ENVIRONMENT_OVERRIDES:
        A dictionary containing all environment variables
        we support as overrides.  This set is mainly provided
        for backwards comparability purposes or for the rare case
        where an environment override would be preferred over a
        config.
    """
    ENVIRONMENT_OVERRIDES = {
        "secret_key": ("PYFARM_SECRET_KEY", read_env_no_log),
        "autocreate_users": ("PYFARM_AUTOCREATE_USERS", read_env_bool),
        "default_job_delete_time": (
            "PYFARM_DEFAULT_JOB_DELETE_TIME", read_env_int),
        "base_url": (
            "PYFARM_BASE_URL", read_env),
        "login_disabled": ("PYFARM_LOGIN_DISABLED", read_env_bool),
        "pretty_json": ("PYFARM_JSON_PRETTY", read_env_bool),
        "echo_sql": ("PYFARM_SQL_ECHO", read_env_bool),
        "database": ("PYFARM_DATABASE_URI", read_env_no_log),
        "timestamp_format": ("PYFARM_TIMESTAMP_FORMAT", read_env),
        "allow_agents_from_loopback": (
            "PYFARM_DEV_ALLOW_AGENT_LOOPBACK_ADDRESSES", read_env_bool),
        "agent_updates_dir": ("PYFARM_AGENT_UPDATES_DIR", read_env),
        "agent_updates_webdir": ("PYFARM_AGENT_UPDATES_WEBDIR", read_env),
        "farm_name": ("PYFARM_FARM_NAME", read_env),
        "tasklogs_dir": ("PYFARM_LOGFILES_DIR", read_env),
        "dev_db_drop_all": (
            "PYFARM_DEV_APP_DB_DROP_ALL", env_bool_false),
        "dev_db_create_all": (
            "PYFARM_DEV_APP_DB_CREATE_ALL", env_bool_false),
        "instance_application": ("PYFARM_APP_INSTANCE", env_bool_false),
        "scheduler_broker": ("PYFARM_SCHEDULER_BROKER", read_env),
        "scheduler_lockfile_base": (
            "PYFARM_SCHEDULER_LOCKFILE_BASE", read_env),
        "transaction_retries": ("PYFARM_TRANSACTION_RETRIES", read_env_int),
        "agent_request_timeout": (
            "PYFARM_AGENT_REQUEST_TIMEOUT", read_env_int),
        "smtp_server": (
            "PYFARM_MAIL_SERVER", read_env),
        "from_email": (
            "PYFARM_FROM_ADDRESS", read_env)
    }

    def __init__(self):  # pylint: disable=super-on-old-class
        super(Configuration, self).__init__("pyfarm.master")
        self.load()
        self.loaded = set(self.loaded)

        # Load model configuration
        models_config = _Configuration("pyfarm.models", version=self.version)
        models_config.load()
        self.update(models_config)
        self.loaded.update(models_config.loaded)

        # Load scheduler configuration
        sched_config = _Configuration("pyfarm.scheduler", version=self.version)
        sched_config.load()
        self.update(sched_config)
        self.loaded.update(sched_config.loaded)

        try:
            items = self.ENVIRONMENT_OVERRIDES.iteritems
        except AttributeError:  # pragma: no cover
            items = self.ENVIRONMENT_OVERRIDES.items

        overrides = {}
        for config_var, (envvar, load_func) in items():
            if envvar in os.environ:
                overrides[config_var] = load_func(envvar)

        if ("PYFARM_DEV_LISTEN_ON_WILDCARD" in os.environ
                and read_env_bool("PYFARM_DEV_LISTEN_ON_WILDCARD")):
            self.update(flask_listen_address="0.0.0.0")

        self.update(overrides)

try:
    config
except NameError:  # pragma: no cover
    config = Configuration()
