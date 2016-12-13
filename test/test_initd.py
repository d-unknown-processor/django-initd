"""This module tests the initd module."""

import os, unittest
import initd

class InitdTest(unittest.TestCase):
    """TestCase for the initd module."""

    def test_create_pid_file(self):
        """Tests initd._create_pid_file."""
        pid_file = 'pid'
        try:
            initd._create_pid_file(pid_file)
            self.assert_(os.path.exists(pid_file))
        finally:
            if os.path.exists(pid_file):
                os.remove(pid_file)
        
    def test_execute(self):
        """Tests initd.execute."""
        # using array as workaround for closure issue
        state = ['stopped']
        def create_set_state_func(s):
            def func(*arguments):
                state[0] = s
            return func
        initd_obj = initd.Initd()
        initd_obj.start = create_set_state_func('start')
        initd_obj.stop = create_set_state_func('stop')
        initd_obj.restart = create_set_state_func('restart')
        
        import sys
        original_argv = sys.argv
        
        # initialize argv
        sys.argv = [original_argv[0], None]
        
        def run_test(cmd):
            initd_obj.execute(cmd, None, None)
            self.assertEqual(state[0], cmd)

        run_test('start')
        run_test('stop')
        run_test('restart')


def suite():
    """
    Creates and returns a TestSuite for the test cases within the
    module.
    """
    return unittest.TestLoader().loadTestsFromTestCase(InitdTest)
