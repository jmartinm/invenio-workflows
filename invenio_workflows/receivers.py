# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2015 CERN.
#
# Invenio is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

"""Signal receivers for workflows."""

import json

from flask import current_app

from invenio_base import signals
from invenio_base.scripts.database import create, drop, recreate

from sqlalchemy.event import listen

from .models import BibWorkflowObject
from .signals import workflow_object_saved


def delete_from_index(mapper, connection, target):
    """Delete record from index."""
    from invenio_ext.es import es
    indices = current_app.config.get(
        "WORKFLOWS_HOLDING_PEN_INDICES"
    )
    doc_type = current_app.config.get(
        "WORKFLOWS_HOLDING_PEN_DOC_TYPE"
    )
    for index in indices:
        es.delete(
            index=index,
            doc_type=doc_type,
            id=target.id,
            ignore=404
        )


def create_holdingpen_index(sender, **kwargs):
    """Create the index for Holding Pen records."""
    from invenio_search.registry import mappings
    from invenio_ext.es import es

    indices = current_app.config.get(
        "WORKFLOWS_HOLDING_PEN_INDICES"
    )
    for index in indices:
        mapping = {}
        mapping_filename = "{0}.json".format(index)
        if mapping_filename in mappings:
            mapping = json.load(open(mappings[mapping_filename], "r"))
        es.indices.delete(index=index, ignore=404)
        es.indices.create(index=index, body=mapping)


def delete_holdingpen_index(sender, **kwargs):
    """Delete the index for Holding Pen records."""
    from invenio_ext.es import es
    indices = current_app.config.get(
        "WORKFLOWS_HOLDING_PEN_INDICES"
    )
    for index in indices:
        es.indices.delete(index=index, ignore=404)


def index_holdingpen_record(sender, index=None, **kwargs):
    """Index a Holding Pen record."""
    from invenio_ext.es import es
    from invenio_records.api import Record

    from .registry import workflows
    from .models import ObjectVersion

    if not sender.workflow:
        # No workflow registered to object yet. Skip indexing
        return

    if sender.version == ObjectVersion.INITIAL:
        # Ignore initial versions
        return

    workflow = workflows.get(sender.workflow.name)
    if not workflow:
        current_app.logger.error(
            "No workflow found for sender: {0}".format(sender.id)
        )
        return

    if not hasattr(sender, 'data'):
        sender.data = sender.get_data()
    if not hasattr(sender, 'extra_data'):
        sender.extra_data = sender.get_extra_data()

    record = Record({})
    record["version"] = ObjectVersion.name_from_version(sender.version)
    record["type"] = sender.data_type
    record["status"] = sender.status
    record["created"] = sender.created.isoformat()
    record["modified"] = sender.modified.isoformat()
    record["uri"] = sender.uri
    record["id_workflow"] = sender.id_workflow
    record["id_user"] = sender.id_user
    record["id_parent"] = sender.id_parent
    record["workflow"] = sender.workflow.name
    try:
        record.update(workflow.get_record(sender))
    except Exception as err:
        current_app.logger.exception(err)

    try:
        record.update(workflow.get_sort_data(sender))
    except Exception as err:
        current_app.logger.exception(err)

    # FIXME: Tmp fix to add collection due to invenio_search
    from invenio_records.recordext.functions.get_record_collections import (
        get_record_collections,
    )
    record["_collections"] = get_record_collections(record)

    if index is None:
        index = current_app.config.get("WORKFLOWS_HOLDING_PEN_INDICES")[0]

    es.index(
        index=index,
        doc_type=current_app.config.get("WORKFLOWS_HOLDING_PEN_DOC_TYPE"),
        body=dict(record),
        id=sender.id
    )

workflow_object_saved.connect(index_holdingpen_record)
listen(BibWorkflowObject, "after_delete", delete_from_index)

signals.pre_command.connect(delete_holdingpen_index, sender=drop)
signals.pre_command.connect(create_holdingpen_index, sender=create)
signals.pre_command.connect(delete_holdingpen_index, sender=recreate)
signals.pre_command.connect(create_holdingpen_index, sender=recreate)
