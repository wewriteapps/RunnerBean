import os
import sys
import inspect
import logging

import beanstalkc
from resolver import resolve as resolve_import

try:
    from simplejson import loads as decode
except ImportError:
    from json import loads as decode



class Runner(object):
    _server = None
    _tubes = ['default']
    _debug = False

    log = None

    def __init__(self, callable,
                 host='0.0.0.0', port=11300, tubes=None,
                 loglevel=logging.ERROR, logfile='runnerbean.log'):

        self._host = host
        self._port = port

        logging.basicConfig(filename=logfile, level=loglevel)
        self.log = logging.getLogger(__name__)

        if isinstance(callable, basestring):
            self.callable = resolve(callable)

        elif hasattr(callable, '__call__'):
            self.callable = callable

        else:
            raise Exception('"%s" is not a callable' % self.callable.__name__)

        self._process_argspec()

        if not self._expected_args:
            raise Exception('no arguments expected for "%s"' % self.callable.__name__)

        if isinstance(tubes, (tuple, list, set)):
            self._tubes = list(tubes)

        elif isinstance(tubes, basestring):
            self._tubes = [str(tubes)]

        elif tubes is not None:
            raise Exception('"tubes" argument is not a valid type (iterable, string, unicode)')


    def __call__(self, timeout=None):
        self.run(timeout=timeout)


    def run(self, timeout=None):
        log.info('Reserving on tubes (%s):' % self._tubes)
        if timeout:
            log.info('  [setting timeout to %ds]' % timeout)

        while 1:

            if timeout:
                job = self.server.reserve(timeout=timeout)
            else:
                job = self.server.reserve()

            if not job:
                log.info('  Received empty job; skipping loop.')
                continue

            log.info('  Processing job "%s":' % job.jid)

            if not job.body:
                log.warning('    [%s] body missing; burying job for later inspection' % job.jid)
                job.bury()
                continue

            try:
                data = decode(job.body)

            except Exception as e:
                log.warning('    [%s] body was not parsable JSON; burying for later inspection' % job.jid)
                log.warning('      %s' % e)
                job.bury()
                continue

            if not data:
                log.warning('    [%s] parsed body was empty; burying job for later inspection' % job.jid)
                job.bury()
                continue

            keys = set(data.keys())
            args = set(self._expected_args)

            if args - keys:
                log.warning('    [%s] is missing keys (%s); burying job for later inspection' % (job.jid, args - keys))
                job.bury()
                continue

            try:
                log.debug('    [%s] executing job with args (%s)' % (job.jid, keys))

                if self.callable(**data):
                    log.info('    [%s] executed successfully' % (job.jid, keys))
                    job.delete()
                    continue

                log.warning('    [%s] was not executed successfully; burying job for later inspection' % job.jid)

            except Exception as e:
                log.warning('    [%s] exception raised during execution; burying for later inspection')
                log.warning('      %s' % e)

            job.bury()



    def __del__(self):
        try:
            if self.server:
                self.server.close()
        except:
            pass


    def _process_argspec(self):
        self._accepts_kwargs = False
        self._all_args = []
        self._expected_args = []
        self._preset_args = []

        log.debug('Parsing argspec for "%s":' % self.callable.__name__)

        try:
            argspec = inspect.getargspec(self.callable)
        except TypeError:
            try:
                argspec = inspect.getargspec(self.callable.__call__)
            except TypeError:
                raise Exception('could not parse argspec for "%s"' % self.callable.__name__)

        self._accepts_kwargs = argspec.keywords != None

        log.debug('  accepts keyword args: %s' % self._accepts_kwargs)

        # skip the "self" arg for class methods
        if inspect.isfunction(self.callable):
            self._all_args = argspec.args
        else:
            self._all_args = argspec.args[1:]

        log.debug('  all arguments accepted: %s' % self._all_args)

        try:
            self._expected_args = self._all_args[:-len(argspec.defaults)]
        except TypeError:
            self._expected_args = self._all_args

        log.debug('  expected arguments: %s' % self._expected_args)

        try:
            self._preset_args = self._all_args[-len(argspec.defaults):]
        except TypeError:
            self._preset_args = self._all_args

        log.debug('  args with default value: %s' % self._preset_args)


    def _get_connection(self):
        if not self._server:
            self._server = beanstalkc.Connection(host=self._host,
                                                 port=self._port)

            if self._tubes:
                self._server.ignore('default')
                for tube in self._tubes:
                    self._server.watch(tube)

        return self._server

    server = property(_get_connection)



def resolve(callable):
    log.debug('Attempting to resolve "%s"...' % callable)

    func = resolve_import(callable)

    if not func:
        raise ImportError()

    log.debug('Found "%s"' % func.__name__)

    return func
