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
Jobtypes
============

UI endpoints allowing seeing and manipulating jobtypes via the web interface
"""

try:
    from httplib import NOT_FOUND, INTERNAL_SERVER_ERROR, SEE_OTHER
except ImportError:  # pragma: no cover
    from http.client import NOT_FOUND, INTERNAL_SERVER_ERROR, SEE_OTHER

from flask import render_template, request, redirect, flash, url_for

from sqlalchemy import desc, func

from pyfarm.models.jobtype import JobType, JobTypeVersion
from pyfarm.models.software import JobTypeSoftwareRequirement
from pyfarm.master.application import db

def jobtypes():
    return render_template("pyfarm/user_interface/jobtypes.html",
                           jobtypes=JobType.query)

def jobtype(jobtype_id):
    """
    UI endpoint for a single jobtype. Allows showing and updating the jobtype
    """
    jobtype = JobType.query.filter_by(id=jobtype_id).first()
    if not jobtype:
        return (render_template(
                    "pyfarm/error.html", error="Jobtype %s not found" %
                    jobtype_id), NOT_FOUND)

    if request.method == "POST":
        with db.session.no_autoflush:
            jobtype.description = request.form["description"]

            new_version = JobTypeVersion(jobtype=jobtype)
            new_version.max_batch = request.form["max_batch"]
            new_version.batch_contiguous =\
                request.form["batch_contiguous"] == "true"
            new_version.classname = request.form["classname"]
            new_version.code = request.form["code"]

            max_version, = db.session.query(func.max(
                    JobTypeVersion.version)).filter_by(jobtype=jobtype).first()
            new_version.version = (max_version or 0) + 1

            previous_version = JobTypeVersion.query.filter_by(
                jobtype=jobtype).order_by(desc(JobTypeVersion.version)).first()
            if previous_version:
                for requirement in previous_version.software_requirements:
                    new_requirement = JobTypeSoftwareRequirement()
                    new_requirement.jobtype_version = new_version
                    new_requirement.software = requirement.software
                    new_requirement.min_version = requirement.min_version
                    new_requirement.max_version = requirement.max_version
                    db.session.add(new_requirement)

            db.session.add(jobtype)
            db.session.add(new_version)
            db.session.commit()

            flash("Jobtype %s updated to version %s" %
                (jobtype.name, new_version.version))

            return redirect(url_for("single_jobtype_ui", jobtype_id=jobtype.id),
                            SEE_OTHER)

    else:
        latest_version = JobTypeVersion.query.filter_by(
            jobtype=jobtype).order_by(desc(JobTypeVersion.version)).first()
        if not latest_version:
            return (render_template(
                        "pyfarm/error.html", error="Jobtype %s has no versions" %
                        jobtype_id), INTERNAL_SERVER_ERROR)

        return render_template("pyfarm/user_interface/jobtype.html",
                            jobtype=jobtype, latest_version=latest_version)

def remove_jobtype_software_requirement(jobtype_id, software_id):
    jobtype = JobType.query.filter_by(id=jobtype_id).first()
    if not jobtype:
        return (render_template(
                    "pyfarm/error.html", error="Jobtype %s not found" %
                    jobtype_id), NOT_FOUND)

    previous_version = JobTypeVersion.query.filter_by(
        jobtype=jobtype).order_by(desc(JobTypeVersion.version)).first()
    if not previous_version:
        return (render_template(
            "pyfarm/error.html", error="Jobtype %s has no versions" %
            jobtype_id), INTERNAL_SERVER_ERROR)

    new_version = JobTypeVersion(jobtype=jobtype)
    new_version.max_batch = previous_version.max_batch
    new_version.batch_contiguous = previous_version.batch_contiguous
    new_version.classname = previous_version.classname
    new_version.code = previous_version.code
    new_version.version = previous_version.version + 1

    for requirement in previous_version.software_requirements:
        if requirement.software_id != software_id:
            new_requirement = JobTypeSoftwareRequirement()
            new_requirement.jobtype_version = new_version
            new_requirement.software = requirement.software
            new_requirement.min_version = requirement.min_version
            new_requirement.max_version = requirement.max_version
            db.session.add(new_requirement)

    db.session.commit()

    flash("Software requirement has been removed from jobtype %s" %
          jobtype.name)

    return redirect(url_for("single_jobtype_ui", jobtype_id=jobtype.id),
                            SEE_OTHER)