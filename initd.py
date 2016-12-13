"""
Class to help with creation of initd scripts.

Use this in conjunction with the DaemonCommand management command base class.
"""
from __future__ import print_function

import logging
import os
import signal
import sys
import pwd
import time
import errno
import django

logger = logging.getLogger('django.management_commands.initd')

buffering = int(sys.version_info[0] == 3) # No unbuffered text I/O on Python 3

__all__ = ['start', 'stop', 'restart', 'status', 'execute']

"""
Django compatibility as become daemon is no more in Django framework
"""
try:
    from django.utils.daemonize import become_daemon
except ImportError: # Django >= 1.9
    if os.name == 'posix':
        def become_daemon(our_home_dir='.', out_log='/dev/null',
                          err_log='/dev/null', umask=0o022):
            """Robustly turn into a UNIX daemon, running in our_home_dir."""
            # First fork
            try:
                if os.fork() > 0:
                    sys.exit(0)     # kill off parent
            except OSError as e:
                sys.stderr.write("fork #1 failed: (%d) %s\n" % (e.errno, e.strerror))
                sys.exit(1)
            os.setsid()
            os.chdir(our_home_dir)
            os.umask(umask)

            # Second fork
            try:
                if os.fork() > 0:
                    os._exit(0)
            except OSError as e:
                sys.stderr.write("fork #2 failed: (%d) %s\n" % (e.errno, e.strerror))
                os._exit(1)

            si = open('/dev/null', 'r')
            so = open(out_log, 'a+', buffering)
            se = open(err_log, 'a+', buffering)
            os.dup2(si.fileno(), sys.stdin.fileno())
            os.dup2(so.fileno(), sys.stdout.fileno())
            os.dup2(se.fileno(), sys.stderr.fileno())
            # Set custom file descriptors so that they get proper buffering.
            sys.stdout, sys.stderr = so, se
    else:
        def become_daemon(our_home_dir='.', out_log=None, err_log=None, umask=0o022):
            """
            If we're not running under a POSIX system, just simulate the daemon
            mode by doing redirections and directory changing.
            """
            os.chdir(our_home_dir)
            os.umask(umask)
            sys.stdin.close()
            sys.stdout.close()
            sys.stderr.close()
            if err_log:
                sys.stderr = open(err_log, 'a', buffering)
            else:
                sys.stderr = NullDevice()
            if out_log:
                sys.stdout = open(out_log, 'a', buffering)
            else:
                sys.stdout = NullDevice()

        class NullDevice:
            """A writeable object that writes to nowhere -- like /dev/null."""
            def write(self, s):
                pass


class Initd(object):
    def __init__(self, pid_file='', workdir='', umask='',
                 stdout='', stderr='', user='', **kwargs):
        self.pid_file = pid_file
        self.workdir = workdir
        self.umask = umask
        self.stdout = stdout
        self.stderr = stderr
        self.user = user

    def start(self, run, exit=None):
        """
        Starts the daemon.  This daemonizes the process, so the calling process
        will just exit normally.

        Arguments:
        * run:function - The command to run (repeatedly) within the daemon.

        """
        # if there's already a pid file, check if process is running
        if os.path.exists(self.pid_file):
            with open(self.pid_file, 'r') as stream:
                pid = int(stream.read())
            try:
                # sending 0 signal doesn't do anything to live process, but 
                # will raise error if process doesn't exist
                os.kill(pid, 0)
            except OSError:
                pass
            else:
                logger.warn('Daemon already running.')
                return

        # Change uid
        if self.user:
            try:
                pw = pwd.getpwnam(self.user)
                uid = pw.pw_uid
                gid = pw.pw_gid
            except KeyError:
                logger.error("User %s not found." % self.user)
                sys.exit(1)
            try:
                os.setgid(gid)
                os.setuid(uid)
            except OSError as e:
                logger.error("Unable to change uid and gid, error is: %s" % e)
                sys.exit(1)

        become_daemon(self.workdir, self.stdout, self.stderr, self.umask)

        self._create_pid_file()

        # workaround for closure issue is putting running flag in array
        running = [True]

        def cb_term_handler(sig, frame):
            """
            Invoked when the daemon is stopping.  Tries to stop gracefully
            before forcing termination.
            
            The arguments of this function are ignored, they only exist to
            provide compatibility for a signal handler.

            """
            if exit:
                logger.debug('Calling exit handler')
                exit()
            running[0] = False

            def cb_alrm_handler(sig, frame):
                """
                Invoked when the daemon could not stop gracefully.  Forces
                exit.

                The arguments of this function are ignored, they only exist to
                provide compatibility for a signal handler.

                """
                logger.warn('Could not exit gracefully.  Forcefully exiting.')
                sys.exit(1)

            signal.signal(signal.SIGALRM, cb_alrm_handler)
            signal.alarm(5)

        signal.signal(signal.SIGTERM, cb_term_handler)

        logger.info('Starting')
        try:
            while running[0]:
                try:
                    run()
                # disabling warning for catching Exception, since it is the
                # top level loop
                except Exception as exc:  # pylint: disable-msg=W0703
                    logger.exception(exc)
        finally:
            os.remove(self.pid_file)
            logger.info('Exiting.')

    def stop(self, run=None, exit=None):
        """
        Stops the daemon.  This reads from the pid file, and sends the SIGTERM
        signal to the process with that as its pid.  This will also wait until
        the running process stops running.
        """
        try:
            with open(self.pid_file, 'r') as stream:
                pid = int(stream.read())
        except IOError as ioe:
            if ioe.errno != errno.ENOENT:
                raise
            sys.stdout.write('Stopped.\n')
            return
        sys.stdout.write('Stopping.')
        sys.stdout.flush()
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            logger.warn('Could not kill process: %s' % e)
            os.remove(self.pid_file)
            return
        while os.path.exists(self.pid_file):
            sys.stdout.write('.')
            sys.stdout.flush()
            time.sleep(0.5)
        sys.stdout.write('\n')

    def restart(self, run, exit=None):
        """
        Restarts the daemon.  This simply calls stop (if the process is running)
        and then start again.

        Arguments:
        * run:function - The command to run (repeatedly) within the daemon.
        """
        if os.path.exists(self.pid_file):
            self.stop(self.pid_file)
        print('Starting.')
        self.start(run, exit=exit)

    def status(self, run=None, exit=None):
        """
        Prints the daemon's status:
        'Running.' if is started, 'Stopped.' if it is stopped.
        """
        if os.path.exists(self.pid_file):
            with open(self.pid_file, 'r') as stream:
                pid = int(stream.read())
            try:
                # sending 0 signal doesn't do anything to live process, but 
                # will raise error if process doesn't exist
                os.kill(pid, 0)
            except OSError:
                sys.stdout.write('Stopped.\n')
                return
            else:
                sys.stdout.write('Running.\n')
                return
        else:
            sys.stdout.write('Stopped.\n')
        sys.stdout.flush()

    def execute(self, action, run=None, exit=None):
        cmd = getattr(self, action)
        cmd(run, exit)

    def _create_pid_file(self):
        """
        Outputs the current pid to the pid file specified in config.  If the
        pid file cannot be written to, the daemon aborts.
        """
        try:
            with open(self.pid_file, 'w') as stream:
                stream.write(str(os.getpid()))
        except OSError as err:
            logger.exception(err)
            logger.error('Failed to write to pid file, exiting now.')
            sys.exit(1)
