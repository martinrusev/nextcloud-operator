#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from ops.main import main
from ops.framework import StoredState

from ops.charm import (
    CharmBase,
    CharmEvents,
)
from ops.model import (
    ActiveStatus,
    MaintenanceStatus,
    WaitingStatus,
    BlockedStatus
)

from typing import Iterable

logger = logging.getLogger(__name__)

REQUIRED_SETTINGS = ["image"]

REQUIRED_DATABASE_FIELDS = {
    'type',  # mysql, postgres
    'host',  # in the form '<url_or_ip>:<port>', e.g. 127.0.0.1:3306
    'name',
    'user',
    'password',
}

VALID_DATABASE_TYPES = {'mysql', 'postgres'}


class NextcloudOperatorCharm(CharmBase):
    store = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        logger.debug('Initializing the NextCloud charm.')

        self.framework.observe(self.on.start, self.configure_pod)
        self.framework.observe(self.on.config_changed, self.configure_pod)
        self.framework.observe(self.on.upgrade_charm, self.configure_pod)

        # -- database relation observations
        self.framework.observe(self.on['database'].relation_changed, self.on_database_changed)
        self.framework.observe(self.on['database'].relation_broken, self.on_database_broken)

        self.store.set_default(database={})  # db configuration

    def _missing_charm_settings(self) -> Iterable[str]:
        """Return a list of required configuration settings that are not set."""
        config = self.model.config

        missing = [setting for setting in REQUIRED_SETTINGS if not config[setting]]
        return sorted(missing)

    def _check_for_config_problems(self) -> str:
        """Check for simple configuration problems and return a string describing them, otherwise an empty string."""
        problems = ""

        missing = self._missing_charm_settings()
        if missing:
            problems = "required setting(s) empty: {}".format(', '.join(missing))

        return problems

    def on_database_changed(self, event):
        """Sets configuration information for database connection."""
        if not self.unit.is_leader():
            return

        if event.unit is None:
            logger.warning("event unit can't be None when setting db config.")
            return

        # save the necessary configuration of this database connection
        database_fields = {
            field: event.relation.data[event.unit].get(field) for field in
            REQUIRED_DATABASE_FIELDS
        }

        # if any required fields are missing, warn the user and return
        missing_fields = [field for field
                          in REQUIRED_DATABASE_FIELDS
                          if database_fields.get(field) is None]
        if missing_fields:
            logger.error("Missing required data fields for related database"
                         "relation: %s", missing_fields)
            return

        # check if the passed database type is not in VALID_DATABASE_TYPES
        if database_fields['type'] not in VALID_DATABASE_TYPES:
            logger.error('Nextcloud can only accept databases of the following'
                         'types: %s', VALID_DATABASE_TYPES)
            return

        # add the new database relation data to the datastore
        self.store.database.update({
            field: value for field, value in database_fields.items()
            if value is not None
        })

        self.configure_pod(event)

    def on_database_broken(self, event):
        """Removes database connection info from the store."""
        if not self.unit.is_leader():
            return

        # remove the existing database info from datastore
        self.store.database = {}

    def _update_pod_env_config(self, pod_spec):
        """Builds the environment config based on info available in the datastore."""

        db_type = self.store.database.get("type", "").lower()
        env = {}
        if db_type == "mysql":
            env = {
                "MYSQL_DATABASE": self.store.database.get("name"),
                "MYSQL_USER": self.store.database.get("user"),
                "MYSQL_PASSWORD": self.store.database.get("password"),
                "MYSQL_HOST": self.store.database.get("host")
            }

        if db_type == "postgresql" or db_type == "postgres":
            env = {
                "POSTGRES_DB": self.store.database.get("name"),
                "POSTGRES_USER": self.store.database.get("user"),
                "POSTGRES_PASSWORD": self.store.database.get("password"),
                "POSTGRES_HOST": self.store.database.get("host")
            }
        pod_spec['containers'][0]['envConfig'] = env
        return pod_spec

    def _build_pod_spec(self):
        """Builds the pod spec based on available info in datastore`."""

        config = self.model.config

        image_details = {
            "imagePath": config["image"],
        }

        ports = [
            {"name": "http", "containerPort": config["port"], "protocol": "TCP"},
        ]
        spec = {
            'version': 3,
            'containers': [{
                'name': self.app.name,
                'imageDetails': image_details,
                'ports': ports,
                'volumeConfig': [],
                'envConfig': {},
                'kubernetes': {
                    'readinessProbe': {
                        'httpGet': {
                            'path': "/status.php",
                            'port': 'http'
                        },
                        'initialDelaySeconds': 10,
                        'timeoutSeconds': 30
                    },
                },
            }]
        }

        return spec

    def configure_pod(self, event):
        """Assemble the pod spec and apply it, if possible."""

        if not self.store.database.get('host'):
            self.unit.status = WaitingStatus('Waiting for database relation')
            return

        problems = self._check_for_config_problems()
        if problems:
            self.unit.status = BlockedStatus(problems)
            return

        if not self.unit.is_leader():
            self.unit.status = ActiveStatus()
            return

        # general pod spec component updates
        self.unit.status = MaintenanceStatus('Building pod spec.')
        pod_spec = self._build_pod_spec()

        # Set the env variables for the pod
        self._update_pod_env_config(pod_spec)

        # set the pod spec with Juju
        self.model.pod.set_spec(pod_spec)
        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(NextcloudOperatorCharm)
