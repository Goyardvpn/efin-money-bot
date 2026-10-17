"""Общая основа тестов: каждый тест работает с чистой временной базой."""

import os
import tempfile
import unittest

import database


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        # База открывается по относительному пути data/efin.db,
        # поэтому во временной папке боевые данные не затрагиваются.
        os.chdir(self._tmp.name)
        database.init_db()

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()
