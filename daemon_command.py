import signal
import logging

from django.core.management.base import BaseCommand
from initd import Initd
from logging.handlers import TimedRotatingFileHandler


class DaemonCommand(BaseCommand):
    """
    Run a management command as a daemon.

    Subclass this and override the `loop_callback` method with the code the 
    daemon process should run. Optionally, override `exit_callback` with 
    code to run when the process is stopped.

    Alternatively, if your code has more complex setup/shutdown requirements,
    override `handle_noargs` along the lines of the basic version here. 
    
    Pass one of --start, --stop, --restart or --status to work as a daemon.
    Otherwise, the command will run as a standard application.
    """
    requires_model_validation = True
    WORKDIR = '.'
    UMASK = 0o022
    PID_FILE = 'daemon_command.pid'
    LOGFILE = 'daemon_command.log'
    LOGLEVEL = 'INFO'
    STDOUT = '/dev/null'
    STDERR = STDOUT
    APP = 'daemon_command'

    def add_arguments(self, parser):
        """
        Add options to daemon command, compatible for Django version >= 1.8
        :param parser: current Command parser
        :return: Nothing
        """
        parser.add_argument('--start', action='store_const', const='start', dest='action', help='Start the daemon')
        parser.add_argument('--stop', action='store_const', const='stop', dest='action', help='Stop the daemon')
        parser.add_argument('--restart', action='store_const', const='restart', dest='action',
                            help='Stop and restart the daemon')
        parser.add_argument('--status', action='store_const', const='status', dest='action',
                            help='Report whether the daemon is currently running or stopped')
        parser.add_argument('--workdir', action='store', dest='workdir', default=self.WORKDIR,
                            help='Full path of the working directory to which the process should change '
                                 'on daemon start.')
        parser.add_argument('--umask', action='store', dest='umask', default=self.UMASK, type=int,
                            help='File access creation mask ("umask") to set for the process on daemon start.')
        parser.add_argument('--pidfile', action='store', dest='pid_file', default=self.PID_FILE, help='PID filename.')
        parser.add_argument('--logfile', action='store', dest='log_file', default=self.LOGFILE, help='Path to log file')
        parser.add_argument('--loglevel', action='store', dest='log_level', default=self.LOGLEVEL, help='Log level')
        parser.add_argument('--stdout', action='store', dest='stdout', default=self.STDOUT,
                            help='Destination to redirect standard out')
        parser.add_argument('--stderr', action='store', dest='stderr', default=self.STDERR,
                            help='Destination to redirect standard error')
        parser.add_argument('--user', action='store', dest='user', default='',
                            help='Run as this user')

    def loop_callback(self):
        raise NotImplementedError

    def exit_callback(self):
        pass

    def _set_up_logging(self, log_file, log_level, log_format='%(asctime)s %(name)s %(levelname)s %(message)s'):
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % log_level)

        self.logger = logging.getLogger(self.APP)
        self.logger.setLevel(numeric_level)
        handler = TimedRotatingFileHandler(
            log_file,
            when='W0', # mondays
            encoding='UTF-8'
        )
        formatter = logging.Formatter(log_format)
        handler.setFormatter(formatter)
        handler.setLevel(numeric_level)
        self.logger.addHandler(handler)

    def handle(self, **options):
        log_file = options.pop('logfile', self.LOGFILE)
        log_level = options.pop('loglevel', self.LOGLEVEL)
        action = options.pop('action', None)

        self._set_up_logging(log_file, log_level)

        if action:
            # daemonizing so set up functions to call while running and at close
            daemon = Initd(app=self.APP, **options)
            daemon.execute(action, run=self.loop_callback, exit=self.exit_callback)
        else:
            # running in console, so set up signal to call on ctrl-c
            signal.signal(signal.SIGINT, lambda sig, frame: self.exit_callback())
            self.loop_callback()
