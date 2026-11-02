import unittest
import warnings

import notify
import orders
import reports
import users


class T(unittest.TestCase):
    def test_get_user(self):
        self.assertEqual(users.get_user(1)["name"], "Ada")
        with self.assertRaises(KeyError):
            users.get_user(99)

    def test_deprecated_alias(self):
        with self.assertWarns(DeprecationWarning) as cm:
            u = users.fetch_user(2)
        self.assertEqual(u, users.get_user(2))
        self.assertIn("get_user", str(cm.warning))

    def test_alias_still_raises_keyerror(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with self.assertRaises(KeyError):
                users.fetch_user(99)

    def test_callers_do_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertEqual(orders.order_owner({"user_id": 1}), "Ada")
            self.assertEqual(reports.report_line(2), "2: Linus <linus@example.com>")
            self.assertEqual(reports.report_all([1, 2]), ["1: Ada <ada@example.com>", "2: Linus <linus@example.com>", "ADA"])
            self.assertEqual(notify.greeting(1), "Hello Ada!")

    def test_no_old_name_left_in_callers(self):
        import pathlib
        for f in ("orders.py", "reports.py", "notify.py"):
            self.assertNotIn("fetch_user", pathlib.Path(f).read_text(), f)


if __name__ == "__main__":
    unittest.main()
