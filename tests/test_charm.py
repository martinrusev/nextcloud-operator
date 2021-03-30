# Copyright 2021 martinrusev
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness
from charm import NextcloudOperatorCharm

BASE_CONFIG = {
    'port': 3000,
    'image': "nextcloud:testing"
}


class TestCharm(unittest.TestCase):

    def setUp(self) -> None:
        self.harness = Harness(NextcloudOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test__pod_spec(self):
        self.harness.set_leader(True)
        self.harness.update_config(BASE_CONFIG)

        pod_spec, _ = self.harness.get_pod_spec()

        self.assertEqual(
            BASE_CONFIG['port'],
            pod_spec.get('containers')[0].get('ports')[0].get('containerPort')
        )

        self.assertEqual(
            BASE_CONFIG['image'],
            pod_spec.get('containers')[0].get('imageDetails').get('imagePath')
        )

    def test__database_relation_data(self):
        self.harness.set_leader(True)
        self.harness.update_config(BASE_CONFIG)
        self.assertEqual(self.harness.charm.state.database, {})

        # # add relation and update relation data
        rel_id = self.harness.add_relation('database', 'mysql')
        rel = self.harness.model.get_relation('database')
        self.harness.add_relation_unit(rel_id, 'mysql/0')
        test_relation_data = {
            'type': 'mysql',
            'host': '0.1.2.3:3306',
            'name': 'my-test-db',
            'user': 'test-user',
            'password': 'super!secret!password',
        }
        self.harness.update_relation_data(rel_id,
                                          'mysql/0',
                                          test_relation_data)

        # # check that charm datastore was properly set
        self.assertEqual(dict(self.harness.charm.state.database),
                         test_relation_data)

        # # now depart this relation and ensure the datastore is emptied
        self.harness.charm.on.database_relation_broken.emit(rel)
        self.assertEqual({}, dict(self.harness.charm.state.database))

    def test__update_pod_env_config(self):
        self.harness.set_leader(True)
        self.harness.update_config(BASE_CONFIG)

        # test mysql
        self.harness.charm.state.database = {
            'type': 'mysql',
            'host': '0.1.2.3:3306',
            'name': 'mysql-test-db',
            'user': 'test-user',
            'password': 'super!secret!password'
        }

        expected_config = {
            'MYSQL_DATABASE': 'mysql-test-db',
            'MYSQL_USER': 'test-user',
            'MYSQL_PASSWORD': 'super!secret!password',
            'MYSQL_HOST': '0.1.2.3:3306'
        }
        pod_spec, _ = self.harness.get_pod_spec()
        self.harness.charm._update_pod_env_config(pod_spec)
        self.assertEqual(
            pod_spec['containers'][0]['envConfig'],
            expected_config
        )

        # test postgresql
        self.harness.charm.state.database = {
            'type': 'postgres',
            'host': '0.1.2.3:5432',
            'name': 'pg-test-db',
            'user': 'test-user',
            'password': 'super!secret!password'
        }

        expected_config = {
            'POSTGRES_DB': 'pg-test-db',
            'POSTGRES_USER': 'test-user',
            'POSTGRES_PASSWORD': 'super!secret!password',
            'POSTGRES_HOST': '0.1.2.3:5432'
        }

        pod_spec, _ = self.harness.get_pod_spec()
        self.harness.charm._update_pod_env_config(pod_spec)
        self.assertEqual(
            pod_spec['containers'][0]['envConfig'],
            expected_config
        )
