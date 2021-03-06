# No shebang line, this module is meant to be imported
#
# Copyright 2015 Ambient Entertainment GmbH & Co. KG
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

import json
from calendar import timegm
from datetime import timedelta, datetime

from flask import render_template, request

from pyfarm.models.statistics.agent_count import AgentCount


def agent_counts():
    days_back = int(request.args.get("days_back", 7))
    time_back = timedelta(days=days_back)

    agent_count_query = AgentCount.query.order_by(
        AgentCount.counted_time).filter(
            AgentCount.counted_time > datetime.utcnow() - time_back)

    online_agent_counts = []
    running_agent_counts = []
    offline_agent_counts = []
    disabled_agent_counts = []
    for sample in agent_count_query:
        timestamp = timegm(sample.counted_time.utctimetuple())
        online_agent_counts.append([timestamp, sample.num_online])
        running_agent_counts.append([timestamp, sample.num_running])
        offline_agent_counts.append([timestamp, sample.num_offline])
        disabled_agent_counts.append([timestamp, sample.num_disabled])

    area_chart = ("area_chart" in request.args and
                  request.args["area_chart"].lower() == "true")

    return render_template(
        "pyfarm/statistics/agent_counts.html",
        online_agent_counts_json=json.dumps(online_agent_counts),
        running_agent_counts_json=json.dumps(running_agent_counts),
        offline_agent_counts_json=json.dumps(offline_agent_counts),
        disabled_agent_counts_json=json.dumps(disabled_agent_counts),
        area_chart=area_chart,
        days_back=days_back)
