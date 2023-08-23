import unittest
from time import sleep

from app.conf import Config
from database.db import connect_database
from cleanup import Cleaner

class TestServer(unittest.TestCase):

    def setUp(self) -> None:
        self.conf = Config('.env.test')
        self.db = connect_database(self.conf)
        self.cursor = self.db.cursor()

        self.cursor.execute('DELETE FROM `ratelimits`')
        self.db.commit()

    def test_cleanup(self) -> None:
        self.cursor.executemany(
            'INSERT INTO `ratelimits` (`sender`, `quota`, `quota_reset`, `quota_locked`, `msg_counter`, `rcpt_counter`) VALUES (%s, %s, %s, %s, %s, %s)',
            [
                ('test1@example.com', 1000, 1000, 0, 0, 0),
                ('test2@example.com', 1000, 1000, 0, 50, 60),
                ('test3@example.com', 3000, 1000, 0, 60, 70),
                ('test4@example.com', 3000, 1000, 1, 60, 70),
            ]
        )
        self.db.commit()

        self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits`'), 4)
        self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits` WHERE `quota` = `quota_reset`'), 2)
        self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits` WHERE `msg_counter` = 0 AND `rcpt_counter` = 0'), 1)
        self.db.commit() # needed to flush the cursor
        # sleep(1) # wait for 1 second to make sure the updated_at field is different from the created_at field
        Cleaner(self.conf)
        self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits`'), 4)
        self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits` WHERE `quota` = `quota_reset`'), 3)
        self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits` WHERE `msg_counter` = 0 AND `rcpt_counter` = 0'), 4)
        # self.assertEqual(self.cursor.execute('SELECT * FROM `ratelimits` WHERE `created_at` = `updated_at`'), 1)
