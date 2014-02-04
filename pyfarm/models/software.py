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
Software
========
Table of software items. Agents can reference this table to show that they
provide a given software. Jobs or jobtypes can depend on a software via the
SoftwareRequirement table
"""

from textwrap import dedent

from sqlalchemy.schema import UniqueConstraint

from pyfarm.master.application import db
from pyfarm.models.core.cfg import TABLE_SOFTWARE, MAX_TAG_LENGTH
from pyfarm.models.core.types import id_column
from pyfarm.models.core.mixins import UtilityMixins

__all__ = ("Software", )


class Software(db.Model, UtilityMixins):
    """
    Model to represent a versioned piece of software that can be present on an
    agent and may be depended on by a job and/or jobtype through the appropriate
    SoftwareRequirement table

    """
    __tablename__ = TABLE_SOFTWARE
    __table_args__ = (
        UniqueConstraint("software"), )

    id = id_column()
    software = db.Column(db.String(MAX_TAG_LENGTH), nullable=False,
                         doc=dedent("""
                         The name of the software"""))
